"""
Main Application Controller for Face-Controlled Wheelchair System
Professional multiprocessing implementation with proper error handling
"""

import multiprocessing as mp
import signal
import sys
import time
import cv2
import numpy as np
from typing import Optional

from Capture import Capture, CaptureSource
from FaceMesh import FaceMesh
from GestureRecognizer import GestureRecognizer, Gesture
from FaceRecognizer import FaceRecognizer
from CommManager import CommManager
from ConfigManager import Config
from Logger import get_logger


# Global shutdown flag
shutdown_event = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_event
    logger = get_logger(__name__)
    logger.info(f"Received signal {signum}, initiating shutdown...")
    
    if shutdown_event is not None:
        shutdown_event.set()


def face_recognition_worker(
    fr_input_queue: mp.Queue,
    fr_output_queue: mp.Queue,
    shutdown: mp.Event,
    config_dict: dict
):
    """
    Face recognition worker process
    
    Args:
        fr_input_queue: Queue for receiving frames
        fr_output_queue: Queue for sending recognition results
        shutdown: Event to signal shutdown
        config_dict: Configuration dictionary
    """
    logger = get_logger('FaceRecognitionWorker')
    logger.info("Face Recognition Worker started")
    
    try:
        # Initialize face recognizer
        recognizer = FaceRecognizer(config_dict, logger)
        
        # Load trained users
        if not recognizer.train():
            logger.error("Failed to train face recognizer")
            return
        
        frame_count = 0
        
        while not shutdown.is_set():
            try:
                # Get frame from queue with timeout
                if not fr_input_queue.empty():
                    frame = fr_input_queue.get(timeout=0.1)
                    
                    if frame is None:
                        continue
                    
                    frame_count += 1
                    
                    # Process frame
                    user = recognizer.process(frame)
                    
                    # Send result
                    if not fr_output_queue.full():
                        fr_output_queue.put(user)
                    
                    # Log periodically
                    if frame_count % 100 == 0:
                        stats = recognizer.get_stats()
                        logger.debug(f"Processed {frame_count} frames, recognized users: {stats['recognized_count']}")
                
                else:
                    time.sleep(0.001)  # Small sleep to prevent busy waiting
                    
            except Exception as e:
                logger.error(f"Error in face recognition loop: {e}", exc_info=True)
                time.sleep(0.1)
        
        logger.info("Face Recognition Worker shutting down...")
        
    except Exception as e:
        logger.error(f"Fatal error in Face Recognition Worker: {e}", exc_info=True)
    finally:
        logger.info("Face Recognition Worker terminated")


def face_mesh_worker(
    fm_input_queue: mp.Queue,
    fm_output_queue: mp.Queue,
    shutdown: mp.Event,
    config_dict: dict
):
    """
    Face mesh and gesture recognition worker process
    
    Args:
        fm_input_queue: Queue for receiving frames
        fm_output_queue: Queue for sending results (yaw, pitch, gesture)
        shutdown: Event to signal shutdown
        config_dict: Configuration dictionary
    """
    logger = get_logger('FaceMeshWorker')
    logger.info("Face Mesh Worker started")
    
    try:
        # Initialize modules
        face_mesh = FaceMesh(config_dict, logger)
        gesture_recognizer = GestureRecognizer(config_dict, logger)
        
        # Get calibration settings
        calibration_time = config_dict.get('face_mesh', {}).get('calibration_time', 3)
        
        # Calibration
        logger.info(f"Starting calibration ({calibration_time}s)...")
        calibration_start = time.time()
        calibration_frames = 0
        
        while not shutdown.is_set():
            try:
                # Get frame from queue with timeout
                if not fm_input_queue.empty():
                    frame = fm_input_queue.get(timeout=0.1)
                    
                    if frame is None:
                        continue
                    
                    # Process frame through face mesh
                    landmarks = face_mesh.process(frame)
                    
                    if landmarks is not None:
                        # Calibration phase
                        elapsed = time.time() - calibration_start
                        
                        if elapsed < calibration_time:
                            face_mesh.calibrate(landmarks)
                            gesture_recognizer.calibrate(landmarks)
                            calibration_frames += 1
                            
                            if calibration_frames % 30 == 0:
                                logger.info(f"Calibrating... {int(calibration_time - elapsed)}s remaining")
                        
                        # Normal operation
                        else:
                            # Get head pose
                            yaw, pitch = face_mesh.get_true_angles(landmarks)
                            
                            # Detect gestures
                            gesture = gesture_recognizer.process(landmarks, yaw, pitch)
                            
                            # Send results
                            if not fm_output_queue.full():
                                fm_output_queue.put((yaw, pitch, gesture))
                
                else:
                    time.sleep(0.001)  # Small sleep to prevent busy waiting
                    
            except Exception as e:
                logger.error(f"Error in face mesh loop: {e}", exc_info=True)
                time.sleep(0.1)
        
        logger.info("Face Mesh Worker shutting down...")
        
    except Exception as e:
        logger.error(f"Fatal error in Face Mesh Worker: {e}", exc_info=True)
    finally:
        logger.info("Face Mesh Worker terminated")


