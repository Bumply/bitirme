"""
Professional Face Recognition Module
Handles user identification through facial recognition with enhanced error handling and security
"""

import cv2
import face_recognition
import os
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple
import time


class FaceRecognitionError(Exception):
    """Exception raised when face recognition operations fail"""
    pass


class User:
    """
    Represents a registered user with facial encoding
    
    Attributes:
        name: Username
        image_path: Path to user's face image
        face_encoding: 128-dimensional face encoding vector
    """
    
    def __init__(self, name: str, image_path: str):
        """
        Initialize user with face encoding
        
        Args:
            name: Username
            image_path: Path to user's reference image
            
        Raises:
            FaceRecognitionError: If face encoding fails
        """
        self.name = name
        self.image_path = image_path
        self.face_encoding = self._encode_face()
    
    def _encode_face(self) -> np.ndarray:
        """
        Generate face encoding from user image
        
        Returns:
            Face encoding as numpy array
            
        Raises:
            FaceRecognitionError: If encoding fails
        """
        try:
            user_image = face_recognition.load_image_file(self.image_path)
            encodings = face_recognition.face_encodings(user_image, model="small")
            
            if len(encodings) == 0:
                raise FaceRecognitionError(f"No face found in image: {self.image_path}")
            
            return encodings[0]
            
        except Exception as e:
            raise FaceRecognitionError(f"Failed to encode face for {self.name}: {e}")


