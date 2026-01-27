"""
Calibration Data Manager
Handles saving and loading per-user calibration data
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime


class CalibrationData:
    """
    Manages per-user calibration data persistence
    
    Data structure:
    {
        'head_pose': {
            'pitch_offset': 0.0,
            'yaw_offset': 0.0
        },
        'eyebrow': {
            'threshold': 350.0,
            'raised_ratio': 400.0,
            'lowered_ratio': 300.0
        },
        'last_calibrated': '2024-01-27T10:00:00'
    }
    """
    
    DEFAULT_DATA = {
        'head_pose': {
            'pitch_offset': 0.0,
            'yaw_offset': 0.0
        },
        'eyebrow': {
            'threshold': 350.0,
            'raised_ratio': 400.0,
            'lowered_ratio': 300.0
        },
        'last_calibrated': None
    }
    
    def __init__(self, data_dir: str = None, logger=None):
        """
        Initialize calibration data manager
        
        Args:
            data_dir: Directory for storing user calibration files
            logger: Logger instance
        """
        self.logger = logger
        
        # Set data directory
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            # Default to config/users relative to src
            self.data_dir = Path(__file__).parent.parent.parent / "config" / "users"
        
        # Create directory if it doesn't exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        if self.logger:
            self.logger.info(f"CalibrationData initialized: {self.data_dir}")
    
    def save(self, username: str, data: dict) -> bool:
        """
        Save calibration data for a user
        
        Args:
            username: Username (used as filename)
            data: Calibration data dictionary
            
        Returns:
            True if saved successfully
        """
        if not username or username.lower() == "no user":
            if self.logger:
                self.logger.warning("Cannot save calibration for empty/no user")
            return False
        
        try:
            # Sanitize username for filename
            safe_name = self._sanitize_filename(username)
            file_path = self.data_dir / f"{safe_name}.yaml"
            
            # Structure the data
            save_data = {
                'head_pose': {
                    'pitch_offset': data.get('pitch_offset', 0.0),
                    'yaw_offset': data.get('yaw_offset', 0.0)
                },
                'eyebrow': {
                    'threshold': data.get('brow_threshold', 350.0),
                    'raised_ratio': data.get('raised_ratio', 400.0),
                    'lowered_ratio': data.get('lowered_ratio', 300.0)
                },
                'last_calibrated': datetime.now().isoformat()
            }
            
            # Save to YAML
            with open(file_path, 'w') as f:
                yaml.safe_dump(save_data, f, default_flow_style=False)
            
            if self.logger:
                self.logger.info(f"Saved calibration for user: {username}")
            
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to save calibration for {username}: {e}")
            return False
    
    def load(self, username: str) -> Optional[Dict]:
        """
        Load calibration data for a user
        
        Args:
            username: Username
            
        Returns:
            Calibration data dict or None if not found
        """
        if not username or username.lower() == "no user":
            return None
        
        try:
            safe_name = self._sanitize_filename(username)
            file_path = self.data_dir / f"{safe_name}.yaml"
            
            if not file_path.exists():
                if self.logger:
                    self.logger.debug(f"No calibration found for user: {username}")
                return None
            
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
            
            if self.logger:
                self.logger.info(f"Loaded calibration for user: {username}")
            
            # Flatten for easier use
            flat_data = {
                'pitch_offset': data['head_pose']['pitch_offset'],
                'yaw_offset': data['head_pose']['yaw_offset'],
                'brow_threshold': data['eyebrow']['threshold'],
                'raised_ratio': data['eyebrow']['raised_ratio'],
                'lowered_ratio': data['eyebrow']['lowered_ratio'],
                'last_calibrated': data.get('last_calibrated')
            }
            
            return flat_data
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to load calibration for {username}: {e}")
            return None
    
    def delete(self, username: str) -> bool:
        """
        Delete calibration data for a user
        
        Args:
            username: Username
            
        Returns:
            True if deleted successfully
        """
        try:
            safe_name = self._sanitize_filename(username)
            file_path = self.data_dir / f"{safe_name}.yaml"
            
            if file_path.exists():
                file_path.unlink()
                if self.logger:
                    self.logger.info(f"Deleted calibration for user: {username}")
                return True
            
            return False
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to delete calibration for {username}: {e}")
            return False
    
    def list_users(self) -> list:
        """
        List all users with saved calibration data
        
        Returns:
            List of usernames
        """
        try:
            users = []
            for file_path in self.data_dir.glob("*.yaml"):
                users.append(file_path.stem)
            return sorted(users)
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to list users: {e}")
            return []
    
    def has_calibration(self, username: str) -> bool:
        """
        Check if user has saved calibration data
        
        Args:
            username: Username
            
        Returns:
            True if calibration exists
        """
        safe_name = self._sanitize_filename(username)
        file_path = self.data_dir / f"{safe_name}.yaml"
        return file_path.exists()
    
    def get_default(self) -> dict:
        """
        Get default calibration values
        
        Returns:
            Default calibration dict
        """
        return {
            'pitch_offset': 0.0,
            'yaw_offset': 0.0,
            'brow_threshold': 350.0,
            'raised_ratio': 400.0,
            'lowered_ratio': 300.0
        }
    
    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize username for use as filename
        
        Args:
            name: Raw username
            
        Returns:
            Safe filename string
        """
        # Remove/replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        safe_name = name.strip()
        
        for char in invalid_chars:
            safe_name = safe_name.replace(char, '_')
        
        # Limit length
        return safe_name[:50]