def communication_worker(
    cm_input_queue: mp.Queue,
    shutdown: mp.Event,
    config_dict: dict
):
    """
    Arduino communication worker process
    
    Args:
        cm_input_queue: Queue for receiving commands (speed, position)
        shutdown: Event to signal shutdown
        config_dict: Configuration dictionary
    """
    logger = get_logger('CommunicationWorker')
    logger.info("Communication Worker started")
    
    try:
        # Initialize communication manager
        comm_manager = CommManager(config_dict, logger)
        
        # Connect to Arduino
        if not comm_manager.start():
            logger.error("Failed to connect to Arduino")
            return
        
        # Send home command
        comm_manager.home()
        time.sleep(1)
        
        command_count = 0
        
        while not shutdown.is_set():
            try:
                # Get command from queue with timeout
                if not cm_input_queue.empty():
                    speed, position = cm_input_queue.get(timeout=0.1)
                    
                    # Send command to Arduino
                    comm_manager.event_loop(speed, position)
                    command_count += 1
                    
                    # Log statistics periodically
                    if command_count % 1000 == 0:
                        stats = comm_manager.get_stats()
                        logger.debug(f"Commands sent: {stats['commands_sent']}, Connected: {stats['is_connected']}")
                
                else:
                    # Send heartbeat to keep connection alive
                    comm_manager.event_loop(0, 0)
                    time.sleep(0.01)
                    
            except Exception as e:
                logger.error(f"Error in communication loop: {e}", exc_info=True)
                time.sleep(0.1)
        
        logger.info("Communication Worker shutting down...")
        
        # Send stop command and cleanup
        comm_manager.stop()
        comm_manager.home()
        comm_manager.cleanup()
        
    except Exception as e:
        logger.error(f"Fatal error in Communication Worker: {e}", exc_info=True)
    finally:
        logger.info("Communication Worker terminated")


