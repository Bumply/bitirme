"""
Calibration Wizard
Step-by-step calibration UI with visual feedback
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QProgressBar, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from typing import Optional, Callable
import time

from .styles import COLORS, get_button_style


class CalibrationStep:
    """Represents a single calibration step"""
    
    def __init__(self, title: str, instruction: str, duration: float, 
                 action: Optional[Callable] = None):
        """
        Args:
            title: Step title
            instruction: Instruction text for user
            duration: How long this step takes in seconds
            action: Optional callback when step starts
        """
        self.title = title
        self.instruction = instruction
        self.duration = duration
        self.action = action


class CalibrationWizard(QWidget):
    """
    Step-by-step calibration wizard
    
    Steps:
    1. Face detection check
    2. Neutral head position (5 seconds)
    3. Raise eyebrows (3 seconds)
    4. Relax face (1 second)
    5. Complete/Retry
    """
    
    # Signals
    calibration_complete = pyqtSignal(dict)  # Emits calibration data
    calibration_cancelled = pyqtSignal()
    step_changed = pyqtSignal(int, str)  # step index, step name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setMinimumSize(600, 400)
        
        # Calibration data
        self.calibration_data = {
            'pitch_offset': 0.0,
            'yaw_offset': 0.0,
            'brow_threshold': 350.0,
            'raised_ratio': 0.0,
            'lowered_ratio': 0.0
        }
        
        # State
        self.current_step = 0
        self.step_start_time = 0
        self.is_calibrating = False
        self.face_detected = False
        
        # Timers
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self._update_progress)
        
        # External callbacks (to be set by parent)
        self.get_pitch_yaw: Optional[Callable] = None
        self.get_brow_ratio: Optional[Callable] = None
        
        # Define calibration steps
        self.steps = [
            CalibrationStep(
                "Face Detection",
                "Position your face in the camera view",
                0,  # No timer, waits for face
                None
            ),
            CalibrationStep(
                "Neutral Position",
                "Look straight ahead and keep still...",
                5.0,
                self._start_neutral_capture
            ),
            CalibrationStep(
                "Raise Eyebrows",
                "Raise your eyebrows and hold...",
                3.0,
                self._start_brow_capture
            ),
            CalibrationStep(
                "Relax Face",
                "Lower your eyebrows and relax...",
                2.0,
                self._start_relax_capture
            ),
            CalibrationStep(
                "Complete",
                "Calibration successful!",
                0,
                None
            )
        ]
        
        # Captured values for averaging
        self.pitch_samples = []
        self.yaw_samples = []
        self.raised_samples = []
        self.lowered_samples = []
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the calibration wizard UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        self.title_label = QLabel("🎯 Calibration Wizard")
        self.title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(f"color: {COLORS['text']};")
        layout.addWidget(self.title_label)
        
        # Step indicator
        self.step_frame = QFrame()
        self.step_frame.setStyleSheet(f"""
            background-color: {COLORS['surface']};
            border-radius: 10px;
            padding: 10px;
        """)
        step_layout = QHBoxLayout(self.step_frame)
        
        self.step_dots = []
        for i in range(5):
            dot = QLabel("●")
            dot.setFont(QFont("Arial", 16))
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet(f"color: {COLORS['disabled']};")
            self.step_dots.append(dot)
            step_layout.addWidget(dot)
        
        layout.addWidget(self.step_frame)
        
        # Content area
        self.content_frame = QFrame()
        self.content_frame.setStyleSheet(f"""
            background-color: {COLORS['surface']};
            border-radius: 15px;
        """)
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.setSpacing(20)
        
        # Step title
        self.step_title = QLabel("Step 1: Face Detection")
        self.step_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.step_title.setAlignment(Qt.AlignCenter)
        self.step_title.setStyleSheet(f"color: {COLORS['text']};")
        content_layout.addWidget(self.step_title)
        
        # Instruction
        self.instruction_label = QLabel("Position your face in the camera view")
        self.instruction_label.setFont(QFont("Segoe UI", 14))
        self.instruction_label.setAlignment(Qt.AlignCenter)
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        content_layout.addWidget(self.instruction_label)
        
        # Status icon (large emoji)
        self.status_icon = QLabel("👤")
        self.status_icon.setFont(QFont("Arial", 48))
        self.status_icon.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(self.status_icon)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v%")
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS['surface_light']};
                border: 2px solid {COLORS['border']};
                border-radius: 10px;
                height: 30px;
                text-align: center;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent']};
                border-radius: 8px;
            }}
        """)
        self.progress_bar.hide()
        content_layout.addWidget(self.progress_bar)
        
        # Timer label
        self.timer_label = QLabel("")
        self.timer_label.setFont(QFont("Segoe UI", 24, QFont.Bold))
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setStyleSheet(f"color: {COLORS['accent']};")
        content_layout.addWidget(self.timer_label)
        
        layout.addWidget(self.content_frame)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(50)
        self.cancel_btn.setStyleSheet(get_button_style('danger'))
        self.cancel_btn.clicked.connect(self._cancel)
        
        self.next_btn = QPushButton("Start")
        self.next_btn.setMinimumHeight(50)
        self.next_btn.setStyleSheet(get_button_style('success'))
        self.next_btn.clicked.connect(self._next_step)
        
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setMinimumHeight(50)
        self.retry_btn.clicked.connect(self._restart)
        self.retry_btn.hide()
        
        self.save_btn = QPushButton("Save & Close")
        self.save_btn.setMinimumHeight(50)
        self.save_btn.setStyleSheet(get_button_style('success'))
        self.save_btn.clicked.connect(self._complete)
        self.save_btn.hide()
        
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.retry_btn)
        button_layout.addWidget(self.next_btn)
        button_layout.addWidget(self.save_btn)
        
        layout.addLayout(button_layout)
    
    def start(self):
        """Start the calibration wizard"""
        self.current_step = 0
        self.is_calibrating = True
        self._reset_samples()
        self._update_ui()
    
    def set_face_detected(self, detected: bool):
        """
        Update face detection status
        
        Args:
            detected: Whether face is detected
        """
        self.face_detected = detected
        
        # Auto-advance from step 0 if face detected
        if self.current_step == 0 and detected:
            self.status_icon.setText("✓")
            self.instruction_label.setText("Face detected! Click 'Next' to continue.")
            self.next_btn.setEnabled(True)
        elif self.current_step == 0:
            self.status_icon.setText("👤")
            self.instruction_label.setText("Position your face in the camera view")
            self.next_btn.setEnabled(False)
    
    def update_values(self, pitch: float, yaw: float, brow_ratio: float):
        """
        Update current sensor values for calibration
        
        Args:
            pitch: Current pitch angle
            yaw: Current yaw angle
            brow_ratio: Current eyebrow ratio
        """
        if not self.is_calibrating:
            return
        
        if self.current_step == 1:  # Neutral capture
            self.pitch_samples.append(pitch)
            self.yaw_samples.append(yaw)
            
        elif self.current_step == 2:  # Raised eyebrows
            self.raised_samples.append(brow_ratio)
            
        elif self.current_step == 3:  # Lowered/relaxed
            self.lowered_samples.append(brow_ratio)
    
    def _reset_samples(self):
        """Reset all captured samples"""
        self.pitch_samples.clear()
        self.yaw_samples.clear()
        self.raised_samples.clear()
        self.lowered_samples.clear()
    
    def _update_ui(self):
        """Update UI for current step"""
        step = self.steps[self.current_step]
        
        # Update step dots
        for i, dot in enumerate(self.step_dots):
            if i < self.current_step:
                dot.setStyleSheet(f"color: {COLORS['success']};")
            elif i == self.current_step:
                dot.setStyleSheet(f"color: {COLORS['accent']};")
            else:
                dot.setStyleSheet(f"color: {COLORS['disabled']};")
        
        # Update content
        self.step_title.setText(f"Step {self.current_step + 1}: {step.title}")
        self.instruction_label.setText(step.instruction)
        
        # Update icon
        icons = ["👤", "🎯", "😮", "😌", "✅"]
        self.status_icon.setText(icons[self.current_step])
        
        # Show/hide progress bar
        if step.duration > 0:
            self.progress_bar.show()
            self.progress_bar.setValue(0)
            self.timer_label.setText(f"{step.duration:.0f}s")
        else:
            self.progress_bar.hide()
            self.timer_label.setText("")
        
        # Update buttons
        if self.current_step == 0:
            self.next_btn.setText("Next")
            self.next_btn.setEnabled(self.face_detected)
            self.next_btn.show()
            self.save_btn.hide()
            self.retry_btn.hide()
        elif self.current_step == len(self.steps) - 1:
            self.next_btn.hide()
            self.save_btn.show()
            self.retry_btn.show()
        else:
            self.next_btn.setText("Skip")
            self.next_btn.setEnabled(True)
            self.next_btn.show()
            self.save_btn.hide()
            self.retry_btn.hide()
        
        # Emit signal
        self.step_changed.emit(self.current_step, step.title)
    
    def _next_step(self):
        """Advance to next calibration step"""
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            step = self.steps[self.current_step]
            
            # Call step action if defined
            if step.action:
                step.action()
            
            # Start timer if step has duration
            if step.duration > 0:
                self.step_start_time = time.time()
                self.progress_timer.start(50)  # Update every 50ms
            
            self._update_ui()
    
    def _update_progress(self):
        """Update progress bar during timed steps"""
        step = self.steps[self.current_step]
        if step.duration <= 0:
            return
        
        elapsed = time.time() - self.step_start_time
        progress = min(100, int((elapsed / step.duration) * 100))
        remaining = max(0, step.duration - elapsed)
        
        self.progress_bar.setValue(progress)
        self.timer_label.setText(f"{remaining:.1f}s")
        
        # Auto-advance when complete
        if elapsed >= step.duration:
            self.progress_timer.stop()
            self._finalize_step()
            self._next_step()
    
    def _finalize_step(self):
        """Finalize data collection for current step"""
        import numpy as np
        
        if self.current_step == 1 and len(self.pitch_samples) > 0:
            # Calculate neutral offsets
            self.calibration_data['pitch_offset'] = -np.mean(self.pitch_samples)
            self.calibration_data['yaw_offset'] = -np.mean(self.yaw_samples)
            
        elif self.current_step == 2 and len(self.raised_samples) > 0:
            self.calibration_data['raised_ratio'] = np.mean(self.raised_samples)
            
        elif self.current_step == 3 and len(self.lowered_samples) > 0:
            self.calibration_data['lowered_ratio'] = np.mean(self.lowered_samples)
            
            # Calculate threshold as midpoint
            raised = self.calibration_data['raised_ratio']
            lowered = self.calibration_data['lowered_ratio']
            self.calibration_data['brow_threshold'] = (raised + lowered) / 2
    
    def _start_neutral_capture(self):
        """Called when neutral capture step starts"""
        self.pitch_samples.clear()
        self.yaw_samples.clear()
    
    def _start_brow_capture(self):
        """Called when eyebrow raise capture starts"""
        self.raised_samples.clear()
    
    def _start_relax_capture(self):
        """Called when relax capture starts"""
        self.lowered_samples.clear()
    
    def _cancel(self):
        """Cancel calibration"""
        self.progress_timer.stop()
        self.is_calibrating = False
        self.calibration_cancelled.emit()
    
    def _restart(self):
        """Restart calibration from beginning"""
        self.progress_timer.stop()
        self._reset_samples()
        self.start()
    
    def _complete(self):
        """Complete calibration and emit data"""
        self.is_calibrating = False
        self.calibration_complete.emit(self.calibration_data)
    
    def get_calibration_data(self) -> dict:
        """Get the collected calibration data"""
        return self.calibration_data.copy()
