"""
Control Panel Widget
Right-side panel with status display and control buttons
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QFrame, QSpacerItem, QSizePolicy, QComboBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from .styles import COLORS, get_button_style


class StatusIndicator(QFrame):
    """Small status indicator with label"""
    
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)
        
        # Status dot
        self.dot = QLabel("●")
        self.dot.setFont(QFont("Arial", 12))
        self.dot.setStyleSheet(f"color: {COLORS['disabled']};")
        
        # Label
        self.label = QLabel(label)
        self.label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        
        # Value
        self.value = QLabel("--")
        self.value.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px; font-weight: bold;")
        self.value.setAlignment(Qt.AlignRight)
        
        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        layout.addStretch()
        layout.addWidget(self.value)
        
        self.setStyleSheet(f"background-color: {COLORS['surface']}; border-radius: 5px;")
    
    def set_status(self, active: bool, value: str = None):
        """
        Update status indicator
        
        Args:
            active: Whether status is active/good
            value: Optional value text
        """
        color = COLORS['success'] if active else COLORS['error']
        self.dot.setStyleSheet(f"color: {color};")
        
        if value is not None:
            self.value.setText(value)


class ControlPanel(QWidget):
    """
    Right-side control panel
    
    Contains:
    - User selection dropdown
    - Status indicators (Control, Arduino, FPS)
    - Control buttons (Calibrate, Settings, Exit)
    """
    
    # Signals
    calibrate_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    exit_clicked = pyqtSignal()
    user_changed = pyqtSignal(str)
    control_toggled = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setFixedWidth(160)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        
        self._setup_ui()
        
        # State
        self.control_enabled = False
    
    def _setup_ui(self):
        """Setup the control panel UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # User Section
        user_frame = QFrame()
        user_frame.setStyleSheet(f"background-color: {COLORS['surface']}; border-radius: 8px;")
        user_layout = QVBoxLayout(user_frame)
        user_layout.setContentsMargins(10, 10, 10, 10)
        
        user_label = QLabel("👤 User")
        user_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        
        self.user_combo = QComboBox()
        self.user_combo.addItem("No User")
        self.user_combo.setMinimumHeight(35)
        self.user_combo.currentTextChanged.connect(self._on_user_changed)
        
        user_layout.addWidget(user_label)
        user_layout.addWidget(self.user_combo)
        
        layout.addWidget(user_frame)
        
        # Status Section
        status_frame = QFrame()
        status_frame.setStyleSheet(f"background-color: {COLORS['surface']}; border-radius: 8px;")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(8, 8, 8, 8)
        status_layout.setSpacing(5)
        
        status_title = QLabel("Status")
        status_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        status_layout.addWidget(status_title)
        
        self.control_status = StatusIndicator("Control")
        self.arduino_status = StatusIndicator("Arduino")
        self.fps_status = StatusIndicator("FPS")
        
        status_layout.addWidget(self.control_status)
        status_layout.addWidget(self.arduino_status)
        status_layout.addWidget(self.fps_status)
        
        layout.addWidget(status_frame)
        
        # Pose display
        pose_frame = QFrame()
        pose_frame.setStyleSheet(f"background-color: {COLORS['surface']}; border-radius: 8px;")
        pose_layout = QVBoxLayout(pose_frame)
        pose_layout.setContentsMargins(10, 8, 10, 8)
        
        self.pitch_label = QLabel("Pitch: --°")
        self.yaw_label = QLabel("Yaw: --°")
        self.brow_label = QLabel("Brow: --")
        self.pitch_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        self.yaw_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        self.brow_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        
        pose_layout.addWidget(self.pitch_label)
        pose_layout.addWidget(self.yaw_label)
        pose_layout.addWidget(self.brow_label)
        
        layout.addWidget(pose_frame)
        
        # Spacer
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        
        # Buttons
        self.calibrate_btn = QPushButton("🎯 Calibrate")
        self.calibrate_btn.setMinimumHeight(55)
        self.calibrate_btn.setStyleSheet(get_button_style('success'))
        self.calibrate_btn.clicked.connect(self.calibrate_clicked.emit)
        
        self.toggle_btn = QPushButton("▶ Enable")
        self.toggle_btn.setMinimumHeight(55)
        self.toggle_btn.clicked.connect(self._toggle_control)
        
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.setMinimumHeight(45)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        
        self.exit_btn = QPushButton("✕ Exit")
        self.exit_btn.setMinimumHeight(45)
        self.exit_btn.setStyleSheet(get_button_style('danger'))
        self.exit_btn.clicked.connect(self.exit_clicked.emit)
        
        layout.addWidget(self.calibrate_btn)
        layout.addWidget(self.toggle_btn)
        layout.addWidget(self.settings_btn)
        layout.addWidget(self.exit_btn)
    
    def _on_user_changed(self, username: str):
        """Handle user selection change"""
        self.user_changed.emit(username)
    
    def _toggle_control(self):
        """Toggle wheelchair control on/off"""
        self.control_enabled = not self.control_enabled
        self.update_control_status(self.control_enabled)
        self.control_toggled.emit(self.control_enabled)
    
    def update_control_status(self, enabled: bool):
        """
        Update control status display
        
        Args:
            enabled: Whether control is enabled
        """
        self.control_enabled = enabled
        self.control_status.set_status(enabled, "ON" if enabled else "OFF")
        
        if enabled:
            self.toggle_btn.setText("⏹ Disable")
            self.toggle_btn.setStyleSheet(get_button_style('danger'))
        else:
            self.toggle_btn.setText("▶ Enable")
            self.toggle_btn.setStyleSheet("")
    
    def update_arduino_status(self, connected: bool):
        """
        Update Arduino connection status
        
        Args:
            connected: Whether Arduino is connected
        """
        self.arduino_status.set_status(connected, "OK" if connected else "N/A")
    
    def update_fps(self, fps: float):
        """
        Update FPS display
        
        Args:
            fps: Current FPS
        """
        good_fps = fps >= 15
        self.fps_status.set_status(good_fps, f"{fps:.0f}")
    
    def update_pose(self, pitch: float, yaw: float, brow_ratio: float = 0.0):
        """
        Update pitch/yaw/brow display
        
        Args:
            pitch: Pitch angle in degrees
            yaw: Yaw angle in degrees
            brow_ratio: Current brow ratio (threshold ~350)
        """
        self.pitch_label.setText(f"Pitch: {pitch:+.0f}°")
        self.yaw_label.setText(f"Yaw: {yaw:+.0f}°")
        
        # Color code brow ratio (green when above threshold)
        brow_text = f"Brow: {brow_ratio:.0f}"
        if brow_ratio > 350:  # Above typical threshold
            self.brow_label.setStyleSheet(f"color: {COLORS['success']}; font-size: 12px; font-weight: bold;")
            brow_text += " 🔼"
        else:
            self.brow_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        self.brow_label.setText(brow_text)
    
    def set_users(self, users: list):
        """
        Update user dropdown list
        
        Args:
            users: List of username strings
        """
        current = self.user_combo.currentText()
        self.user_combo.clear()
        self.user_combo.addItem("No User")
        self.user_combo.addItems(users)
        
        # Restore selection if still valid
        index = self.user_combo.findText(current)
        if index >= 0:
            self.user_combo.setCurrentIndex(index)
    
    def set_current_user(self, username: str):
        """
        Set the currently selected user
        
        Args:
            username: Username to select
        """
        index = self.user_combo.findText(username)
        if index >= 0:
            self.user_combo.setCurrentIndex(index)
