
import cv2
import time
import sys
import numpy as np

def test_opencv(index=0):
    print(f"Testing OpenCV Camera {index}...")
    try:
        # Try default
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            print("  Default backend failed. Trying V4L2...")
            cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        
        if not cap.isOpened():
            print("  Failed to open camera with OpenCV.")
            return False
            
        print(f"  Camera opened using backend: {cap.getBackendName()}")
        
        # Try updating resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Read frames
        start = time.time()
        frames = 0
        success_count = 0
        
        for i in range(10):
            ret, frame = cap.read()
            if ret and frame is not None:
                success_count += 1
                frames = frame.shape
            else:
                print(f"  Frame {i} read failed.")
            time.sleep(0.1)
            
        cap.release()
        
        if success_count > 5:
            print(f"  Success! captured {success_count}/10 frames. Shape: {frames}")
            return True
        else:
            print("  Unstable capture.")
            return False
            
    except Exception as e:
        print(f"  OpenCV Error: {e}")
        return False

def test_picamera2():
    print("Testing PiCamera2...")
    try:
        from picamera2 import Picamera2
        picam = Picamera2()
        config = picam.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        picam.configure(config)
        picam.start()
        
        # Warmup
        time.sleep(1)
        
        # Capture
        frame = picam.capture_array()
        picam.stop()
        picam.close()
        
        if frame is not None and frame.size > 0:
            print(f"  Success! Frame shape: {frame.shape}")
            return True
        else:
            print("  Capture returned empty frame.")
            return False
            
    except ImportError:
        print("  PiCamera2 module not found.")
        return False
    except Exception as e:
        print(f"  PiCamera2 Error: {e}")
        return False

if __name__ == "__main__":
    print("=== Diagnostic Camera Test ===")
    
    cv_result = test_opencv(0)
    print("-" * 30)
    picam_result = test_picamera2()
    
    print("=" * 30)
    print(f"OpenCV Result: {'PASS' if cv_result else 'FAIL'}")
    print(f"PiCamera2 Result: {'PASS' if picam_result else 'FAIL'}")
