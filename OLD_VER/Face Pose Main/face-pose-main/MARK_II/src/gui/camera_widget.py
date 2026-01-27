"""
Camera Preview Widget
Displays live camera feed with overlays for face detection and pose visualization
"""

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont
import cv2
import numpy as np
from typing import Optional, Tuple


class CameraWidget(QWidget):
    """
    Widget for displaying camera feed with overlays
    
    Features:
    - Live camera preview
    - Face bounding box overlay
    - Head pose indicator (arrow)
    - Calibration guide overlay
    - FPS display
    """
    
    # Signals
    frame_ready = pyqtSignal(np.ndarray)
    face_detected = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Widget settings
        self.setMinimumSize(640, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Display label
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #000000; border-radius: 10px;")
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.image_label)
        
        # State
        self.current_frame: Optional[np.ndarray] = None
        self.face_landmarks = None
        self.face_box = None
        self.pitch = 0.0
        self.yaw = 0.0
        self.show_pose_indicator = True
        self.show_face_guide = False
        self.show_fps = True
        self.fps = 0.0
        self.is_face_detected = False
        
        # Calibration guide settings
        self.guide_center = (320, 200)
        self.guide_radius = 120
    
    def update_frame(self, frame: np.ndarray):
        """
        Update displayed frame with overlays
        
        Args:
            frame: BGR image from camera
        """
        if frame is None:
            return
        
        self.current_frame = frame.copy()
        
        # Draw overlays
        display_frame = self._draw_overlays(frame)
        
        # Convert to QImage and display
        self._display_image(display_frame)
        
        # Emit signal
        self.frame_ready.emit(frame)
    
    def _draw_overlays(self, frame: np.ndarray) -> np.ndarray:
        """
        Draw all overlays on the frame
        
        Args:
            frame: Input frame
            
        Returns:
            Frame with overlays
        """
        # Face bounding box
        if self.face_box is not None:
            x, y, w, h = self.face_box
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 233, 106), 2)
        
        # Head pose indicator
        if self.show_pose_indicator and self.is_face_detected:
            self._draw_pose_indicator(frame)
        
        # Calibration guide (face position guide)
        if self.show_face_guide:
            self._draw_face_guide(frame)
        
        # FPS counter
        if self.show_fps:
            cv2.putText(frame, f"FPS: {self.fps:.1f}", (10, 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 1)
        
        return frame
    
    def _draw_pose_indicator(self, frame: np.ndarray):
        """
        Draw head pose direction indicator
        
        Args:
            frame: Frame to draw on
        """
        h, w = frame.shape[:2]
        center_x, center_y = w - 70, 70
        
        # Background circle
        cv2.circle(frame, (center_x, center_y), 50, (30, 30, 50), -1)
        cv2.circle(frame, (center_x, center_y), 50, (100, 100, 120), 2)
        
        # Direction arrow based on yaw and pitch
        arrow_len = 35
        angle_rad = np.radians(-self.yaw)  # Negative for correct direction
        
        end_x = int(center_x + arrow_len * np.sin(angle_rad))
        end_y = int(center_y - arrow_len * np.cos(angle_rad) * (1 + self.pitch / 90))
        
        # Clamp to circle bounds
        dx, dy = end_x - center_x, end_y - center_y
        dist = np.sqrt(dx**2 + dy**2)
        if dist > 40:
            end_x = int(center_x + 40 * dx / dist)
            end_y = int(center_y + 40 * dy / dist)
        
        # Draw arrow
        color = (0, 233, 106) if abs(self.yaw) < 15 and abs(self.pitch) < 15 else (233, 69, 96)
        cv2.arrowedLine(frame, (center_x, center_y), (end_x, end_y), color, 3, tipLength=0.3)
        
        # Center dot
        cv2.circle(frame, (center_x, center_y), 5, (255, 255, 255), -1)
    
    def _draw_face_guide(self, frame: np.ndarray):
        """
        Draw face position guide for calibration
        
        Args:
            frame: Frame to draw on
        """
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        
        # Outer oval guide
        color = (0, 233, 106) if self.is_face_detected else (100, 100, 120)
        cv2.ellipse(frame, (cx, cy), (100, 130), 0, 0, 360, color, 2)
        
        # Inner face guide
        cv2.ellipse(frame, (cx, cy - 20), (60, 80), 0, 0, 360, color, 1)
        
        # Eye positions
        cv2.circle(frame, (cx - 30, cy - 40), 8, color, 1)
        cv2.circle(frame, (cx + 30, cy - 40), 8, color, 1)
        
        # Nose line
        cv2.line(frame, (cx, cy - 20), (cx, cy + 10), color, 1)
        
        # Mouth line  
        cv2.ellipse(frame, (cx, cy + 40), (25, 10), 0, 0, 180, color, 1)
        
        # Instructions
        if not self.is_face_detected:
            cv2.putText(frame, "Position your face here", (cx - 100, h - 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)
    
    def _display_image(self, frame: np.ndarray):
        """
        Convert frame to QPixmap and display
        
        Args:
            frame: BGR frame to display
        """
        try:
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            
            # Create QImage
            bytes_per_line = ch * w
            q_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            # Scale to fit label while maintaining aspect ratio
            pixmap = QPixmap.fromImage(q_image)
            scaled_pixmap = pixmap.scaled(
                self.image_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            self.image_label.setPixmap(scaled_pixmap)
            
        except Exception as e:
            print(f"Error displaying frame: {e}")
    
    def set_face_data(self, face_box: Optional[Tuple[int, int, int, int]], 
                      pitch: float, yaw: float, detected: bool):
        """
        Update face detection data
        
        Args:
            face_box: (x, y, w, h) tuple or None
            pitch: Head pitch angle
            yaw: Head yaw angle
            detected: Whether face is detected
        """
        self.face_box = face_box
        self.pitch = pitch
        self.yaw = yaw
        
        if detected != self.is_face_detected:
            self.is_face_detected = detected
            self.face_detected.emit(detected)
    
    def set_fps(self, fps: float):
        """Update FPS display"""
        self.fps = fps
    
    def show_calibration_guide(self, show: bool):
        """Show or hide calibration face guide"""
        self.show_face_guide = show
    
    def set_show_pose_indicator(self, show: bool):
        """Show or hide pose indicator"""
        self.show_pose_indicator = show
    
    def set_show_fps(self, show: bool):
        """Show or hide FPS counter"""
        self.show_fps = show
    
    def get_current_frame(self) -> Optional[np.ndarray]:
        """Get the current camera frame"""
        return self.current_frame
