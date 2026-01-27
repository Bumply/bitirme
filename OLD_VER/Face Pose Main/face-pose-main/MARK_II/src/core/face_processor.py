"""
Face Processor
Combined face mesh and gesture recognition for threading model
"""

from PyQt5.QtCore import QObject, pyqtSignal
import numpy as np
import time
from typing import Optional, Tuple, List
import sys
import os

# Add parent directory to path for imports
_current_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(_current_dir)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from FaceMesh import FaceMesh
from GestureRecognizer import GestureRecognizer, Gesture


class FaceProcessor(QObject):
    """
    Combined face mesh and gesture processing
    
    Runs in main thread but processes efficiently
    Emits signals for GUI updates
    """
    
    # Signals
    face_detected = pyqtSignal(bool)
    pose_updated = pyqtSignal(float, float)  # pitch, yaw
    gesture_detected = pyqtSignal(str)       # gesture name
    face_box_updated = pyqtSignal(tuple)     # (x, y, w, h)
    brow_ratio_updated = pyqtSignal(float)   # for calibration
    
    def __init__(self, config: dict, logger=None):
        """
        Initialize face processor
        
        Args:
            config: Configuration dictionary
            logger: Logger instance
        """
        super().__init__()
        
        self.config = config
        self.logger = logger
        
        # Initialize modules with crash-protected versions
        self.face_mesh = FaceMesh(config, logger)
        self.gesture_recognizer = GestureRecognizer(config, logger)
        
        # State
        self.is_face_detected = False
        self.pitch = 0.0
        self.yaw = 0.0
        self.current_gesture = Gesture.NONE
        self.face_box: Optional[Tuple[int, int, int, int]] = None
        self.brow_ratio = 0.0
        
        # Calibration state
        self.pitch_offset = 0.0
        self.yaw_offset = 0.0
        self.is_calibrated = False
        
        # Performance tracking
        self.process_count = 0
        self.total_process_time = 0.0
        self.last_log_time = time.time()
        
        if self.logger:
            self.logger.info("FaceProcessor initialized")
    
    def process(self, frame: np.ndarray) -> dict:
        """
        Process a single frame
        
        Args:
            frame: BGR image from camera
            
        Returns:
            Dict with processing results
        """
        start_time = time.time()
        
        result = {
            'face_detected': False,
            'pitch': 0.0,
            'yaw': 0.0,
            'gesture': Gesture.NONE,
            'brow_raised': False,
            'face_box': None,
            'brow_ratio': 0.0,
            'landmarks': None
        }
        
        if frame is None:
            return result
        
        try:
            # Process with FaceMesh (returns landmarks or None/False)
            landmarks = self.face_mesh.process(frame)
            
            # landmarks can be a list, None, or False
            if landmarks is not None and landmarks is not False and len(landmarks) > 0:
                result['face_detected'] = True
                result['landmarks'] = landmarks
                
                # Get head pose
                result['pitch'] = self.face_mesh.pitch
                result['yaw'] = self.face_mesh.yaw
                
                # Calculate face bounding box from landmarks
                result['face_box'] = self._calculate_face_box(landmarks, frame.shape)
                
                # Process gestures
                gesture_result = self.gesture_recognizer.process(
                    landmarks, 
                    self.face_mesh.pitch, 
                    self.face_mesh.yaw,
                    self.pitch_offset,
                    self.yaw_offset
                )
                
                # Always get brow_raised and brow_ratio from gesture recognizer
                result['brow_raised'] = self.gesture_recognizer.brow_raised
                result['brow_ratio'] = self.gesture_recognizer.normalized_ratio
                
                if gesture_result:
                    result['gesture'] = self.gesture_recognizer.get_gesture()
            
            # Update internal state
            self._update_state(result)
            
            # Emit signals
            self._emit_signals(result)
            
            # Performance tracking
            process_time = (time.time() - start_time) * 1000
            self.total_process_time += process_time
            self.process_count += 1
            
            # Log performance periodically
            if time.time() - self.last_log_time > 30:
                avg_time = self.total_process_time / max(1, self.process_count)
                if self.logger:
                    self.logger.debug(f"FaceProcessor avg: {avg_time:.1f}ms, count: {self.process_count}")
                self.process_count = 0
                self.total_process_time = 0.0
                self.last_log_time = time.time()
            
            return result
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"FaceProcessor error: {e}")
            return result
    
    def _calculate_face_box(self, landmarks: List, shape: tuple) -> Tuple[int, int, int, int]:
        """
        Calculate face bounding box from landmarks
        
        Args:
            landmarks: Face landmarks as list of [x, y] coordinates
            shape: Image shape (h, w, c)
            
        Returns:
            (x, y, w, h) tuple
        """
        try:
            h, w = shape[:2]
            
            # Get x,y coordinates from landmarks
            xs = []
            ys = []
            
            for lm in landmarks:
                # Landmarks are [x, y] pixel coordinates (already scaled)
                if isinstance(lm, (list, tuple)) and len(lm) >= 2:
                    xs.append(int(lm[0]))
                    ys.append(int(lm[1]))
                elif hasattr(lm, 'x') and hasattr(lm, 'y'):
                    # Handle object-style landmarks
                    xs.append(int(lm.x * w))
                    ys.append(int(lm.y * h))
            
            if len(xs) < 10:
                return None
            
            # Calculate bounding box with padding
            x_min = max(0, min(xs) - 20)
            y_min = max(0, min(ys) - 30)
            x_max = min(w, max(xs) + 20)
            y_max = min(h, max(ys) + 20)
            
            return (x_min, y_min, x_max - x_min, y_max - y_min)
            
        except Exception:
            return None
    
    def _update_state(self, result: dict):
        """Update internal state from results"""
        self.is_face_detected = result['face_detected']
        self.pitch = result['pitch']
        self.yaw = result['yaw']
        self.current_gesture = result['gesture']
        self.face_box = result['face_box']
        self.brow_ratio = result['brow_ratio']
    
    def _emit_signals(self, result: dict):
        """Emit Qt signals for GUI updates"""
        self.face_detected.emit(result['face_detected'])
        
        if result['face_detected']:
            self.pose_updated.emit(result['pitch'], result['yaw'])
            
            if result['face_box']:
                self.face_box_updated.emit(result['face_box'])
            
            self.brow_ratio_updated.emit(result['brow_ratio'])
            
            if result['gesture'] != Gesture.NONE:
                self.gesture_detected.emit(result['gesture'].name)
    
    def apply_calibration(self, data: dict):
        """
        Apply calibration data
        
        Args:
            data: Calibration data dict with pitch_offset, yaw_offset, brow_threshold
        """
        try:
            # Apply to face mesh
            pitch_offset = data.get('pitch_offset', 0.0)
            yaw_offset = data.get('yaw_offset', 0.0)
            self.face_mesh.set_calibration(pitch_offset, yaw_offset)
            
            # Apply to gesture recognizer
            brow_threshold = data.get('brow_threshold', 350.0)
            self.gesture_recognizer.set_threshold(brow_threshold)
            
            self.pitch_offset = pitch_offset
            self.yaw_offset = yaw_offset
            self.is_calibrated = True
            
            if self.logger:
                self.logger.info(f"Applied calibration: pitch={pitch_offset:.1f}, yaw={yaw_offset:.1f}, brow={brow_threshold:.1f}")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to apply calibration: {e}")
    
    def reset_calibration(self):
        """Reset calibration to defaults"""
        self.face_mesh.reset_calibration()
        self.gesture_recognizer.reset_calibration()
        self.pitch_offset = 0.0
        self.yaw_offset = 0.0
        self.is_calibrated = False
        
        if self.logger:
            self.logger.info("Calibration reset to defaults")
    
    def get_pose(self) -> Tuple[float, float]:
        """Get current pitch and yaw"""
        return (self.pitch, self.yaw)
    
    def get_gesture(self) -> Gesture:
        """Get current gesture"""
        return self.current_gesture
    
    def is_brow_raised(self) -> bool:
        """Check if eyebrows are currently raised"""
        return self.gesture_recognizer.brow_raised
    
    def get_brow_ratio(self) -> float:
        """Get current eyebrow ratio (for calibration)"""
        return self.brow_ratio
    
    def is_tracking(self) -> bool:
        """Check if face is currently being tracked"""
        return self.is_face_detected
    
    def get_stats(self) -> dict:
        """Get processing statistics"""
        return {
            'face_detected': self.is_face_detected,
            'pitch': self.pitch,
            'yaw': self.yaw,
            'gesture': self.current_gesture.name if self.current_gesture else 'NONE',
            'is_calibrated': self.is_calibrated,
            'process_count': self.process_count
        }
    
    def cleanup(self):
        """Release resources"""
        if self.face_mesh:
            self.face_mesh.cleanup()
        
        if self.logger:
            self.logger.info("FaceProcessor cleaned up")
