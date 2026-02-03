"""
MARK II Wheelchair Control System - GUI Application
Main entry point for the PyQt5-based control interface
"""

import sys
import os

# Ensure src directory is in path
src_dir = os.path.dirname(os.path.abspath(__file__))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Also add parent directory for config access
parent_dir = os.path.dirname(src_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from PyQt5.QtWidgets import QApplication, QSplashScreen, QMessageBox
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QFont
import time
import cv2
from typing import Optional

# Import GUI modules
from gui.main_window import MainWindow
from gui.styles import apply_dark_theme

# Import core modules
from core.camera_thread import CameraThread
from core.face_processor import FaceProcessor
from core.arduino_thread import ArduinoThread
from core.calibration_data import CalibrationData

# Import existing modules (from src directory)
try:
    from ConfigManager import Config, load_config, get_config
    from Logger import WheelchairLogger, get_logger, setup_logging
    from GestureRecognizer import Gesture
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running from the src directory")
    sys.exit(1)


class WheelchairApp:
    """
    Main application controller
    
    Orchestrates:
    - Camera capture (thread)
    - Face processing
    - Arduino communication (thread)
    - GUI updates
    """
    
    def __init__(self):
        # Initialize Qt application
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("MARK II Wheelchair Control")
        
        # Apply dark theme
        apply_dark_theme(self.app)
        
        # Initialize components
        self.config = None
        self.logger = None
        self.window: Optional[MainWindow] = None
        self.camera_thread: Optional[CameraThread] = None
        self.arduino_thread: Optional[ArduinoThread] = None
        self.face_processor: Optional[FaceProcessor] = None
        self.calibration_data: Optional[CalibrationData] = None
        
        # State
        self.control_enabled = False
        self.current_user = None
        self.last_gesture_time = 0
        self.gesture_cooldown = 2.0  # Seconds between gesture toggles
        
        # Processing timer (runs in main thread)
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(self._process_frame)
        
        # Current frame buffer
        self.current_frame = None
        self.is_processing = False  # Flag to prevent processing overlap
        self.display_frame = None  # Separate buffer for display only
    
    def initialize(self) -> bool:
        """
        Initialize all components
        
        Returns:
            True if successful
        """
        try:
            # Load configuration
            config_path = os.path.join(src_dir, "..", "config", "config.yaml")
            load_config(config_path)
            config = get_config()
            
            # Store as dict for compatibility with existing modules
            self.config = config.get_all()
            
            # Initialize logger
            log_dir = os.path.join(src_dir, "..", "logs")
            os.makedirs(log_dir, exist_ok=True)
            
            # Setup logging with config
            logging_config = self.config.get('logging', {
                'level': 'INFO',
                'log_dir': log_dir,
                'console_enabled': True,
                'file_enabled': True
            })
            logging_config['log_dir'] = log_dir  # Ensure log_dir is set
            setup_logging(logging_config)
            self.logger = get_logger('App')
            self.logger.info("=== MARK II GUI Starting ===")
            
            # Initialize calibration data manager
            self.calibration_data = CalibrationData(logger=self.logger)
            
            # Initialize face processor
            self.face_processor = FaceProcessor(self.config, self.logger)
            
            # Initialize camera thread
            camera_config = self.config.get('camera', {})
            self.camera_thread = CameraThread(
                camera_index=camera_config.get('device_id', 0),
                width=camera_config.get('resolution', {}).get('width', 640),
                height=camera_config.get('resolution', {}).get('height', 480),
                target_fps=camera_config.get('fps', 30)
            )
            self.camera_thread.frame_ready.connect(self._on_frame_received)
            self.camera_thread.camera_error.connect(self._on_camera_error)
            
            # Initialize Arduino thread (disabled for Windows testing)
            arduino_config = self.config.get('arduino', {})
            if arduino_config.get('enabled', False):  # Default to False for testing
                self.arduino_thread = ArduinoThread(self.config, self.logger)
                self.arduino_thread.connection_changed.connect(self._on_arduino_connection)
                self.arduino_thread.obstacle_detected.connect(self._on_obstacle)
                self.arduino_thread.error_occurred.connect(self._on_arduino_error)
            else:
                self.logger.info("Arduino disabled for testing")
            
            # Initialize main window
            self.window = MainWindow()
            self.window.control_enabled_changed.connect(self._on_control_toggle)
            self.window.user_selected.connect(self._on_user_selected)
            self.window.request_calibration.connect(self._start_calibration)
            
            # Connect calibration wizard
            self.window.calibration_wizard.calibration_complete.connect(self._on_calibration_complete)
            
            # Set up users list
            users = self.calibration_data.list_users()
            self.window.set_users(users)
            
            self.logger.info("Initialization complete")
            return True
            
        except Exception as e:
            print(f"Initialization error: {e}")
            if self.logger:
                self.logger.error(f"Initialization error: {e}", exc_info=True)
            return False
    
    def run(self) -> int:
        """
        Run the application
        
        Returns:
            Exit code
        """
        if not self.initialize():
            QMessageBox.critical(
                None,
                "Initialization Error",
                "Failed to initialize the application.\nCheck logs for details."
            )
            return 1
        
        # Start camera thread
        self.camera_thread.start()
        
        # Start Arduino thread
        if self.arduino_thread:
            self.arduino_thread.start()
        
        # Start processing timer (100ms = 10 FPS max processing)
        # MediaPipe is slow on Pi, so we process at a lower rate
        self.process_timer.start(100)
        
        # Show window
        self.window.show()
        
        # Run event loop
        try:
            exit_code = self.app.exec_()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Application error: {e}", exc_info=True)
            exit_code = 1
        
        # Cleanup
        self.shutdown()
        
        return exit_code
    
    def _on_frame_received(self, frame):
        """Handle new frame from camera thread"""
        # Store frame for processing (will be consumed by _process_frame)
        if not self.is_processing:  # Only update if not currently processing
            self.current_frame = frame
        # Always update display frame for smooth preview
        self.display_frame = frame
    
    def _process_frame(self):
        """Process current frame (called by timer in main thread)"""
        # Show display frame even if not processing
        if self.display_frame is not None:
            display = cv2.flip(self.display_frame, 1)
            self.window.update_frame(display)
        
        if self.current_frame is None:
            return
        
        if self.is_processing:
            return  # Skip if already processing
        
        self.is_processing = True
        
        try:
            frame = self.current_frame
            self.current_frame = None  # Clear so we get fresh frame next time
            
            # Mirror the frame horizontally (so turning right moves wheelchair right)
            frame = cv2.flip(frame, 1)
            
            # Process face
            result = self.face_processor.process(frame)
            
            # Update GUI with processed frame
            self.window.update_face_data(
                result['face_box'],
                result['pitch'],
                result['yaw'],
                result['face_detected'],
                result['brow_ratio']
            )
            
            # Handle gestures for control toggle
            if result['brow_raised'] and time.time() - self.last_gesture_time > self.gesture_cooldown:
                if self.logger:
                    self.logger.info(f"Eyebrow raise detected! Toggling control. Ratio: {result['brow_ratio']:.1f}")
                self._toggle_control()
                self.last_gesture_time = time.time()
            
            # Update wheelchair control
            if self.control_enabled and result['face_detected']:
                speed, position = self._calculate_control(result['pitch'], result['yaw'])
                
                if self.arduino_thread:
                    self.arduino_thread.set_command(speed, position)
        
        except Exception as e:
            if self.logger:
                self.logger.error(f"Frame processing error: {e}")
        
        finally:
            self.is_processing = False
    
    def _calculate_control(self, pitch: float, yaw: float) -> tuple:
        """
        Calculate wheelchair speed and steering from head pose
        
        Args:
            pitch: Head pitch (forward/backward tilt)
            yaw: Head yaw (left/right turn)
            
        Returns:
            (speed, position) tuple
        """
        control_config = self.config.get('control', {})
        
        # Get thresholds
        pitch_deadzone = control_config.get('pitch_deadzone', 5)
        yaw_deadzone = control_config.get('yaw_deadzone', 8)
        max_speed = control_config.get('max_speed', 60)
        max_steering = control_config.get('max_steering', 80)
        
        # Calculate speed from pitch (forward tilt = forward motion)
        speed = 0
        if abs(pitch) > pitch_deadzone:
            # Positive pitch = head tilted down = forward
            if pitch > pitch_deadzone:
                speed = min(max_speed, int((pitch - pitch_deadzone) * 2))
        
        # Calculate steering from yaw
        position = 0
        if abs(yaw) > yaw_deadzone:
            # Scale yaw to steering range
            position = int((yaw / 45) * max_steering)
            position = max(-max_steering, min(max_steering, position))
        
        return (speed, position)
    
    def _toggle_control(self):
        """Toggle wheelchair control on/off"""
        self.control_enabled = not self.control_enabled
        
        self.window.update_control_status(self.control_enabled)
        
        if self.arduino_thread:
            self.arduino_thread.enable_control(self.control_enabled)
        
        if self.logger:
            status = "ENABLED" if self.control_enabled else "DISABLED"
            self.logger.info(f"Wheelchair control {status}")
    
    def _on_control_toggle(self, enabled: bool):
        """Handle control toggle from GUI"""
        self.control_enabled = enabled
        
        if self.arduino_thread:
            self.arduino_thread.enable_control(enabled)
        
        if self.logger:
            status = "ENABLED" if enabled else "DISABLED"
            self.logger.info(f"Wheelchair control {status} (from GUI)")
    
    def _on_user_selected(self, username: str):
        """Handle user selection from GUI"""
        self.current_user = username if username != "No User" else None
        
        if self.current_user:
            # Load user's calibration
            cal_data = self.calibration_data.load(username)
            if cal_data:
                self.face_processor.apply_calibration(cal_data)
                if self.logger:
                    self.logger.info(f"Loaded calibration for user: {username}")
        else:
            # Reset to defaults
            self.face_processor.reset_calibration()
    
    def _on_calibration_complete(self, data: dict):
        """Handle calibration completion"""
        # Apply calibration
        self.face_processor.apply_calibration(data)
        
        # Save for current user
        if self.current_user:
            self.calibration_data.save(self.current_user, data)
            if self.logger:
                self.logger.info(f"Saved calibration for user: {self.current_user}")
    
    def _start_calibration(self):
        """Start calibration process"""
        # Disable control during calibration
        if self.control_enabled:
            self._toggle_control()
    
    def _on_camera_error(self, error: str):
        """Handle camera error"""
        if self.logger:
            self.logger.error(f"Camera error: {error}")
    
    def _on_arduino_connection(self, connected: bool):
        """Handle Arduino connection change"""
        self.window.update_arduino_status(connected)
    
    def _on_obstacle(self, detected: bool):
        """Handle obstacle detection from Arduino"""
        if detected and self.control_enabled:
            # Emergency stop on obstacle
            if self.arduino_thread:
                self.arduino_thread.emergency_stop()
            self.control_enabled = False
            self.window.update_control_status(False)
            
            if self.logger:
                self.logger.warning("Obstacle detected - emergency stop!")
    
    def _on_arduino_error(self, error: str):
        """Handle Arduino error"""
        if self.logger:
            self.logger.error(f"Arduino error: {error}")
    
    def shutdown(self):
        """Cleanup and shutdown"""
        if self.logger:
            self.logger.info("Shutting down...")
        
        # Stop timers
        self.process_timer.stop()
        
        # Stop threads
        if self.camera_thread:
            self.camera_thread.stop()
        
        if self.arduino_thread:
            self.arduino_thread.stop()
        
        # Cleanup processors
        if self.face_processor:
            self.face_processor.cleanup()
        
        if self.logger:
            self.logger.info("=== MARK II GUI Shutdown Complete ===")


def main():
    """Application entry point"""
    app = WheelchairApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
