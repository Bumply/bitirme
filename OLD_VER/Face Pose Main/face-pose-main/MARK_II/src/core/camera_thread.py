"""
Camera Thread
Threaded camera capture for non-blocking frame acquisition
"""

from PyQt5.QtCore import QThread, pyqtSignal
import cv2
import numpy as np
import time
import threading
from typing import Optional


class CameraThread(QThread):
    """
    Background thread for camera capture
    
    Uses a thread-safe frame buffer instead of signals to avoid blocking
    """
    
    # Signals (only for status, not frame data)
    camera_error = pyqtSignal(str)        # Emits error message
    fps_updated = pyqtSignal(float)       # Emits current FPS
    
    def __init__(self, camera_index: int = 0, width: int = 640, height: int = 480,
                 target_fps: int = 30, parent=None):
        """
        Initialize camera thread
        
        Args:
            camera_index: Camera device index
            width: Frame width
            height: Frame height
            target_fps: Target frames per second
            parent: Parent QObject
        """
        super().__init__(parent)
        
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.frame_delay = 1.0 / target_fps
        
        # State
        self.running = False
        self.capture: Optional[cv2.VideoCapture] = None
        self.use_picamera = False
        self.picamera = None
        
        # Thread-safe frame buffer
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._frame_id = 0  # Increment on each new frame
        
        # Statistics
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.current_fps = 0.0
        
        # Error recovery
        self.consecutive_failures = 0
        self.max_failures = 10
    
    def get_frame(self) -> tuple:
        """
        Get the latest frame in a thread-safe way
        
        Returns:
            (frame, frame_id) tuple, or (None, -1) if no frame available
        """
        with self._frame_lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy(), self._frame_id
            return None, -1
    
    def run(self):
        """Main thread loop - captures frames continuously"""
        self.running = True
        
        # Try to initialize camera
        if not self._init_camera():
            self.camera_error.emit("Failed to initialize camera")
            return
        
        while self.running:
            try:
                frame = self._capture_frame()
                
                if frame is not None:
                    # Store frame in thread-safe buffer (non-blocking)
                    with self._frame_lock:
                        self._latest_frame = frame
                        self._frame_id += 1
                    
                    self.frame_count += 1
                    self.consecutive_failures = 0
                else:
                    self.consecutive_failures += 1
                    if self.consecutive_failures >= self.max_failures:
                        self._attempt_reconnect()
                
                # Update FPS every second
                current_time = time.time()
                if current_time - self.last_fps_time >= 1.0:
                    self.current_fps = self.frame_count / (current_time - self.last_fps_time)
                    self.fps_updated.emit(self.current_fps)
                    self.frame_count = 0
                    self.last_fps_time = current_time
                
                # Minimal delay - just yield to other threads
                time.sleep(0.001)
                
            except Exception as e:
                self.camera_error.emit(f"Capture error: {e}")
                self.consecutive_failures += 1
                time.sleep(0.1)
        
        self._release_camera()
    
    def _init_camera(self) -> bool:
        """
        Initialize camera capture
        
        Returns:
            True if successful
        """
        try:
            # Try PiCamera first on Raspberry Pi
            if self._try_picamera():
                return True
            
            # Fall back to OpenCV
            self.capture = cv2.VideoCapture(self.camera_index)
            
            if not self.capture.isOpened():
                # Try different backends
                for backend in [cv2.CAP_V4L2, cv2.CAP_GSTREAMER, cv2.CAP_ANY]:
                    self.capture = cv2.VideoCapture(self.camera_index, backend)
                    if self.capture.isOpened():
                        break
            
            if not self.capture.isOpened():
                return False
            
            # Configure camera
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.capture.set(cv2.CAP_PROP_FPS, self.target_fps)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize latency
            
            return True
            
        except Exception as e:
            self.camera_error.emit(f"Camera init error: {e}")
            return False
    
    def _try_picamera(self) -> bool:
        """
        Try to initialize PiCamera2 with the simplest possible configuration
        
        Returns:
            True if successful
        """
        try:
            from picamera2 import Picamera2
            
            self.picamera = Picamera2()
            
            # Use simple configuration with buffer settings to prevent timeout
            # buffer_count=4 gives enough buffers, queue=False drops old frames
            config = self.picamera.create_preview_configuration(
                main={"size": (self.width, self.height)},
                buffer_count=4,
                queue=False  # Drop frames if processing can't keep up
            )
            self.picamera.configure(config)
            self.picamera.start()
            
            # Give camera time to warm up
            import time
            time.sleep(0.5)
            
            self.use_picamera = True
            print(f"PiCamera2 initialized successfully")
            return True
            
        except ImportError:
            print("PiCamera2 not installed")
            return False
        except Exception as e:
            print(f"PiCamera2 error: {e}")
            if self.picamera:
                try:
                    self.picamera.close()
                except:
                    pass
            return False
    
    def _capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a single frame
        
        Returns:
            Frame or None on failure
        """
        try:
            if self.use_picamera and self.picamera:
                # PiCamera2 capture with explicit copy to avoid buffer issues
                frame = self.picamera.capture_array()
                
                if frame is None:
                    return None
                
                # Make a complete copy immediately to release PiCamera2's buffer
                if len(frame.shape) == 3 and frame.shape[2] == 4:
                    # 4 channels - take first 3 with copy
                    frame = np.ascontiguousarray(frame[:, :, :3])
                else:
                    frame = np.ascontiguousarray(frame)
                
                return frame
            
            elif self.capture and self.capture.isOpened():
                # OpenCV capture - already BGR
                ret, frame = self.capture.read()
                if ret and frame is not None:
                    return frame
            
            return None
            
        except Exception as e:
            print(f"Capture error: {e}")
            return None
    
    def _attempt_reconnect(self):
        """Attempt to reconnect camera after failures"""
        self.camera_error.emit("Camera connection lost, attempting reconnect...")
        
        self._release_camera()
        time.sleep(1.0)
        
        if self._init_camera():
            self.camera_error.emit("Camera reconnected successfully")
            self.consecutive_failures = 0
        else:
            self.camera_error.emit("Camera reconnect failed")
    
    def _release_camera(self):
        """Release camera resources"""
        try:
            if self.use_picamera and self.picamera:
                self.picamera.stop()
                self.picamera.close()
                self.picamera = None
            
            if self.capture:
                self.capture.release()
                self.capture = None
                
        except Exception:
            pass
    
    def stop(self):
        """Stop the camera thread"""
        self.running = False
        self.wait(2000)  # Wait up to 2 seconds for thread to finish
    
    def set_resolution(self, width: int, height: int):
        """
        Change camera resolution
        
        Args:
            width: New width
            height: New height
        """
        self.width = width
        self.height = height
        
        if self.capture and self.capture.isOpened():
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    
    def get_fps(self) -> float:
        """Get current FPS"""
        return self.current_fps
