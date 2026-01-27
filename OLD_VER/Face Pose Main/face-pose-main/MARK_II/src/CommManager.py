"""
Professional Arduino Communication Manager
Handles serial communication with wheelchair control Arduino with robust error handling
"""

import serial
import serial.tools.list_ports
import time
from typing import Optional, Tuple


class CommunicationError(Exception):
    """Exception raised when serial communication fails"""
    pass


class CommManager:
    """
    Professional serial communication manager for Arduino
    
    Features:
    - Automatic port detection
    - Connection validation
    - Automatic reconnection on failure
    - Timeout protection
    - Command validation
    - Statistics tracking
    - Proper error handling
    """
    
    def __init__(self, config: dict, logger):
        """
        Initialize communication manager
        
        Args:
            config: Configuration dictionary
            logger: Logger instance
        """
        self.logger = logger
        self.config = config
        
        # Get configuration
        arduino_config = config.get('arduino', {})
        self.auto_detect = arduino_config.get('auto_detect', True)
        self.port = arduino_config.get('port')
        self.baud_rate = arduino_config.get('baud_rate', 115200)
        self.timeout = arduino_config.get('timeout', 0.1)
        self.reconnect_attempts = arduino_config.get('reconnect_attempts', 3)
        self.reconnect_delay = arduino_config.get('reconnect_delay', 2)
        
        # Get command configuration
        self.watchdog_timeout = arduino_config.get('watchdog_timeout_ms', 400)
        self.heartbeat_interval = arduino_config.get('heartbeat_interval_ms', 100)
        self.stop_command = arduino_config.get('stop_command', 'S:0,P:0')
        self.home_command = arduino_config.get('home_command', 'Home')
        self.check_command = arduino_config.get('check_command', 'CHK')
        
        # State variables
        self.serial_port = None
        self.is_connected = False
        self.obstacle_detected = False
        self.last_command_time = 0
        
        # Statistics
        self.commands_sent = 0
        self.connection_failures = 0
        self.reconnection_attempts = 0
        self.last_error_time = 0
        
        self.logger.info(f"Communication Manager initialized (baud: {self.baud_rate})")
    
    def start(self) -> bool:
        """
        Start communication by finding and connecting to Arduino
        
        Returns:
            True if connected, False otherwise
        """
        self.logger.info("Starting Arduino communication...")
        
        if self.port and not self.auto_detect:
            # Use specified port
            self.logger.info(f"Using configured port: {self.port}")
            return self._connect_to_port(self.port)
        else:
            # Auto-detect Arduino
            self.logger.info("Auto-detecting Arduino port...")
            port = self._find_arduino_port()
            
            if port:
                return self._connect_to_port(port)
            else:
                self.logger.error("Failed to find Arduino port")
                return False
    
    def _find_arduino_port(self) -> Optional[str]:
        """
        Automatically find Arduino serial port
        
        Returns:
            Port name if found, None otherwise
        """
        ports = serial.tools.list_ports.comports()
        
        if len(ports) == 0:
            self.logger.warning("No serial ports found")
            return None
        
        self.logger.info(f"Scanning {len(ports)} serial ports...")
        
        for port in ports:
            self.logger.debug(f"Checking port: {port.device}")
            
            try:
                # Try to open port
                test_serial = serial.Serial(
                    port.device,
                    self.baud_rate,
                    timeout=0.2,
                    write_timeout=1
                )
                time.sleep(2)  # Allow Arduino to initialize
                
                # Send check command
                for attempt in range(2):
                    try:
                        test_serial.write((self.check_command + "\n").encode('ascii'))
                        time.sleep(0.01)
                        response = test_serial.read_until(b"\n").decode('ascii').strip()
                        
                        if response == "OK":
                            test_serial.close()
                            self.logger.info(f"Arduino found on port: {port.device}")
                            return port.device
                            
                    except Exception as e:
                        self.logger.debug(f"Check command failed on {port.device}: {e}")
                        continue
                
                test_serial.close()
                
            except serial.SerialException as e:
                self.logger.debug(f"Could not open port {port.device}: {e}")
                continue
            except Exception as e:
                self.logger.debug(f"Error checking port {port.device}: {e}")
                continue
        
        return None
    
    def _connect_to_port(self, port: str) -> bool:
        """
        Connect to specified serial port
        
        Args:
            port: Serial port name
            
        Returns:
            True if connected, False otherwise
        """
        try:
            self.logger.info(f"Connecting to port: {port}")
            
            self.serial_port = serial.Serial(
                port,
                self.baud_rate,
                timeout=self.timeout
            )
            time.sleep(2)  # Allow Arduino to initialize
            
            self.is_connected = True
            self.port = port
            self.connection_failures = 0
            
            self.logger.info(f"Successfully connected to Arduino on {port}")
            return True
            
        except serial.SerialException as e:
            self.logger.error(f"Failed to connect to {port}: {e}")
            self.connection_failures += 1
            self.is_connected = False
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error connecting to {port}: {e}", exc_info=True)
            self.connection_failures += 1
            self.is_connected = False
            return False
    
    def event_loop(self, speed: int, position: int):
        """
        Main event loop for sending commands to Arduino
        
        Args:
            speed: Speed value (0-100)
            position: Steering position (-100 to 100)
        """
        if not self.is_connected or self.serial_port is None:
            if time.time() - self.last_error_time > 5:
                self.logger.warning("Not connected to Arduino")
                self.last_error_time = time.time()
            return
        
        try:
            # Validate inputs
            speed = self._validate_speed(speed)
            position = self._validate_position(position)
            
            # Clear buffers
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            
            # Send command
            self._send_command(speed, position)
            
            # Read response (if any)
            self._read_response()
            
            # Update statistics
            self.commands_sent += 1
            self.last_command_time = time.time()
            
        except serial.SerialException as e:
            self.logger.error(f"Serial communication error: {e}")
            self.is_connected = False
            self._attempt_reconnection()
        except Exception as e:
            self.logger.error(f"Error in communication event loop: {e}", exc_info=True)
    
    def _validate_speed(self, speed: int) -> int:
        """
        Validate and clamp speed value
        
        Args:
            speed: Raw speed value
            
        Returns:
            Validated speed (0-100)
        """
        if not isinstance(speed, (int, float)):
            self.logger.warning(f"Invalid speed type: {type(speed)}, defaulting to 0")
            return 0
        
        if speed < 0:
            self.logger.debug(f"Negative speed {speed}, clamping to 0")
            return 0
        
        if speed > 100:
            self.logger.debug(f"Speed {speed} exceeds max, clamping to 100")
            return 100
        
        return int(speed)
    
    def _validate_position(self, position: int) -> int:
        """
        Validate and clamp position value
        
        Args:
            position: Raw position value
            
        Returns:
            Validated position (-100 to 100)
        """
        if not isinstance(position, (int, float)):
            self.logger.warning(f"Invalid position type: {type(position)}, defaulting to 0")
            return 0
        
        if position < -100:
            self.logger.debug(f"Position {position} below min, clamping to -100")
            return -100
        
        if position > 100:
            self.logger.debug(f"Position {position} above max, clamping to 100")
            return 100
        
        return int(position)
    
    def _send_command(self, speed: int, position: int):
        """
        Send speed and position command to Arduino
        
        Args:
            speed: Speed value (0-100)
            position: Steering position (-100 to 100)
        """
        command = f"S:{speed},P:{position}\n"
        self.serial_port.write(command.encode('ascii'))
        
        if self.commands_sent % 100 == 0:
            self.logger.debug(f"Sent command: S:{speed}, P:{position}")
    
    def _read_response(self):
        """Read and process response from Arduino"""
        try:
            if self.serial_port.in_waiting > 0:
                response = self.serial_port.read_until(b'\n').decode('ascii').strip()
                
                if response == "OD":
                    if not self.obstacle_detected:
                        self.logger.warning("Obstacle detected by Arduino")
                        self.obstacle_detected = True
                        
                elif response == "OC":
                    if self.obstacle_detected:
                        self.logger.info("Obstacle cleared")
                        self.obstacle_detected = False
                        
        except Exception as e:
            self.logger.debug(f"Error reading response: {e}")
    
    def home(self):
        """Send home command to reset steering to center"""
        if not self.is_connected or self.serial_port is None:
            self.logger.warning("Cannot send home command: not connected")
            return
        
        try:
            self.logger.info("Sending home command to Arduino")
            self.serial_port.write((self.home_command + "\n").encode('ascii'))
            self.commands_sent += 1
            
        except serial.SerialException as e:
            self.logger.error(f"Failed to send home command: {e}")
            self.is_connected = False
        except Exception as e:
            self.logger.error(f"Error sending home command: {e}", exc_info=True)
    
    def stop(self):
        """Send stop command (speed=0, position=0)"""
        if not self.is_connected or self.serial_port is None:
            return
        
        try:
            self.logger.info("Sending stop command")
            
            for _ in range(3):  # Send multiple times for safety
                self.event_loop(0, 0)
                time.sleep(0.01)
                
        except Exception as e:
            self.logger.error(f"Error sending stop command: {e}")
    
    def _attempt_reconnection(self):
        """Attempt to reconnect to Arduino"""
        if self.reconnection_attempts >= self.reconnect_attempts:
            if time.time() - self.last_error_time > 10:
                self.logger.error(f"Maximum reconnection attempts ({self.reconnect_attempts}) reached")
                self.last_error_time = time.time()
            return
        
        self.logger.info(f"Attempting reconnection ({self.reconnection_attempts + 1}/{self.reconnect_attempts})...")
        self.reconnection_attempts += 1
        
        # Close existing connection
        self.disconnect()
        
        # Wait before reconnecting
        time.sleep(self.reconnect_delay)
        
        # Try to reconnect
        if self.start():
            self.logger.info("Reconnection successful")
            self.reconnection_attempts = 0
        else:
            self.logger.error("Reconnection failed")
    
    def disconnect(self):
        """Close serial connection"""
        if self.serial_port is not None:
            try:
                self.serial_port.close()
                self.logger.info("Serial port closed")
            except Exception as e:
                self.logger.error(f"Error closing serial port: {e}")
        
        self.serial_port = None
        self.is_connected = False
    
    def is_available(self) -> bool:
        """
        Check if Arduino connection is available
        
        Returns:
            True if connected and ready, False otherwise
        """
        return self.is_connected and self.serial_port is not None
    
    def get_stats(self) -> dict:
        """
        Get communication statistics
        
        Returns:
            Dictionary of statistics
        """
        return {
            'is_connected': self.is_connected,
            'port': self.port if self.port else 'None',
            'commands_sent': self.commands_sent,
            'connection_failures': self.connection_failures,
            'reconnection_attempts': self.reconnection_attempts,
            'obstacle_detected': self.obstacle_detected
        }
    
    def cleanup(self):
        """Cleanup resources and disconnect"""
        self.logger.info("Cleaning up Communication Manager...")
        self.stop()
        time.sleep(0.1)
        self.disconnect()
        self.logger.info("Communication Manager cleaned up")
