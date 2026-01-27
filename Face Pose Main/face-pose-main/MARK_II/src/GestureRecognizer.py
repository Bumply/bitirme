"""
Professional Gesture Recognition Module
Detects facial gestures (eyebrow raise, blink) with validation and config-driven settings
"""

import numpy as np
from enum import Enum
import time
from typing import List, Tuple, Optional
import os
import sys

# Import landmark_indexes from same directory
try:
    import landmark_indexes
except ImportError:
    # Fallback for different import contexts
    from . import landmark_indexes


class Gesture(Enum):
    """Detected gesture types"""
    NONE = 0
    BROW_RAISE = 1
    BLINK = 2


class GestureRecognizerError(Exception):
    """Raised when gesture recognition fails"""
    pass


class GestureRecognizer:
    """
    Professional gesture detector
    
    Features:
    - Eyebrow raise detection
    - Blink detection (future)
    - Config-driven thresholds
    - Calibration support
    - Compensation for head movement
    - Weighted averaging for stability
    """
    
    def __init__(self, config: dict, logger):
        """
        Initialize gesture recognizer
        
        Args:
            config: Configuration dictionary
            logger: Logger instance
        """
        self.logger = logger
        self.config = config
        
        # Get configuration
        gesture_config = config.get('gesture', {})
        eyebrow_config = gesture_config.get('eyebrow_raise', {})
        
        self.eyebrow_enabled = eyebrow_config.get('enabled', True)
        self.hold_duration = eyebrow_config.get('hold_duration_seconds', 2.0)
        self.calibration_duration = eyebrow_config.get('calibration_duration', 7)
        self.threshold_percentage = eyebrow_config.get('threshold_percentage', 70)
        
        blink_config = gesture_config.get('blink', {})
        self.blink_enabled = blink_config.get('enabled', False)
        self.blink_threshold = blink_config.get('threshold', 0.3)
        
        # State variables
        # Default threshold set to a reasonable value (works without calibration)
        # Higher = more eyebrow raise needed, Lower = more sensitive
        self.brow_raise_threshold = 400  # Reasonable default (higher to prevent false positives)
        self.normalized_ratio = 0
        self.ratio_list = []
        self.weight_list = []
        self.avg_ratio = 0
        
        self.true_pitch = 0
        self.true_yaw = 0
        
        self.brow_raised = False
        self.current_gesture = Gesture.NONE
        
        # Calibration state
        self.brow_threshold_calibrated = False
        self.brow_calibration_entry_time = -1
        self.calibration_instruction = "Raise your eyebrows"
        self.eyebrow_raised_ratio = 0
        self.eyebrow_lowered_ratio = 0
        
        # Performance tracking
        self.process_count = 0
        self.gesture_detections = {
            Gesture.BROW_RAISE: 0,
            Gesture.BLINK: 0
        }
        
        self.logger.info(f"Gesture Recognizer initialized (eyebrow: {self.eyebrow_enabled}, blink: {self.blink_enabled})")
    
    def process(self, face: List, pitch: float, yaw: float, pitch_offset: float, yaw_offset: float) -> Gesture:
        """
        Process facial landmarks to detect gestures
        
        Args:
            face: List of facial landmarks [[x, y], ...]
            pitch: Current pitch angle
            yaw: Current yaw angle
            pitch_offset: Pitch calibration offset
            yaw_offset: Yaw calibration offset
            
        Returns:
            Detected gesture
        """
        if not self._validate_inputs(face, pitch, yaw):
            return Gesture.NONE
        
        # Calculate true angles (without offsets)
        self.true_pitch = pitch - pitch_offset
        self.true_yaw = yaw - yaw_offset
        
        # Reset gesture
        self.current_gesture = Gesture.NONE
        
        # Check for eyebrow raise
        if self.eyebrow_enabled:
            self._check_eyebrow_raise(face)
            if self.brow_raised:
                self.current_gesture = Gesture.BROW_RAISE
                self.gesture_detections[Gesture.BROW_RAISE] += 1
        
        # Check for blink (future implementation)
        if self.blink_enabled:
            self._check_blink(face)
        
        self.process_count += 1
        
        # Log statistics occasionally
        if self.process_count % 300 == 0:
            self.logger.debug(f"Gesture stats: {self.gesture_detections}")
        
        return self.current_gesture
    
    def _validate_inputs(self, face: List, pitch: float, yaw: float) -> bool:
        """
        Validate input parameters
        
        Args:
            face: Facial landmarks
            pitch: Pitch angle
            yaw: Yaw angle
            
        Returns:
            True if valid, False otherwise
        """
        if not face or len(face) == 0:
            return False
        
        if not isinstance(pitch, (int, float)) or not isinstance(yaw, (int, float)):
            self.logger.warning(f"Invalid angle types: pitch={type(pitch)}, yaw={type(yaw)}")
            return False
        
        # Check for reasonable angle ranges
        if abs(pitch) > 90 or abs(yaw) > 90:
            self.logger.debug(f"Angles out of reasonable range: pitch={pitch}, yaw={yaw}")
            return False
        
        return True
    
    def _check_eyebrow_raise(self, face: List):
        """
        Detect eyebrow raise gesture with crash protection
        
        Args:
            face: Facial landmarks
        """
        try:
            # Calculate head height reference
            head_height = self._find_distance(
                face[landmark_indexes.MOUTH_UPPER],
                face[landmark_indexes.MID_FACE_UP]
            )
            
            # ===== CRASH FIX: Guard against invalid distances =====
            if head_height < 5.0:  # Face too close or invalid
                self.logger.debug("Face too close: head_height too small")
                return
            # ===== END CRASH FIX =====
            
            # Get eyebrow to head distance (choose side based on yaw)
            if self.true_yaw < 0:
                brow_to_head_distance = self._find_distance(
                    face[landmark_indexes.LEFT_BROW_UP],
                    face[landmark_indexes.LEFT_FACE_UP]
                )
            else:
                brow_to_head_distance = self._find_distance(
                    face[landmark_indexes.RIGHT_BROW_UP],
                    face[landmark_indexes.RIGHT_FACE_UP]
                )
            
            # ===== CRASH FIX: Guard against division by zero =====
            if brow_to_head_distance < 1.0:  # Too close or invalid
                self.logger.debug("Face too close: brow distance too small")
                return
            # ===== END CRASH FIX =====
            
            dist_ratio = head_height / brow_to_head_distance * 100
            
            # ===== CRASH FIX: Guard against extreme ratios =====
            if dist_ratio < 0 or dist_ratio > 1000:
                self.logger.debug(f"Ignoring extreme dist_ratio: {dist_ratio}")
                return
            # ===== END CRASH FIX =====
            
            # ===== HEAD MOVEMENT GUARD =====
            # Don't trigger during significant head movement
            # Check if head pose has changed significantly
            pitch_delta = abs(self.true_pitch - getattr(self, '_last_pitch', self.true_pitch))
            yaw_delta = abs(self.true_yaw - getattr(self, '_last_yaw', self.true_yaw))
            self._last_pitch = self.true_pitch
            self._last_yaw = self.true_yaw
            
            # If head is moving too fast, don't detect (prevents false positives)
            if pitch_delta > 3.0 or yaw_delta > 4.0:
                self.brow_raised = False
                return
            
            # Don't detect when head is significantly tilted or turned
            if abs(self.true_pitch) > 25 or abs(self.true_yaw) > 30:
                self.brow_raised = False
                return
            # ===== END HEAD MOVEMENT GUARD =====
            
            # Compensate for pitch (head tilt up/down) - STRONGER compensation
            if self.true_pitch > 0:  # Looking up
                corrected_ratio = dist_ratio - (self.true_pitch * 3.0)  # Was 1.8
            else:  # Looking down
                corrected_ratio = dist_ratio - (self.true_pitch * 2.5)  # Was 1.2
            
            # Compensate for yaw (head turn left/right) - STRONGER compensation
            yaw_compensation = abs(self.true_yaw) * 3.5  # Was 2.6
            if abs(self.true_yaw) > 10:  # Start compensating earlier (was 18)
                corrected_ratio = corrected_ratio - yaw_compensation
            
            # ===== CRASH FIX: Validate corrected ratio =====
            if np.isnan(corrected_ratio) or np.isinf(corrected_ratio):
                self.logger.debug("Invalid corrected_ratio (NaN/Inf)")
                return
            # ===== END CRASH FIX =====
            
            # Add to history for smoothing
            self.ratio_list.append(corrected_ratio)
            
            # Use weighted average for stability
            if len(self.ratio_list) >= 10:
                self.avg_ratio = np.average(self.ratio_list)
                
                # ===== CRASH FIX: Safe weight calculation =====
                if self.avg_ratio != 0:
                    deviation = abs(self.avg_ratio - corrected_ratio) / abs(self.avg_ratio)
                    
                    # Guard against division by zero and overflow
                    if deviation >= 0.95:  # Would cause overflow or division by near-zero
                        weight = 1.0  # Default weight
                    else:
                        weight = 1.0 / (1.0 - deviation)
                    
                    # Cap weight to prevent extreme values
                    weight = min(max(weight, 0.1), 10.0)
                    self.weight_list.append(weight)
                else:
                    self.weight_list.append(1.0)  # Default weight
                # ===== END CRASH FIX =====
                
                if len(self.weight_list) >= 10:
                    # Validate weights before averaging
                    valid_weights = [w for w in self.weight_list if not (np.isnan(w) or np.isinf(w))]
                    if len(valid_weights) == len(self.ratio_list):
                        self.normalized_ratio = np.average(self.ratio_list, weights=valid_weights)
                    else:
                        self.normalized_ratio = np.average(self.ratio_list)
                    self.weight_list.pop(0)
                else:
                    self.normalized_ratio = np.average(self.ratio_list)
                
                self.ratio_list.pop(0)
            else:
                self.normalized_ratio = corrected_ratio
            
            # ===== CRASH FIX: Final validation =====
            if np.isnan(self.normalized_ratio) or np.isinf(self.normalized_ratio):
                self.normalized_ratio = 0
                self.logger.debug("Reset normalized_ratio due to invalid value")
                return
            # ===== END CRASH FIX =====
            
            # Check against threshold
            if self.normalized_ratio > self.brow_raise_threshold:
                self.brow_raised = True
            else:
                self.brow_raised = False
                
        except (IndexError, KeyError) as e:
            self.logger.debug(f"Landmark index error in eyebrow detection: {e}")
        except ZeroDivisionError:
            self.logger.debug("Division by zero in eyebrow detection")
        except Exception as e:
            self.logger.warning(f"Error in eyebrow detection: {e}")
    
    def _check_blink(self, face: List):
        """
        Detect blink gesture (future implementation)
        
        Args:
            face: Facial landmarks
        """
        # TODO: Implement blink detection
        pass
    
    def _find_distance(self, point1: List, point2: List) -> float:
        """
        Calculate Euclidean distance between two points
        
        Args:
            point1: [x, y]
            point2: [x, y]
            
        Returns:
            Distance
        """
        try:
            x1, y1 = point1[0], point1[1]
            x2, y2 = point2[0], point2[1]
            return np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        except (IndexError, TypeError) as e:
            self.logger.debug(f"Error calculating distance: {e}")
            return 0.0
    
    def calibrate(self) -> Tuple[str, float]:
        """
        Calibrate eyebrow raise threshold
        
        Returns:
            Tuple of (instruction, new_threshold)
        """
        new_threshold = 0
        
        if self.brow_calibration_entry_time == -1:
            # Start calibration
            self.brow_calibration_entry_time = time.time()
            self.eyebrow_raised_ratio = 0
            self.eyebrow_lowered_ratio = 0
            self.calibration_instruction = "Raise your eyebrows"
            self.logger.info("Eyebrow calibration started")
        
        elapsed_time = time.time() - self.brow_calibration_entry_time
        
        # Phase 1: Raise eyebrows
        if elapsed_time >= 3 and elapsed_time < 6:
            if self.eyebrow_raised_ratio == 0:
                self.eyebrow_raised_ratio = self.normalized_ratio
                self.logger.debug(f"Raised ratio captured: {self.eyebrow_raised_ratio}")
            self.calibration_instruction = "Lower your eyebrows"
        
        # Phase 2: Lower eyebrows and calculate threshold
        if elapsed_time >= 6 and elapsed_time < 7:
            if not self.brow_threshold_calibrated:
                if self.eyebrow_lowered_ratio == 0:
                    self.eyebrow_lowered_ratio = self.normalized_ratio
                    self.logger.debug(f"Lowered ratio captured: {self.eyebrow_lowered_ratio}")
                
                # Validation: raised should be higher than lowered
                if self.eyebrow_lowered_ratio > self.eyebrow_raised_ratio:
                    self.logger.warning("Invalid calibration: lowered > raised, retrying...")
                    self.eyebrow_raised_ratio = 0
                    self.eyebrow_lowered_ratio = 0
                    self.calibration_instruction = "Raise your eyebrows"
                    self.brow_calibration_entry_time = time.time()
                    return self.calibration_instruction, new_threshold
                
                # Validation: difference should be significant
                if self.eyebrow_lowered_ratio < self.eyebrow_raised_ratio + 20 and \
                   self.eyebrow_lowered_ratio > self.eyebrow_raised_ratio - 20:
                    self.logger.warning("Insufficient difference between raised/lowered, retrying...")
                    self.eyebrow_raised_ratio = 0
                    self.eyebrow_lowered_ratio = 0
                    self.calibration_instruction = "Raise your eyebrows"
                    self.brow_calibration_entry_time = time.time()
                    return self.calibration_instruction, new_threshold
                
                # Calculate threshold (70% between lowered and raised)
                new_threshold = self.eyebrow_lowered_ratio + \
                    ((self.eyebrow_raised_ratio - self.eyebrow_lowered_ratio) * self.threshold_percentage / 100.0)
                
                self.logger.info(f"Calibration complete - Raised: {self.eyebrow_raised_ratio:.1f}, "
                               f"Lowered: {self.eyebrow_lowered_ratio:.1f}, "
                               f"Threshold: {new_threshold:.1f}")
                
                self.brow_threshold_calibrated = True
                self.brow_calibration_entry_time = -1
        
        return self.calibration_instruction, new_threshold
    
    def set_brow_raise_threshold(self, threshold: float):
        """
        Set eyebrow raise threshold
        
        Args:
            threshold: Threshold value
        """
        if threshold < 0:
            self.logger.warning(f"Invalid threshold {threshold}, using absolute value")
            threshold = abs(threshold)
        
        self.brow_raise_threshold = threshold
        self.brow_threshold_calibrated = True
        self.logger.info(f"Eyebrow threshold set to: {threshold:.1f}")
    
    def reset_calibration(self):
        """Reset calibration state"""
        self.brow_threshold_calibrated = False
        self.brow_calibration_entry_time = -1
        self.eyebrow_raised_ratio = 0
        self.eyebrow_lowered_ratio = 0
        self.logger.info("Gesture calibration reset")
    
    def get_gesture(self) -> Gesture:
        """Get the currently detected gesture"""
        return self.current_gesture
    
    def is_calibrated(self) -> bool:
        """Check if gesture recognition is calibrated"""
        return self.brow_threshold_calibrated
    
    def get_stats(self) -> dict:
        """Get processing statistics"""
        return {
            'process_count': self.process_count,
            'calibrated': self.brow_threshold_calibrated,
            'current_gesture': self.current_gesture.name,
            'detections': dict([(g.name, count) for g, count in self.gesture_detections.items()]),
            'normalized_ratio': self.normalized_ratio,
            'threshold': self.brow_raise_threshold
        }
