"""
Professional Camera Capture Module with Error Recovery
Handles video capture with validation, reconnection, and proper logging
"""

import cv2
from imutils.video import VideoStream
from enum import Enum
from typing import Optional
import time
import numpy as np


class CaptureSource(Enum):
    """Camera capture source types"""
    CV2 = 1
    IMUTILS = 2
    PICAMERA = 3


class CaptureError(Exception):
    """Raised when camera capture fails"""
    pass


class Capture:
    """
    Professional camera capture handler
    
    Features:
    - Multiple camera backends
    - Automatic reconnection
    - Frame validation
    - Performance monitoring
    - Proper error handling
    - Resource cleanup
    """
    
    def __init__(self, config: dict, logger):
        """
        Initialize camera capture
        
        Args:
            config: Configuration dictionary
            logger: Logger instance
        """
        self.logger = logger
        self.config = config
        
        # Get camera configuration
        cam_config = config.get('camera', {})
        self.device_id = cam_config.get('device_id', 0)
        self.width = cam_config.get('resolution', {}).get('width', 640)
        self.height = cam_config.get('resolution', {}).get('height', 480)
        self.fps = cam_config.get('fps', 30)
        self.flip_horizontal = cam_config.get('flip_horizontal', True)
        
        # Determine source type
        backend = cam_config.get('backend', 'cv2').lower()
        if backend == 'cv2':
            self.source = CaptureSource.CV2
        elif backend == 'imutils':
            self.source = CaptureSource.IMUTILS
        elif backend == 'picamera':
            self.source = CaptureSource.PICAMERA
        else:
            self.logger.warning(f"Unknown backend '{backend}', defaulting to CV2")
            self.source = CaptureSource.CV2
        
        self.cap = None
        self.is_opened = False
        self.frame_count = 0
        self.error_count = 0
        self.last_frame_time = 0
        
        # Initialize camera
        self._initialize_camera()
    
    def _initialize_camera(self):
        """Initialize the camera capture"""
        try:
            self.logger.info(f"Initializing camera (device {self.device_id}, {self.source.name})")
            
            if self.source == CaptureSource.CV2:
                self.cap = cv2.VideoCapture(self.device_id)
                if not self.cap.isOpened():
                    raise CaptureError("Failed to open camera with CV2")
                
                # Set camera properties
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                
                # Verify settings
                actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = int(self.cap.get(cv2.CAP_PROP_FPS))
                
                self.logger.info(f"Camera opened: {actual_width}x{actual_height} @ {actual_fps}fps")
                
            elif self.source == CaptureSource.IMUTILS:
                self.cap = VideoStream(src=self.device_id).start()
                time.sleep(2.0)  # Warm up camera
                self.logger.info("Camera opened with imutils")
                
            elif self.source == CaptureSource.PICAMERA:
                try:
                    from picamera2 import Picamera2
                    self.cap = Picamera2()
                    
                    # Configure camera with proper settings
                    config = self.cap.create_preview_configuration(
                        main={"size": (self.width, self.height), "format": "RGB888"}
                    )
                    self.cap.configure(config)
                    
                    # Start the camera
                    self.cap.start()
                    time.sleep(2)  # Give camera time to warm up
                    
                    self.logger.info(f"Pi Camera initialized: {self.width}x{self.height}")
                except ImportError:
                    self.logger.error("picamera2 not available, falling back to CV2")
                    self.source = CaptureSource.CV2
                    self._initialize_camera()
                    return
                except Exception as e:
                    self.logger.error(f"picamera2 initialization failed: {e}, falling back to CV2")
                    self.source = CaptureSource.CV2
                    self._initialize_camera()
                    return
            
            self.is_opened = True
            self.error_count = 0
            self.logger.info("Camera initialization successful")
            
        except Exception as e:
            self.logger.error(f"Camera initialization failed: {e}", exc_info=True)
            self.is_opened = False
            raise CaptureError(f"Failed to initialize camera: {e}")
    
    def getFrame(self) -> Optional[np.ndarray]:
        """
        Get a frame from the camera with validation
        
        Returns:
            Frame as numpy array, or None if failed
        """
        if not self.is_opened:
            self.logger.warning("Camera not opened, attempting to reconnect...")
            try:
                self._reconnect()
            except CaptureError as e:
                self.logger.error(f"Reconnection failed: {e}")
                return None
        
        try:
            frame = None
            
            if self.source == CaptureSource.CV2:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    raise CaptureError("Failed to read frame from CV2")
                    
            elif self.source == CaptureSource.IMUTILS:
                frame = self.cap.read()
                if frame is None:
                    raise CaptureError("Failed to read frame from imutils")
                    
            elif self.source == CaptureSource.PICAMERA:
                frame = self.cap.capture_array()
                if frame is None:
                    raise CaptureError("Failed to read frame from PiCamera")
            
            # Validate frame
            if not self._validate_frame(frame):
                raise CaptureError("Frame validation failed")
            
            # Flip if configured
            if self.flip_horizontal:
                frame = cv2.flip(frame, flipCode=1)
            
            # Update statistics
            self.frame_count += 1
            self.error_count = 0  # Reset error count on success
            current_time = time.time()
            
            # Calculate FPS occasionally
            if self.frame_count % 30 == 0:
                if self.last_frame_time > 0:
                    fps = 30 / (current_time - self.last_frame_time)
                    self.logger.debug(f"Camera FPS: {fps:.1f}")
                self.last_frame_time = current_time
            
            return frame
            
        except CaptureError as e:
            self.error_count += 1
            self.logger.warning(f"Frame capture error (count: {self.error_count}): {e}")
            
            # Attempt reconnect after multiple failures
            if self.error_count >= 5:
                self.logger.error("Multiple frame capture failures, attempting reconnect...")
                try:
                    self._reconnect()
                except CaptureError as reconnect_error:
                    self.logger.error(f"Reconnection failed: {reconnect_error}")
            
            return None
            
        except Exception as e:
            self.logger.error(f"Unexpected error getting frame: {e}", exc_info=True)
            self.error_count += 1
            return None
    
    def _validate_frame(self, frame: np.ndarray) -> bool:
        """
        Validate that frame is valid
        
        Args:
            frame: Frame to validate
            
        Returns:
            True if valid, False otherwise
        """
        if frame is None:
            self.logger.debug("Frame is None")
            return False
        
        if not isinstance(frame, np.ndarray):
            self.logger.debug(f"Frame is not ndarray, got {type(frame)}")
            return False
        
        if frame.size == 0:
            self.logger.debug("Frame is empty")
            return False
        
        if len(frame.shape) != 3:
            self.logger.debug(f"Frame has invalid shape: {frame.shape}")
            return False
        
        # NOTE: Disabled black frame check - PiCamera can return dark frames during warmup
        # and this was causing false validation failures
        # if np.mean(frame) < 5:
        #     self.logger.debug("Frame appears to be all black")
        #     return False
        
        return True
    
    def _reconnect(self):
        """Attempt to reconnect the camera"""
        self.logger.info("Attempting camera reconnection...")
        
        # Close existing connection
        self.release()
        
        # Wait a bit
        time.sleep(1)
        
        # Try to reconnect
        try:
            self._initialize_camera()
            self.logger.info("Camera reconnection successful")
        except CaptureError as e:
            self.logger.error(f"Camera reconnection failed: {e}")
            raise
    
    def release(self):
        """Release camera resources"""
        if self.cap is not None:
            try:
                if self.source == CaptureSource.CV2:
                    self.cap.release()
                elif self.source == CaptureSource.IMUTILS:
                    self.cap.stop()
                elif self.source == CaptureSource.PICAMERA:
                    self.cap.stop()
                
                self.logger.info("Camera released")
            except Exception as e:
                self.logger.error(f"Error releasing camera: {e}")
        
        self.cap = None
        self.is_opened = False
    
    def is_available(self) -> bool:
        """Check if camera is available"""
        return self.is_opened and self.cap is not None
    
    def get_stats(self) -> dict:
        """Get camera statistics"""
        return {
            'frame_count': self.frame_count,
            'error_count': self.error_count,
            'is_opened': self.is_opened,
            'source': self.source.name
        }
    
    def __del__(self):
        """Cleanup on deletion"""
        self.release()