class FaceRecognizer:
    """
    Professional face recognition system
    
    Features:
    - User registration and training
    - Face matching with confidence threshold
    - Low-resolution mode for performance
    - Proper error handling and recovery
    - Training validation
    - Statistics tracking
    """
    
    def __init__(self, config: dict, logger):
        """
        Initialize face recognition system
        
        Args:
            config: Configuration dictionary
            logger: Logger instance
        """
        self.logger = logger
        self.config = config
        
        # Get configuration
        fr_config = config.get('face_recognition', {})
        self.enabled = fr_config.get('enabled', True)
        self.low_res = fr_config.get('low_resolution_mode', True)
        self.confidence = fr_config.get('recognition_confidence', 0.5)
        self.model = fr_config.get('model', 'hog')
        
        # Get user images path
        self.user_images_path = Path(fr_config.get('user_images_path', 'user_images'))
        
        # State variables
        self.users = []
        self.known_face_encodings = []
        self.active_user = None
        self.active_user_index = -1
        
        # Processing state
        self.image_face_locations = []
        self.unknown_face_locations = []
        self.image_face_encodings = []
        self.matches = []
        
        # Statistics
        self.process_count = 0
        self.recognition_count = 0
        self.failure_count = 0
        self.last_process_time = 0
        
        self.logger.info(f"Face Recognizer initialized (model: {self.model}, confidence: {self.confidence})")
        
        if not self.enabled:
            self.logger.warning("Face recognition is disabled in configuration")
    
    def train(self) -> bool:
        """
        Train the face recognizer with all registered users
        
        Returns:
            True if training successful, False otherwise
        """
        if not self.enabled:
            self.logger.info("Face recognition disabled, skipping training")
            return False
        
        self.logger.info("Starting face recognition training...")
        start_time = time.time()
        
        # Clear existing data
        self.users.clear()
        self.known_face_encodings.clear()
        
        # Check if user images directory exists
        if not self.user_images_path.exists():
            self.logger.warning(f"User images directory not found: {self.user_images_path}")
            self.user_images_path.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Created user images directory: {self.user_images_path}")
            return True
        
        # Get user directories
        user_dirs = self._get_user_directories()
        
        if len(user_dirs) == 0:
            self.logger.warning("No user directories found for training")
            return True
        
        # Train on each user
        success_count = 0
        for user_dir in user_dirs:
            user_name = user_dir.name
            
            try:
                # Find images in user directory
                images = list(user_dir.glob('*.jpg')) + list(user_dir.glob('*.png'))
                
                if len(images) == 0:
                    self.logger.warning(f"No images found for user: {user_name}")
                    continue
                
                # Encode each image
                for image_path in images:
                    try:
                        self._encode_user(user_name, str(image_path))
                        success_count += 1
                    except FaceRecognitionError as e:
                        self.logger.error(f"Failed to encode {image_path}: {e}")
                        continue
                
            except Exception as e:
                self.logger.error(f"Error processing user {user_name}: {e}", exc_info=True)
                continue
        
        training_time = time.time() - start_time
        self.logger.info(f"Training complete: {success_count} images from {len(user_dirs)} users in {training_time:.2f}s")
        
        return success_count > 0
    
    def _get_user_directories(self) -> List[Path]:
        """
        Get list of user directories
        
        Returns:
            List of directory paths
        """
        try:
            return [d for d in self.user_images_path.iterdir() if d.is_dir()]
        except Exception as e:
            self.logger.error(f"Error reading user directories: {e}")
            return []
    
    def _encode_user(self, name: str, image_path: str):
        """
        Encode a user's face and add to known faces
        
        Args:
            name: Username
            image_path: Path to user's image
            
        Raises:
            FaceRecognitionError: If encoding fails
        """
        try:
            user = User(name, image_path)
            self.users.append(user)
            self.known_face_encodings.append(user.face_encoding)
            self.logger.debug(f"Encoded user: {name} from {image_path}")
            
        except FaceRecognitionError as e:
            self.logger.error(f"Failed to encode user {name}: {e}")
            raise
    
    def process(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Process image to recognize faces
        
        Args:
            image: Input image (BGR format)
            
        Returns:
            Processed image with face boxes, or None if processing failed
        """
        if not self.enabled:
            return image
        
        if not self._validate_image(image):
            return None
        
        start_time = time.time()
        
        try:
            # Reset state
            self._reset_state()
            
            # Optionally resize for performance
            if self.low_res:
                image = cv2.resize(image, (0, 0), fx=0.25, fy=0.25)
            
            # Convert BGR to RGB
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            # Find faces
            self.image_face_locations = face_recognition.face_locations(
                rgb_image, 
                model=self.model
            )
            
            if len(self.image_face_locations) == 0:
                self.logger.debug("No faces detected in image")
                return image
            
            # Encode faces
            self.image_face_encodings = face_recognition.face_encodings(
                rgb_image,
                known_face_locations=self.image_face_locations,
                model="small"
            )
            
            # Match faces
            for encoding in self.image_face_encodings:
                matches = face_recognition.compare_faces(
                    self.known_face_encodings,
                    encoding,
                    self.confidence
                )
                self.matches.extend(matches)
            
            # Identify user
            for i, match in enumerate(self.matches):
                if match:
                    user_index = i % len(self.users)
                    self.active_user = self.users[user_index]
                    self.active_user_index = user_index
                    self.recognition_count += 1
                    self.logger.info(f"User recognized: {self.active_user.name}")
                    break
            
            # Update statistics
            self.process_count += 1
            process_time = (time.time() - start_time) * 1000
            
            if self.process_count % 30 == 0:
                self.logger.debug(f"Face recognition processing: {process_time:.1f}ms")
            
            return image
            
        except Exception as e:
            self.failure_count += 1
            self.logger.error(f"Face recognition processing error: {e}", exc_info=True)
            return None
    
    def _validate_image(self, image: np.ndarray) -> bool:
        """
        Validate input image
        
        Args:
            image: Image to validate
            
        Returns:
            True if valid, False otherwise
        """
        if image is None:
            self.logger.debug("Image is None")
            return False
        
        if not isinstance(image, np.ndarray):
            self.logger.warning(f"Image is not ndarray, got {type(image)}")
            return False
        
        if image.size == 0:
            self.logger.debug("Image is empty")
            return False
        
        if len(image.shape) != 3:
            self.logger.warning(f"Image has invalid shape: {image.shape}")
            return False
        
        return True
    
    def _reset_state(self):
        """Reset recognition state variables"""
        self.active_user = None
        self.active_user_index = -1
        self.image_face_locations = []
        self.unknown_face_locations = []
        self.image_face_encodings = []
        self.matches = []
    
    def new_user(self, name: str, image: np.ndarray) -> bool:
        """
        Register a new user with their face image
        
        Args:
            name: Username
            image: Face image
            
        Returns:
            True if successful, False otherwise
        """
        if not name or name.strip() == "":
            self.logger.error("Cannot create user with empty name")
            return False
        
        if not self._validate_image(image):
            self.logger.error("Invalid image provided for new user")
            return False
        
        try:
            # Create user directory if it doesn't exist
            user_dir = self.user_images_path / name
            
            if user_dir.exists():
                # User exists, add another image
                image_count = len(list(user_dir.glob('*.jpg')))
                image_filename = f"{image_count + 1}.jpg"
                self.logger.info(f"Adding image for existing user: {name}")
            else:
                # New user
                user_dir.mkdir(parents=True, exist_ok=True)
                image_filename = "1.jpg"
                self.logger.info(f"Creating new user: {name}")
            
            # Save image
            image_path = user_dir / image_filename
            success = cv2.imwrite(str(image_path), image)
            
            if not success:
                self.logger.error(f"Failed to save image: {image_path}")
                return False
            
            self.logger.info(f"User image saved: {image_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating new user {name}: {e}", exc_info=True)
            return False
    
    def get_user(self) -> Optional[User]:
        """
        Get the currently recognized user
        
        Returns:
            User object if recognized, None otherwise
        """
        return self.active_user
    
    def get_user_count(self) -> int:
        """
        Get number of registered users
        
        Returns:
            Number of users
        """
        return len(self.users)
    
    def get_stats(self) -> dict:
        """
        Get recognition statistics
        
        Returns:
            Dictionary of statistics
        """
        return {
            'process_count': self.process_count,
            'recognition_count': self.recognition_count,
            'failure_count': self.failure_count,
            'user_count': len(self.users),
            'active_user': self.active_user.name if self.active_user else None,
            'enabled': self.enabled
        }
    
    def cleanup(self):
        """Release resources and cleanup"""
        self.users.clear()
        self.known_face_encodings.clear()
        self._reset_state()
        self.logger.info("Face Recognizer cleaned up")
