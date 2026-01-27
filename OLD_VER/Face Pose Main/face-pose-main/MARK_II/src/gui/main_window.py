"""
Main Window for MARK II Wheelchair Control System
PyQt5-based GUI optimized for Raspberry Pi 7" touchscreen (800x480)
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, 
    QStackedWidget, QStatusBar, QLabel, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont
import cv2
import numpy as np
import time
from typing import Optional

from .camera_widget import CameraWidget
from .control_panel import ControlPanel
from .calibration_wizard import CalibrationWizard
from .styles import COLORS, apply_dark_theme


class MainWindow(QMainWindow):
    """
    Main application window
    
    Layout (800x480):
    - Left: Camera preview (640px)
    - Right: Control panel (160px)
    - Bottom: Status bar
    """
    
    # Signals for controller communication
    request_calibration = pyqtSignal()
    control_enabled_changed = pyqtSignal(bool)
    user_selected = pyqtSignal(str)
    
    def __init__(self, controller=None):
        """
        Initialize main window
        
        Args:
            controller: WheelchairController instance (optional)
        """
        super().__init__()
        
        self.controller = controller
        
        # Window settings for 7" touchscreen
        self.setWindowTitle("MARK II - Wheelchair Control System")
        self.setFixedSize(800, 480)
        self.setWindowFlags(Qt.FramelessWindowHint)  # Fullscreen on Pi
        
        # State
        self.is_calibrating = False
        self.frame_count = 0
        self.fps = 0.0
        self.last_fps_time = time.time()
        
        # Setup UI
        self._setup_ui()
        self._setup_status_bar()
        
        # FPS calculation timer
        self.fps_timer = QTimer(self)
        self.fps_timer.timeout.connect(self._calculate_fps)
        self.fps_timer.start(1000)  # Every second
    
    def _setup_ui(self):
        """Setup the main UI layout"""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # Stacked widget for switching between main view and calibration
        self.stack = QStackedWidget()
        
        # === Main View (Camera + Controls) ===
        main_view = QWidget()
        main_view_layout = QHBoxLayout(main_view)
        main_view_layout.setContentsMargins(0, 0, 0, 0)
        main_view_layout.setSpacing(5)
        
        # Camera widget (left side)
        self.camera_widget = CameraWidget()
        main_view_layout.addWidget(self.camera_widget, 1)
        
        # Control panel (right side)
        self.control_panel = ControlPanel()
        self.control_panel.calibrate_clicked.connect(self._start_calibration)
        self.control_panel.settings_clicked.connect(self._show_settings)
        self.control_panel.exit_clicked.connect(self._confirm_exit)
        self.control_panel.control_toggled.connect(self._on_control_toggled)
        self.control_panel.user_changed.connect(self._on_user_changed)
        main_view_layout.addWidget(self.control_panel)
        
        # === Calibration View ===
        self.calibration_wizard = CalibrationWizard()
        self.calibration_wizard.calibration_complete.connect(self._on_calibration_complete)
        self.calibration_wizard.calibration_cancelled.connect(self._on_calibration_cancelled)
        self.calibration_wizard.step_changed.connect(self._on_calibration_step)
        
        # Add to stack
        self.stack.addWidget(main_view)
        self.stack.addWidget(self.calibration_wizard)
        
        main_layout.addWidget(self.stack)
    
    def _setup_status_bar(self):
        """Setup the status bar"""
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {COLORS['surface']};
                color: {COLORS['text_secondary']};
                border-top: 1px solid {COLORS['border']};
                font-size: 11px;
                padding: 2px;
            }}
        """)
        self.setStatusBar(self.status_bar)
        
        # Status labels
        self.status_control = QLabel("Control: OFF")
        self.status_fps = QLabel("FPS: --")
        self.status_pitch = QLabel("Pitch: --°")
        self.status_yaw = QLabel("Yaw: --°")
        self.status_arduino = QLabel("Arduino: --")
        
        for label in [self.status_control, self.status_fps, self.status_pitch, 
                      self.status_yaw, self.status_arduino]:
            label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 0 10px;")
            self.status_bar.addWidget(label)
        
        # Add stretch
        spacer = QWidget()
        spacer.setFixedWidth(1)
        self.status_bar.addWidget(spacer, 1)
        
        # Version label
        version_label = QLabel("MARK II v2.0")
        version_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding-right: 10px;")
        self.status_bar.addPermanentWidget(version_label)
    
    def update_frame(self, frame: np.ndarray):
        """
        Update camera display with new frame
        
        Args:
            frame: BGR image from camera
        """
        if frame is None:
            return
        
        self.frame_count += 1
        
        # Update camera widget
        self.camera_widget.update_frame(frame)
        
        # Update calibration wizard if active
        if self.is_calibrating:
            # Pass face detection status
            self.calibration_wizard.set_face_detected(
                self.camera_widget.is_face_detected
            )
    
    def update_face_data(self, face_box: Optional[tuple], pitch: float, 
                         yaw: float, detected: bool, brow_ratio: float = 0.0):
        """
        Update face tracking data
        
        Args:
            face_box: (x, y, w, h) or None
            pitch: Pitch angle
            yaw: Yaw angle
            detected: Whether face is detected
            brow_ratio: Eyebrow ratio for calibration
        """
        # Update camera widget
        self.camera_widget.set_face_data(face_box, pitch, yaw, detected)
        
        # Update control panel
        if detected:
            self.control_panel.update_pose(pitch, yaw, brow_ratio)
            self.status_pitch.setText(f"Pitch: {pitch:+.0f}°")
            self.status_yaw.setText(f"Yaw: {yaw:+.0f}°")
        
        # Update calibration if active
        if self.is_calibrating:
            self.calibration_wizard.update_values(pitch, yaw, brow_ratio)
    
    def update_control_status(self, enabled: bool):
        """
        Update wheelchair control status display
        
        Args:
            enabled: Whether control is enabled
        """
        self.control_panel.update_control_status(enabled)
        
        status_text = "Control: ON 🟢" if enabled else "Control: OFF 🔴"
        self.status_control.setText(status_text)
        color = COLORS['success'] if enabled else COLORS['error']
        self.status_control.setStyleSheet(f"color: {color}; padding: 0 10px; font-weight: bold;")
    
    def update_arduino_status(self, connected: bool):
        """
        Update Arduino connection status
        
        Args:
            connected: Whether Arduino is connected
        """
        self.control_panel.update_arduino_status(connected)
        
        status_text = "Arduino: ✓" if connected else "Arduino: ✗"
        color = COLORS['success'] if connected else COLORS['error']
        self.status_arduino.setText(status_text)
        self.status_arduino.setStyleSheet(f"color: {color}; padding: 0 10px;")
    
    def set_users(self, users: list):
        """
        Set available users in dropdown
        
        Args:
            users: List of username strings
        """
        self.control_panel.set_users(users)
    
    def _calculate_fps(self):
        """Calculate and update FPS display"""
        current_time = time.time()
        elapsed = current_time - self.last_fps_time
        
        if elapsed > 0:
            self.fps = self.frame_count / elapsed
        
        self.frame_count = 0
        self.last_fps_time = current_time
        
        # Update displays
        self.camera_widget.set_fps(self.fps)
        self.control_panel.update_fps(self.fps)
        self.status_fps.setText(f"FPS: {self.fps:.0f}")
    
    def _start_calibration(self):
        """Start calibration wizard"""
        self.is_calibrating = True
        self.camera_widget.show_calibration_guide(True)
        self.calibration_wizard.start()
        self.stack.setCurrentIndex(1)  # Switch to calibration view
    
    def _on_calibration_complete(self, data: dict):
        """
        Handle calibration completion
        
        Args:
            data: Calibration data dictionary
        """
        self.is_calibrating = False
        self.camera_widget.show_calibration_guide(False)
        self.stack.setCurrentIndex(0)  # Back to main view
        
        # Show success message
        QMessageBox.information(
            self, 
            "Calibration Complete",
            f"Calibration successful!\n\n"
            f"Pitch offset: {data['pitch_offset']:.1f}°\n"
            f"Yaw offset: {data['yaw_offset']:.1f}°\n"
            f"Brow threshold: {data['brow_threshold']:.1f}"
        )
        
        # Emit for controller to apply
        if self.controller:
            self.controller.apply_calibration(data)
    
    def _on_calibration_cancelled(self):
        """Handle calibration cancellation"""
        self.is_calibrating = False
        self.camera_widget.show_calibration_guide(False)
        self.stack.setCurrentIndex(0)  # Back to main view
    
    def _on_calibration_step(self, step: int, name: str):
        """Handle calibration step change"""
        # Update status bar
        self.status_bar.showMessage(f"Calibrating: Step {step + 1} - {name}", 5000)
    
    def _on_control_toggled(self, enabled: bool):
        """Handle control toggle button"""
        self.control_enabled_changed.emit(enabled)
    
    def _on_user_changed(self, username: str):
        """Handle user selection change"""
        self.user_selected.emit(username)
    
    def _show_settings(self):
        """Show settings dialog"""
        QMessageBox.information(
            self,
            "Settings",
            "Settings dialog coming soon!\n\n"
            "Configure:\n"
            "- Sensitivity\n"
            "- Speed limits\n"
            "- Camera settings"
        )
    
    def _confirm_exit(self):
        """Confirm and handle exit"""
        reply = QMessageBox.question(
            self,
            "Exit",
            "Are you sure you want to exit?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.close()
    
    def keyPressEvent(self, event):
        """Handle key presses"""
        # ESC to exit calibration or show exit dialog
        if event.key() == Qt.Key_Escape:
            if self.is_calibrating:
                self._on_calibration_cancelled()
            else:
                self._confirm_exit()
        
        # Q to quit
        elif event.key() == Qt.Key_Q:
            self._confirm_exit()
        
        # C for calibration
        elif event.key() == Qt.Key_C and not self.is_calibrating:
            self._start_calibration()
        
        # Space to toggle control
        elif event.key() == Qt.Key_Space and not self.is_calibrating:
            self.control_panel._toggle_control()
        
        super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """Handle window close"""
        # Stop timers
        self.fps_timer.stop()
        
        # Cleanup
        if self.controller:
            self.controller.shutdown()
        
        event.accept()
