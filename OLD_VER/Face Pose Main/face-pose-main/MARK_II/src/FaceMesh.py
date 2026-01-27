"""
Professional Face Mesh Module with Enhanced Error Handling
Tracks facial landmarks and calculates head pose with validation
"""

import cv2
import mediapipe as mp
import numpy as np
import time
from typing import Optional, Tuple, List, Any


class FaceMeshError(Exception):
    """Raised when face mesh processing fails"""
    pass


class FaceMesh:
    """
    Professional face mesh processor with MediaPipe
    
    Features:
    - 468 facial landmark tracking
    - Head pose estimation (pitch/yaw)
    - Calibration support
    - Input validation
    - Performance monitoring
    - Proper error handling
    """
    
    def __init__(self, config: dict, logger):
        """
        Initialize face mesh processor
        
        Args:
            config: Configuration dictionary
            logger: Logger instance
        """
        self.logger = logger
        self.config = config
        
        # Get configuration
        fm_config = config.get('face_mesh', {})
        self.detect_confidence = fm_config.get('detection_confidence', 0.7)
        self.track_confidence = fm_config.get('tracking_confidence', 0.8)
        self.process_width = fm_config.get('process_resolution', {}).get('width', 683)
        self.process_height = fm_config.get('process_resolution', {}).get('height', 360)
        self.angle_coefficient = fm_config.get('angle_coefficient', 1.0)
        
        # State variables
        self.pitch = 0.0
        self.yaw = 0.0
        self.pitchOffset = 0.0
        self.yawOffset = 0.0
        self.face = []
        
        # Calibration state
        self.calibrated = False
        self.calibrationEntryTime = -1
        self.calibrationInstruction = "Position your head neutrally"
        
        # Get calibration config
        cal_config = config.get('calibration', {}).get('head_pose', {})
        self.neutral_hold_time = cal_config.get('neutral_hold_time', 5)
        self.calibration_time = cal_config.get('calibration_time', 3)
        
        # Performance tracking
        self.process_count = 0
        self.error_count = 0
        self.last_process_time = 0
        
        # Face outline indexes (key points for pose estimation)
        self.FACE_OUTLINE_INDEXES = [33, 263, 1, 61, 291, 199]
        
        # Initialize MediaPipe Face Mesh
        self.face_mesh = None
        self.drawing_spec = None
        self.use_legacy_api = False
        
        try:
            self.logger.info("Initializing MediaPipe Face Mesh...")
            
            # Try the legacy solutions API first
            try:
                self.face_mesh = mp.solutions.face_mesh.FaceMesh(
                    min_detection_confidence=self.detect_confidence,
                    min_tracking_confidence=self.track_confidence
                )
                self.drawing_spec = mp.solutions.drawing_utils.DrawingSpec(
                    thickness=1, circle_radius=1
                )
                self.use_legacy_api = True
                self.logger.info("Face Mesh initialized with legacy API")
            except AttributeError:
                # New MediaPipe tasks API (0.10.x+)
                self.logger.info("Legacy API not available, trying new tasks API...")
                
                # For the new API, we'll use a different approach
                # Import the face landmarker
                from mediapipe.tasks import python
                from mediapipe.tasks.python import vision
                
                # Get the model path or use bundled model
                import urllib.request
                import tempfile
                import os
                
                model_path = os.path.join(tempfile.gettempdir(), "face_landmarker.task")
                if not os.path.exists(model_path):
                    self.logger.info("Downloading face landmarker model...")
                    model_url = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
                    urllib.request.urlretrieve(model_url, model_path)
                    self.logger.info("Model downloaded")
                
                base_options = python.BaseOptions(model_asset_path=model_path)
                options = vision.FaceLandmarkerOptions(
                    base_options=base_options,
                    num_faces=1,
                    min_face_detection_confidence=self.detect_confidence,
                    min_face_presence_confidence=self.track_confidence,
                    min_tracking_confidence=self.track_confidence
                )
                self.face_mesh = vision.FaceLandmarker.create_from_options(options)
                self.use_legacy_api = False
                self.logger.info("Face Mesh initialized with new tasks API")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize Face Mesh: {e}", exc_info=True)
            raise FaceMeshError(f"MediaPipe initialization failed: {e}")
    
    def process(self, image: np.ndarray) -> Optional[List]:
        """
        Process image and extract facial landmarks and pose
        
        Args:
            image: Input image (BGR format)
            
        Returns:
            List of facial landmarks if face detected, None otherwise
        """
        if not self._validate_image(image):
            return None
        
        start_time = time.time()
        
        try:
            # Resize image for processing
            image = cv2.resize(image, (self.process_width, self.process_height))
            img_h, img_w = image.shape[0], image.shape[1]
            
            # Convert to RGB
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            # Reset face landmarks
            self.face = []
            face_3d = []
            face_2d = []
            
            # Process based on API version
            if self.use_legacy_api:
                # Legacy solutions API
                rgb_image.flags.writeable = False
                results = self.face_mesh.process(rgb_image)
                
                if results.multi_face_landmarks:
                    face_landmarks = results.multi_face_landmarks[0]
                    
                    for idx, lm in enumerate(face_landmarks.landmark):
                        x = int(lm.x * img_w)
                        y = int(lm.y * img_h)
                        self.face.append([x, y])
                        
                        if idx in self.FACE_OUTLINE_INDEXES:
                            face_2d.append([x, y])
                            face_3d.append([x, y, lm.z])
            else:
                # New tasks API
                import mediapipe as mp
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
                results = self.face_mesh.detect(mp_image)
                
                if results.face_landmarks and len(results.face_landmarks) > 0:
                    face_landmarks = results.face_landmarks[0]
                    
                    for idx, lm in enumerate(face_landmarks):
                        x = int(lm.x * img_w)
                        y = int(lm.y * img_h)
                        z = lm.z if hasattr(lm, 'z') else 0.0
                        self.face.append([x, y])
                        
                        if idx in self.FACE_OUTLINE_INDEXES:
                            face_2d.append([x, y])
                            face_3d.append([x, y, z])
            
            # Check if we got landmarks
            if len(self.face) > 0:
                # Calculate head pose if we have key points
                if len(face_2d) == len(self.FACE_OUTLINE_INDEXES):
                    self._calculate_head_pose(face_2d, face_3d, img_w, img_h)
                
                # Update statistics
                self.process_count += 1
                self.error_count = 0
                
                # Log performance occasionally
                if self.process_count % 100 == 0:
                    process_time = (time.time() - start_time) * 1000
                    self.logger.debug(f"Face mesh processing: {process_time:.1f}ms")
                
                return self.face  # Return landmarks
            else:
                # No face detected
                if self.process_count % 30 == 0:  # Log occasionally
                    self.logger.debug("No face detected in frame")
                return None
                
        except cv2.error as e:
            self.error_count += 1
            self.logger.warning(f"OpenCV error in face mesh processing: {e}")
            return False
        except Exception as e:
            self.error_count += 1
            self.logger.error(f"Unexpected error in face mesh processing: {e}", exc_info=True)
            return False
    
    def _validate_image(self, image: np.ndarray) -> bool:
        """
        Validate input image
        
        Args:
            image: Image to validate
            
        Returns:
            True if valid, False otherwise
        """
        if image is None:
            self.logger.debug("Image is None")
            return False
        
        if not isinstance(image, np.ndarray):
            self.logger.warning(f"Image is not ndarray, got {type(image)}")
            return False
        
        if image.size == 0:
            self.logger.debug("Image is empty")
            return False
        
        if len(image.shape) != 3:
            self.logger.warning(f"Image has invalid shape: {image.shape}")
            return False
        
        return True
    
    def _calculate_head_pose(self, face_2d: List, face_3d: List, img_w: int, img_h: int) -> bool:
        """
        Calculate head pitch and yaw angles with crash protection
        
        Args:
            face_2d: 2D facial landmarks
            face_3d: 3D facial landmarks
            img_w: Image width
            img_h: Image height
            
        Returns:
            True if calculation successful, False otherwise
        """
        try:
            # Convert to numpy arrays
            face_2d = np.array(face_2d, dtype=np.float64)
            face_3d = np.array(face_3d, dtype=np.float64)
            
            # ===== CRASH FIX: Bounds checking for close faces =====
            # Check if any 2D landmarks are outside image bounds (face too close)
            if np.any(face_2d[:, 0] < 0) or np.any(face_2d[:, 0] > img_w):
                self.logger.debug("Face too close: landmarks outside horizontal bounds")
                return False
            if np.any(face_2d[:, 1] < 0) or np.any(face_2d[:, 1] > img_h):
                self.logger.debug("Face too close: landmarks outside vertical bounds")
                return False
            
            # Check for extreme Z-values (indicates face too close to camera)
            if np.any(np.abs(face_3d[:, 2]) > 0.5):
                self.logger.debug("Face too close: extreme Z values detected")
                return False
            
            # Check for NaN or Inf values
            if np.any(np.isnan(face_2d)) or np.any(np.isinf(face_2d)):
                self.logger.debug("Invalid face_2d values (NaN/Inf)")
                return False
            if np.any(np.isnan(face_3d)) or np.any(np.isinf(face_3d)):
                self.logger.debug("Invalid face_3d values (NaN/Inf)")
                return False
            
            # Validate minimum face size (prevent issues with very small detections)
            face_width = np.max(face_2d[:, 0]) - np.min(face_2d[:, 0])
            face_height = np.max(face_2d[:, 1]) - np.min(face_2d[:, 1])
            if face_width < 20 or face_height < 20:
                self.logger.debug("Face too small for reliable pose estimation")
                return False
            
            # ===== END CRASH FIX =====
            
            # Camera matrix (simple pinhole camera model)
            cam_matrix = np.array([
                [img_w, 0, img_h / 2],
                [0, img_w, img_w / 2],
                [0, 0, 1]
            ], dtype=np.float64)
            
            # Solve PnP (Perspective-n-Point) to get rotation vector
            success, rot_vec, trans_vec = cv2.solvePnP(
                face_3d, face_2d, cam_matrix, None,
                flags=cv2.SOLVEPNP_ITERATIVE  # More stable solver
            )
            
            if not success:
                self.logger.debug("solvePnP failed")
                return False
            
            # Validate rotation vector (crash protection)
            if rot_vec is None or np.any(np.isnan(rot_vec)) or np.any(np.isinf(rot_vec)):
                self.logger.debug("Invalid rotation vector from solvePnP")
                return False
            
            # Get rotation matrix from rotation vector
            rotation_matrix, _ = cv2.Rodrigues(rot_vec)
            
            # Validate rotation matrix
            if rotation_matrix is None or np.any(np.isnan(rotation_matrix)):
                self.logger.debug("Invalid rotation matrix")
                return False
            
            # Decompose rotation matrix to get Euler angles
            rot_ratios, _, _, _, _, _ = cv2.RQDecomp3x3(rotation_matrix)
            
            # Calculate pitch and yaw with offsets
            raw_pitch = rot_ratios[0] * 180 * np.pi * self.angle_coefficient
            raw_yaw = rot_ratios[1] * 180 * np.pi * self.angle_coefficient
            
            # Clamp to reasonable range (-90 to 90 degrees)
            raw_pitch = np.clip(raw_pitch, -90, 90)
            raw_yaw = np.clip(raw_yaw, -90, 90)
            
            self.pitch = np.round(raw_pitch) + self.pitchOffset
            self.yaw = np.round(raw_yaw) + self.yawOffset
            
            return True
            
        except cv2.error as e:
            self.logger.warning(f"OpenCV error in head pose calculation: {e}")
            return False
        except Exception as e:
            self.logger.warning(f"Error calculating head pose: {e}")
            return False
    
    def calibrate(self) -> Tuple[str, float, float]:
        """
        Perform calibration to determine neutral head position
        
        Returns:
            Tuple of (instruction, pitch_offset, yaw_offset)
        """
        pitchOffset = 0.0
        yawOffset = 0.0
        
        if self.calibrationEntryTime == -1:
            # Start calibration
            self.calibrationEntryTime = time.time()
            self.yawOffset = 0
            self.pitchOffset = 0
            self.calibrationInstruction = "Position your head neutrally"
            self.logger.info("Head pose calibration started")
        
        elapsed_time = time.time() - self.calibrationEntryTime
        
        # Phase 1: Position head neutrally
        if elapsed_time >= self.neutral_hold_time and elapsed_time < (self.neutral_hold_time + self.calibration_time):
            self.calibrationInstruction = "Stay still"
            
        # Phase 2: Calculate offsets
        if elapsed_time >= (self.neutral_hold_time + self.calibration_time):
            pitchOffset = self.pitch * -1.0
            yawOffset = self.yaw * -1.0
            self.calibrationEntryTime = -1
            self.calibrated = True
            self.logger.info(f"Calibration complete: pitch_offset={pitchOffset:.1f}, yaw_offset={yawOffset:.1f}")
        
        return self.calibrationInstruction, pitchOffset, yawOffset
    
    def reset_calibration(self):
        """Reset calibration state"""
        self.calibrated = False
        self.calibrationEntryTime = -1
        self.pitchOffset = 0.0
        self.yawOffset = 0.0
        self.logger.info("Calibration reset")
    
    def set_offsets(self, pitch_offset: float, yaw_offset: float):
        """
        Manually set calibration offsets
        
        Args:
            pitch_offset: Pitch offset in degrees
            yaw_offset: Yaw offset in degrees
        """
        self.pitchOffset = pitch_offset
        self.yawOffset = yaw_offset
        self.calibrated = True
        self.logger.info(f"Offsets set: pitch={pitch_offset:.1f}, yaw={yaw_offset:.1f}")
    
    def get_yaw_pitch(self) -> Tuple[float, float]:
        """
        Get current yaw and pitch angles
        
        Returns:
            Tuple of (yaw, pitch)
        """
        return (self.yaw, self.pitch)
    
    def get_true_angles(self) -> Tuple[float, float]:
        """
        Get angles without offsets (raw values)
        
        Returns:
            Tuple of (yaw, pitch) without offsets
        """
        return (self.yaw - self.yawOffset, self.pitch - self.pitchOffset)
    
    def has_face(self) -> bool:
        """Check if a face is currently detected"""
        return len(self.face) > 0
    
    def get_stats(self) -> dict:
        """Get processing statistics"""
        return {
            'process_count': self.process_count,
            'error_count': self.error_count,
            'calibrated': self.calibrated,
            'has_face': self.has_face(),
            'pitch': self.pitch,
            'yaw': self.yaw
        }
    
    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self, 'face_mesh') and self.face_mesh is not None:
            self.face_mesh.close()
            self.logger.info("Face Mesh cleaned up")
