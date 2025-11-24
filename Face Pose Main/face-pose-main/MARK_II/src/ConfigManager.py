"""
Configuration Manager for Wheelchair Control System
Loads and validates configuration from YAML file
"""

import yaml
import os
from pathlib import Path
from typing import Any, Dict, Optional
import copy


class ConfigurationError(Exception):
    """Raised when configuration is invalid"""
    pass


class Config:
    """
    Configuration manager with validation and defaults
    
    Features:
    - Load from YAML file
    - Validate required fields
    - Provide defaults
    - Type checking
    - Environment variable overrides
    - Hot reload capability
    """
    
    _instance = None
    _config = None
    _config_path = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def load(self, config_path: str = None):
        """
        Load configuration from YAML file
        
        Args:
            config_path: Path to config.yaml file
        """
        if config_path is None:
            # Try to find config.yaml in standard locations
            possible_paths = [
                Path("config/config.yaml"),
                Path("MARK_II/config/config.yaml"),
                Path("../config/config.yaml"),
            ]
            
            for path in possible_paths:
                if path.exists():
                    config_path = str(path)
                    break
            
            if config_path is None:
                raise ConfigurationError("config.yaml not found in standard locations")
        
        self._config_path = config_path
        
        try:
            with open(config_path, 'r') as f:
                self._config = yaml.safe_load(f)
        except FileNotFoundError:
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in configuration file: {e}")
        
        # Apply environment variable overrides
        self._apply_env_overrides()
        
        # Validate configuration
        self._validate()
        
        print(f"[Config] Configuration loaded from: {config_path}")
        print(f"[Config] Application: {self.get('application.name')} v{self.get('application.version')}")
        print(f"[Config] Mode: {self.get('application.mode')}")
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides to configuration"""
        # Example: WHEELCHAIR_LOGGING_LEVEL=DEBUG
        prefix = "WHEELCHAIR_"
        
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower().replace('_', '.')
                self.set(config_key, value)
    
    def _validate(self):
        """Validate required configuration fields"""
        required_sections = [
            'application',
            'logging',
            'camera',
            'control',
            'safety'
        ]
        
        for section in required_sections:
            if section not in self._config:
                raise ConfigurationError(f"Required configuration section missing: {section}")
        
        # Validate specific values
        if self.get('control.speed.max_percent') > 100:
            raise ConfigurationError("control.speed.max_percent cannot exceed 100")
        
        if self.get('control.speed.max_percent') < 0:
            raise ConfigurationError("control.speed.max_percent cannot be negative")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation
        
        Args:
            key: Configuration key (e.g., 'logging.level')
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        if self._config is None:
            raise ConfigurationError("Configuration not loaded. Call load() first.")
        
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any):
        """
        Set configuration value using dot notation
        
        Args:
            key: Configuration key (e.g., 'logging.level')
            value: Value to set
        """
        if self._config is None:
            raise ConfigurationError("Configuration not loaded. Call load() first.")
        
        keys = key.split('.')
        config = self._config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def get_section(self, section: str) -> Dict:
        """
        Get entire configuration section
        
        Args:
            section: Section name (e.g., 'logging')
            
        Returns:
            Dictionary of configuration for that section
        """
        return self.get(section, {})
    
    def reload(self):
        """Reload configuration from file"""
        if self._config_path:
            self.load(self._config_path)
    
    def save(self, path: Optional[str] = None):
        """
        Save current configuration to file
        
        Args:
            path: Path to save to (uses original path if None)
        """
        if path is None:
            path = self._config_path
        
        if path is None:
            raise ConfigurationError("No path specified and no original path available")
        
        with open(path, 'w') as f:
            yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)
    
    def get_all(self) -> Dict:
        """Get entire configuration as dictionary"""
        return copy.deepcopy(self._config)
    
    @property
    def data(self) -> Dict:
        """Get entire configuration (alias for get_all)"""
        return self.get_all()
    
    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access"""
        return self.get(key)
    
    def __setitem__(self, key: str, value: Any):
        """Allow dictionary-style setting"""
        self.set(key, value)
    
    # Convenience methods for common configs
    @property
    def app_name(self) -> str:
        return self.get('application.name', 'Wheelchair Control')
    
    @property
    def app_version(self) -> str:
        return self.get('application.version', '2.0.0')
    
    @property
    def is_production(self) -> bool:
        return self.get('application.mode') == 'production'
    
    @property
    def is_debug(self) -> bool:
        return self.get('debug.enabled', False)
    
    @property
    def log_level(self) -> str:
        return self.get('logging.level', 'INFO')
    
    @property
    def camera_device(self) -> int:
        return self.get('camera.device_id', 0)
    
    @property
    def max_speed_percent(self) -> int:
        return self.get('control.speed.max_percent', 20)
    
    @property
    def arduino_port(self) -> Optional[str]:
        return self.get('arduino.port')
    
    @property
    def arduino_baud(self) -> int:
        return self.get('arduino.baud_rate', 115200)


# Global configuration instance
_config_instance = Config()


def load_config(config_path: str = None):
    """Load the global configuration"""
    _config_instance.load(config_path)


def get_config() -> Config:
    """Get the global configuration instance"""
    return _config_instance


def get(key: str, default: Any = None) -> Any:
    """Shortcut to get configuration value"""
    return _config_instance.get(key, default)


def get_section(section: str) -> Dict:
    """Shortcut to get configuration section"""
    return _config_instance.get_section(section)