class WheelchairController:
    """
    Main wheelchair controller application
    
    Coordinates face recognition, face mesh tracking, gesture recognition,
    and Arduino communication through multiprocessing workers
    """
    
    def __init__(self):
        """Initialize wheelchair controller"""
        # Load configuration
        self.config = Config()
        self.config.load()  # Load the config file
        self.logger = get_logger(__name__)
        
        self.logger.info("=" * 80)
        self.logger.info("Face-Controlled Wheelchair System MARK II")
        self.logger.info("=" * 80)
        
        # Get configuration sections
        self.control_config = self.config.get_section('control')
        self.safety_config = self.config.get_section('safety')
        self.camera_config = self.config.get_section('camera')
        
        # Initialize camera
        self.logger.info("Initializing camera...")
        self.capture = Capture(self.config.data, self.logger)
        
        # Multiprocessing components
        self.shutdown_event = mp.Event()
        
        # Queues
        self.fr_input_queue = mp.Queue(maxsize=2)
        self.fr_output_queue = mp.Queue(maxsize=2)
        self.fm_input_queue = mp.Queue(maxsize=2)
        self.fm_output_queue = mp.Queue(maxsize=2)
        self.cm_input_queue = mp.Queue(maxsize=5)
        
        # Workers
        self.workers = []
        
        # State variables
        self.current_user = None
        self.wheelchair_enabled = False
        self.last_yaw = 0
        self.last_pitch = 0
        self.last_gesture = None
        self.face_lost_time = None
        
        # Statistics
        self.frame_count = 0
        self.start_time = time.time()
        
        # Setup signal handlers
        global shutdown_event
        shutdown_event = self.shutdown_event
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def start_workers(self):
        """Start all worker processes"""
        self.logger.info("Starting worker processes...")
        
        try:
            # Face recognition worker
            fr_worker = mp.Process(
                target=face_recognition_worker,
                args=(
                    self.fr_input_queue,
                    self.fr_output_queue,
                    self.shutdown_event,
                    self.config.data
                ),
                name="FaceRecognitionWorker"
            )
            fr_worker.start()
            self.workers.append(fr_worker)
            self.logger.info("Face Recognition Worker started")
            
            # Face mesh worker
            fm_worker = mp.Process(
                target=face_mesh_worker,
                args=(
                    self.fm_input_queue,
                    self.fm_output_queue,
                    self.shutdown_event,
                    self.config.data
                ),
                name="FaceMeshWorker"
            )
            fm_worker.start()
            self.workers.append(fm_worker)
            self.logger.info("Face Mesh Worker started")
            
            # Communication worker
            cm_worker = mp.Process(
                target=communication_worker,
                args=(
                    self.cm_input_queue,
                    self.shutdown_event,
                    self.config.data
                ),
                name="CommunicationWorker"
            )
            cm_worker.start()
            self.workers.append(cm_worker)
            self.logger.info("Communication Worker started")
            
            self.logger.info(f"All {len(self.workers)} workers started successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to start workers: {e}", exc_info=True)
            self.shutdown()
            raise
    
    def run(self):
        """Main control loop"""
        self.logger.info("Starting main control loop...")
        
        try:
            # Start workers
            self.start_workers()
            
            # Give workers time to initialize
            time.sleep(2)
            
            # Main loop
            while not self.shutdown_event.is_set():
                # Capture frame
                frame = self.capture.read()
                
                if frame is None:
                    self.logger.warning("Failed to capture frame")
                    time.sleep(0.1)
                    continue
                
                self.frame_count += 1
                
                # Send frame to face recognition worker (periodically)
                if self.frame_count % 30 == 0:  # Every 30 frames (~1 second at 30 fps)
                    if not self.fr_input_queue.full():
                        self.fr_input_queue.put(frame.copy())
                
                # Send frame to face mesh worker
                if not self.fm_input_queue.full():
                    self.fm_input_queue.put(frame.copy())
                
                # Get face recognition result
                if not self.fr_output_queue.empty():
                    user = self.fr_output_queue.get()
                    if user != self.current_user:
                        self.current_user = user
                        if user:
                            self.logger.info(f"User recognized: {user}")
                        else:
                            self.logger.info("No user recognized")
                
                # Get face mesh and gesture results
                if not self.fm_output_queue.empty():
                    yaw, pitch, gesture = self.fm_output_queue.get()
                    
                    self.last_yaw = yaw
                    self.last_pitch = pitch
                    
                    # Check for face lost
                    if yaw is None or pitch is None:
                        if self.face_lost_time is None:
                            self.face_lost_time = time.time()
                            self.logger.warning("Face lost")
                        
                        # Face lost timeout
                        face_lost_timeout = self.safety_config.get('face_lost_timeout', 2.0)
                        if time.time() - self.face_lost_time > face_lost_timeout:
                            if self.wheelchair_enabled:
                                self.logger.warning("Face lost timeout, disabling wheelchair")
                                self.wheelchair_enabled = False
                    else:
                        self.face_lost_time = None
                    
                    # Handle gesture
                    if gesture != self.last_gesture:
                        self.last_gesture = gesture
                        
                        if gesture == Gesture.BROW_RAISE:
                            self.wheelchair_enabled = not self.wheelchair_enabled
                            state = "ENABLED" if self.wheelchair_enabled else "DISABLED"
                            self.logger.info(f"Wheelchair {state}")
                
                # Calculate speed and position
                speed, position = self._calculate_control(self.last_yaw, self.last_pitch)
                
                # Apply safety limits
                if not self.wheelchair_enabled:
                    speed = 0
                    position = 0
                
                # Send command to Arduino
                if not self.cm_input_queue.full():
                    self.cm_input_queue.put((speed, position))
                
                # Display frame (optional, for debugging)
                if self.config.get('ui.show_frame', False):
                    self._draw_ui(frame)
                    cv2.imshow('Wheelchair Control', frame)
                    
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        self.logger.info("Quit key pressed")
                        break
                
                # Log statistics periodically
                if self.frame_count % 300 == 0:
                    elapsed = time.time() - self.start_time
                    fps = self.frame_count / elapsed
                    self.logger.info(f"FPS: {fps:.1f}, Frames: {self.frame_count}, User: {self.current_user}, Enabled: {self.wheelchair_enabled}")
                
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def _calculate_control(self, yaw: Optional[float], pitch: Optional[float]) -> tuple:
        """
        Calculate speed and position from head pose
        
        Args:
            yaw: Head yaw angle (left-right)
            pitch: Head pitch angle (up-down)
            
        Returns:
            Tuple of (speed, position)
        """
        if yaw is None or pitch is None:
            return 0, 0
        
        # Get control settings
        min_control_pitch = self.control_config.get('min_control_pitch', 5)
        max_control_pitch = self.control_config.get('max_control_pitch', 15)
        min_control_yaw = self.control_config.get('min_control_yaw', 5)
        max_control_yaw = self.control_config.get('max_control_yaw', 25)
        max_speed_percent = self.control_config.get('max_speed_percent', 20)
        
        # Calculate speed from pitch (looking down = forward)
        if pitch > min_control_pitch:
            speed_ratio = min((pitch - min_control_pitch) / (max_control_pitch - min_control_pitch), 1.0)
            speed = int(speed_ratio * max_speed_percent)
        else:
            speed = 0
        
        # Calculate position from yaw (looking left = turn left)
        if abs(yaw) > min_control_yaw:
            position_ratio = min(abs(yaw - min_control_yaw) / (max_control_yaw - min_control_yaw), 1.0)
            position = int(position_ratio * 100) * (1 if yaw > 0 else -1)
        else:
            position = 0
        
        return speed, position
    
    def _draw_ui(self, frame: np.ndarray):
        """
        Draw UI elements on frame
        
        Args:
            frame: Frame to draw on
        """
        # Status text
        status = "ENABLED" if self.wheelchair_enabled else "DISABLED"
        color = (0, 255, 0) if self.wheelchair_enabled else (0, 0, 255)
        cv2.putText(frame, f"Status: {status}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
        
        # User
        user_text = f"User: {self.current_user if self.current_user else 'Unknown'}"
        cv2.putText(frame, user_text, (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # Head pose
        pose_text = f"Yaw: {self.last_yaw:.1f}, Pitch: {self.last_pitch:.1f}"
        cv2.putText(frame, pose_text, (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    def shutdown(self):
        """Shutdown all components gracefully"""
        self.logger.info("Initiating shutdown...")
        
        # Set shutdown event
        self.shutdown_event.set()
        
        # Stop all workers
        self.logger.info("Stopping workers...")
        for worker in self.workers:
            worker.join(timeout=5)
            if worker.is_alive():
                self.logger.warning(f"Worker {worker.name} did not stop, terminating...")
                worker.terminate()
                worker.join(timeout=2)
        
        # Cleanup camera
        self.logger.info("Releasing camera...")
        self.capture.release()
        
        # Close windows
        cv2.destroyAllWindows()
        
        # Log final statistics
        elapsed = time.time() - self.start_time
        fps = self.frame_count / elapsed if elapsed > 0 else 0
        self.logger.info(f"Session statistics: {self.frame_count} frames in {elapsed:.1f}s ({fps:.1f} FPS)")
        
        self.logger.info("Shutdown complete")


def main():
    """Main entry point"""
    # Create and run controller
    controller = WheelchairController()
    controller.run()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
