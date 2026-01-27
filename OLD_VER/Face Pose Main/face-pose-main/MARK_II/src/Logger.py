"""
Professional Logging System for Wheelchair Control
Provides structured logging with rotation, levels, and multiple outputs
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import traceback


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'       # Reset
    }
    
    def format(self, record):
        # Add color to level name
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)


class WheelchairLogger:
    """
    Centralized logging system for the wheelchair control application
    
    Features:
    - Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - Console and file output
    - Automatic log rotation
    - Separate logs per module
    - Performance metrics logging
    - Error tracking with stack traces
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WheelchairLogger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self.loggers = {}
            self.log_dir = None
            self.config = None
    
    def setup(self, config: dict):
        """
        Initialize the logging system with configuration
        
        Args:
            config: Dictionary containing logging configuration
        """
        self.config = config.get('logging', {})
        
        # Create log directory
        self.log_dir = Path(config.get('paths', {}).get('logs', 'logs'))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Set root logger level
        log_level = getattr(logging, self.config.get('level', 'INFO'))
        logging.basicConfig(level=log_level)
        
        print(f"[Logger] Logging system initialized at level: {self.config.get('level', 'INFO')}")
        print(f"[Logger] Log directory: {self.log_dir}")
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        Get or create a logger for a specific module
        
        Args:
            name: Name of the module (e.g., 'FaceMesh', 'CommManager')
            
        Returns:
            Configured logger instance
        """
        if name in self.loggers:
            return self.loggers[name]
        
        # Initialize config if not set
        if self.config is None:
            self.config = {}
        
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, self.config.get('level', 'INFO')))
        logger.propagate = False
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # Console handler with colors
        if self.config.get('console_output', True):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.DEBUG)
            console_formatter = ColoredFormatter(
                self.config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
                datefmt=self.config.get('date_format', '%Y-%m-%d %H:%M:%S')
            )
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)
        
        # File handler with rotation
        if self.config.get('file_output', True) and self.log_dir:
            # Main log file for this module
            log_file = self.log_dir / f"{name}.log"
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=self.config.get('max_log_size_mb', 10) * 1024 * 1024,
                backupCount=self.config.get('backup_count', 5)
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                self.config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
                datefmt=self.config.get('date_format', '%Y-%m-%d %H:%M:%S')
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            
            # Separate error log
            error_log_file = self.log_dir / f"{name}_errors.log"
            error_handler = logging.handlers.RotatingFileHandler(
                error_log_file,
                maxBytes=self.config.get('max_log_size_mb', 10) * 1024 * 1024,
                backupCount=self.config.get('backup_count', 5)
            )
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(file_formatter)
            logger.addHandler(error_handler)
        
        self.loggers[name] = logger
        return logger
    
    def log_exception(self, logger: logging.Logger, message: str, exc_info=True):
        """
        Log an exception with full stack trace
        
        Args:
            logger: Logger instance
            message: Error message
            exc_info: Include exception info
        """
        logger.error(message, exc_info=exc_info)
        
        # Also save to separate crash log
        if self.log_dir:
            crash_log = self.log_dir / "crashes.log"
            with open(crash_log, 'a') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Message: {message}\n")
                f.write(f"Traceback:\n")
                traceback.print_exc(file=f)
                f.write(f"{'='*80}\n")
    
    def log_performance(self, module: str, metric: str, value: float, unit: str = ""):
        """
        Log performance metrics
        
        Args:
            module: Module name
            metric: Metric name (e.g., 'fps', 'latency')
            value: Metric value
            unit: Unit of measurement
        """
        if self.log_dir:
            perf_log = self.log_dir / "performance.log"
            with open(perf_log, 'a') as f:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp},{module},{metric},{value},{unit}\n")
    
    def log_telemetry(self, event_type: str, data: dict):
        """
        Log telemetry data for analytics
        
        Args:
            event_type: Type of event
            data: Event data as dictionary
        """
        if self.log_dir:
            telemetry_dir = self.log_dir / "telemetry"
            telemetry_dir.mkdir(exist_ok=True)
            
            telemetry_file = telemetry_dir / f"{event_type}_{datetime.now().strftime('%Y%m%d')}.log"
            with open(telemetry_file, 'a') as f:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp}: {data}\n")
    
    def create_session_log(self) -> str:
        """
        Create a new session log file and return its path
        
        Returns:
            Path to the session log file
        """
        if not self.log_dir:
            return ""
        
        session_dir = self.log_dir / "sessions"
        session_dir.mkdir(exist_ok=True)
        
        session_file = session_dir / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        with open(session_file, 'w') as f:
            f.write(f"Session started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*80}\n\n")
        
        return str(session_file)


# Global logger instance
_logger_instance = WheelchairLogger()


def setup_logging(config: dict):
    """Setup the global logging system"""
    _logger_instance.setup(config)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module"""
    return _logger_instance.get_logger(name)


def log_exception(logger: logging.Logger, message: str, exc_info=True):
    """Log an exception with full details"""
    _logger_instance.log_exception(logger, message, exc_info)


def log_performance(module: str, metric: str, value: float, unit: str = ""):
    """Log a performance metric"""
    _logger_instance.log_performance(module, metric, value, unit)


def log_telemetry(event_type: str, data: dict):
    """Log telemetry data"""
    _logger_instance.log_telemetry(event_type, data)


def create_session_log() -> str:
    """Create a new session log"""
    return _logger_instance.create_session_log()


# Convenience functions for common log patterns
def log_startup(logger: logging.Logger, module: str, version: str):
    """Log module startup"""
    logger.info(f"{'='*60}")
    logger.info(f"{module} v{version} starting...")
    logger.info(f"{'='*60}")


def log_shutdown(logger: logging.Logger, module: str):
    """Log module shutdown"""
    logger.info(f"{'='*60}")
    logger.info(f"{module} shutting down...")
    logger.info(f"{'='*60}")


def log_config(logger: logging.Logger, config: dict):
    """Log configuration details"""
    logger.info("Configuration loaded:")
    for key, value in config.items():
        if isinstance(value, dict):
            logger.info(f"  {key}:")
            for sub_key, sub_value in value.items():
                logger.info(f"    {sub_key}: {sub_value}")
        else:
            logger.info(f"  {key}: {value}")
