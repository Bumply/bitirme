"""
MARK II - Face-Controlled Wheelchair System
Professional implementation with proper logging and configuration
"""

from .Logger import get_logger, setup_logging, log_exception
from .ConfigManager import Config, load_config, get_config
from .Capture import Capture, CaptureSource, CaptureError
from .FaceMesh import FaceMesh, FaceMeshError
from .GestureRecognizer import GestureRecognizer, Gesture, GestureRecognizerError
from .FaceRecognizer import FaceRecognizer, FaceRecognitionError, User
from .CommManager import CommManager, CommunicationError

__version__ = "2.0.0"
__author__ = "MARK II Team"

__all__ = [
    # Logger
    'get_logger',
    'setup_logging', 
    'log_exception',
    
    # Config
    'Config',
    'load_config',
    'get_config',
    
    # Capture
    'Capture',
    'CaptureSource',
    'CaptureError',
    
    # FaceMesh
    'FaceMesh',
    'FaceMeshError',
    
    # GestureRecognizer
    'GestureRecognizer',
    'Gesture',
    'GestureRecognizerError',
    
    # FaceRecognizer
    'FaceRecognizer',
    'FaceRecognitionError',
    'User',
    
    # CommManager
    'CommManager',
    'CommunicationError',
]
