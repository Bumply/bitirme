"""
Arduino Communication Thread
Threaded serial communication for non-blocking wheelchair control
"""

from PyQt5.QtCore import QThread, pyqtSignal
import time
from typing import Optional
import sys
import os

# Add parent directory to path for imports
_current_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(_current_dir)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from CommManager import CommManager


class ArduinoThread(QThread):
    """
    Background thread for Arduino communication
    
    Sends speed/position commands at regular intervals
    """
    
    # Signals
    connection_changed = pyqtSignal(bool)  # Connected/disconnected
    obstacle_detected = pyqtSignal(bool)   # Obstacle status
    command_sent = pyqtSignal(int, int)    # speed, position
    error_occurred = pyqtSignal(str)       # Error message
    
    def __init__(self, config: dict, logger=None, parent=None):
        """
        Initialize Arduino thread
        
        Args:
            config: Configuration dictionary
            logger: Logger instance
            parent: Parent QObject
        """
        super().__init__(parent)
        
        self.config = config
        self.logger = logger
        
        # Create CommManager
        self.comm_manager = CommManager(config, logger)
        
        # Command state
        self.target_speed = 0
        self.target_position = 0
        self.current_speed = 0
        self.current_position = 0
        
        # Control state
        self.running = False
        self.control_enabled = False
        
        # Timing
        arduino_config = config.get('arduino', {})
        self.command_interval = arduino_config.get('command_interval_ms', 50) / 1000.0
        
        # Safety
        self.last_command_time = 0
        self.watchdog_timeout = arduino_config.get('watchdog_timeout_ms', 400) / 1000.0
    
    def run(self):
        """Main thread loop - sends commands to Arduino"""
        self.running = True
        
        # Connect to Arduino
        if self.comm_manager.start():
            self.connection_changed.emit(True)
        else:
            self.error_occurred.emit("Failed to connect to Arduino")
            self.connection_changed.emit(False)
        
        while self.running:
            try:
                if self.comm_manager.is_available():
                    if self.control_enabled:
                        # Smooth transition to target values
                        self._smooth_transition()
                        
                        # Send command
                        self.comm_manager.event_loop(
                            self.current_speed, 
                            self.current_position
                        )
                        
                        self.command_sent.emit(self.current_speed, self.current_position)
                        self.last_command_time = time.time()
                    else:
                        # Control disabled, send stop
                        self.comm_manager.event_loop(0, 0)
                        self.current_speed = 0
                        self.current_position = 0
                    
                    # Check for obstacle
                    if self.comm_manager.obstacle_detected:
                        self.obstacle_detected.emit(True)
                    
                else:
                    # Not connected, try to reconnect periodically
                    if time.time() - self.last_command_time > 5.0:
                        self._attempt_reconnect()
                
                # Command rate limiting
                time.sleep(self.command_interval)
                
            except Exception as e:
                self.error_occurred.emit(f"Arduino thread error: {e}")
                time.sleep(0.5)
        
        # Cleanup
        self._shutdown()
    
    def _smooth_transition(self):
        """Smoothly transition current values to target values"""
        # Speed smoothing (ramp up/down)
        speed_diff = self.target_speed - self.current_speed
        max_speed_change = 10  # Max change per cycle
        
        if abs(speed_diff) > max_speed_change:
            self.current_speed += max_speed_change if speed_diff > 0 else -max_speed_change
        else:
            self.current_speed = self.target_speed
        
        # Position smoothing (steering)
        pos_diff = self.target_position - self.current_position
        max_pos_change = 15  # Max change per cycle
        
        if abs(pos_diff) > max_pos_change:
            self.current_position += max_pos_change if pos_diff > 0 else -max_pos_change
        else:
            self.current_position = self.target_position
    
    def _attempt_reconnect(self):
        """Attempt to reconnect to Arduino"""
        if self.logger:
            self.logger.info("Attempting Arduino reconnection...")
        
        if self.comm_manager.start():
            self.connection_changed.emit(True)
            if self.logger:
                self.logger.info("Arduino reconnected")
        else:
            self.connection_changed.emit(False)
        
        self.last_command_time = time.time()
    
    def _shutdown(self):
        """Shutdown communication safely"""
        if self.comm_manager:
            # Send stop commands
            for _ in range(3):
                try:
                    self.comm_manager.event_loop(0, 0)
                    time.sleep(0.05)
                except:
                    pass
            
            self.comm_manager.cleanup()
    
    def set_command(self, speed: int, position: int):
        """
        Set target speed and position
        
        Args:
            speed: Target speed (0-100)
            position: Target steering position (-100 to 100)
        """
        self.target_speed = max(0, min(100, speed))
        self.target_position = max(-100, min(100, position))
    
    def enable_control(self, enabled: bool):
        """
        Enable or disable wheelchair control
        
        Args:
            enabled: Whether control is enabled
        """
        self.control_enabled = enabled
        
        if not enabled:
            # Immediately stop
            self.target_speed = 0
            self.target_position = 0
            self.current_speed = 0
            self.current_position = 0
    
    def stop(self):
        """Stop the Arduino thread"""
        self.control_enabled = False
        self.running = False
        self.wait(2000)  # Wait up to 2 seconds
    
    def emergency_stop(self):
        """Emergency stop - immediate halt"""
        self.control_enabled = False
        self.target_speed = 0
        self.target_position = 0
        self.current_speed = 0
        self.current_position = 0
        
        if self.comm_manager and self.comm_manager.is_available():
            self.comm_manager.stop()
    
    def home(self):
        """Send home command to center steering"""
        if self.comm_manager and self.comm_manager.is_available():
            self.comm_manager.home()
    
    def is_connected(self) -> bool:
        """Check if Arduino is connected"""
        return self.comm_manager.is_available() if self.comm_manager else False
    
    def has_obstacle(self) -> bool:
        """Check if obstacle is detected"""
        return self.comm_manager.obstacle_detected if self.comm_manager else False
    
    def get_stats(self) -> dict:
        """Get communication statistics"""
        if self.comm_manager:
            stats = self.comm_manager.get_stats()
            stats['control_enabled'] = self.control_enabled
            stats['current_speed'] = self.current_speed
            stats['current_position'] = self.current_position
            return stats
        return {}
