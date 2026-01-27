#!/bin/bash
#=============================================================================
# Automated Setup Script for Face-Controlled Wheelchair System
# Raspberry Pi OS (Legacy, 32-bit) - Buster
#=============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
}

#=============================================================================
# Check if running on Raspberry Pi
#=============================================================================
print_header "Checking System"

if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null && ! grep -q "BCM" /proc/cpuinfo 2>/dev/null; then
    print_warning "This doesn't appear to be a Raspberry Pi. Continuing anyway..."
else
    print_success "Raspberry Pi detected!"
fi

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    print_error "Please do not run this script as root. Run as regular user (pi)."
    print_info "Usage: bash setup.sh"
    exit 1
fi

#=============================================================================
# Update System
#=============================================================================
print_header "Step 1: Updating System Packages"

print_info "This may take several minutes..."
sudo apt update
sudo apt upgrade -y
print_success "System updated successfully!"

#=============================================================================
# Install System Dependencies
#=============================================================================
print_header "Step 2: Installing System Dependencies"

print_info "Installing Python and development tools..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-setuptools \
    cmake \
    build-essential \
    pkg-config

print_info "Installing image processing libraries..."
sudo apt install -y \
    libopencv-dev \
    python3-opencv \
    libatlas-base-dev \
    libhdf5-dev \
    libhdf5-serial-dev \
    libjasper-dev \
    libqtgui4 \
    libqt4-test \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev

print_info "Installing machine learning libraries..."
sudo apt install -y \
    libopenblas-dev \
    liblapack-dev \
    gfortran

print_info "Installing camera support..."
sudo apt install -y \
    python3-picamera2 \
    v4l-utils

print_success "System dependencies installed!"

#=============================================================================
# Increase Swap Space (for compilation)
#=============================================================================
print_header "Step 3: Increasing Swap Space"

print_info "Current swap size:"
free -h | grep Swap

print_info "Increasing swap to 2GB for better compilation performance..."
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo systemctl restart dphys-swapfile
sleep 2

print_success "Swap space increased!"
free -h | grep Swap

#=============================================================================
# Install Python Packages
#=============================================================================
print_header "Step 4: Installing Python Packages"

print_info "Upgrading pip..."
python3 -m pip install --upgrade pip

print_info "Installing NumPy (required for other packages)..."
pip3 install numpy

print_info "Installing OpenCV..."
pip3 install opencv-python==4.5.3.56
pip3 install opencv-contrib-python==4.5.3.56

print_info "Installing MediaPipe..."
print_warning "This may take 5-10 minutes..."
pip3 install mediapipe==0.8.10

print_info "Installing dlib (required for face_recognition)..."
print_warning "This is the longest step - expect 30-60 minutes!"
print_info "Coffee break recommended ☕"
pip3 install dlib

print_info "Installing face_recognition..."
pip3 install face_recognition

print_info "Installing remaining packages..."
pip3 install imutils
pip3 install pyserial

print_success "All Python packages installed!"

#=============================================================================
# Configure Camera
#=============================================================================
print_header "Step 5: Configuring Camera"

print_info "Checking camera interface status..."
if sudo raspi-config nonint get_camera | grep -q "0"; then
    print_success "Camera interface is already enabled!"
else
    print_info "Enabling camera interface..."
    sudo raspi-config nonint do_camera 0
    print_success "Camera interface enabled!"
fi

print_info "Adding user to video group..."
sudo usermod -a -G video $USER
print_success "User added to video group!"

#=============================================================================
# Configure Serial Port for Arduino
#=============================================================================
print_header "Step 6: Configuring Serial Port"

print_info "Configuring serial port for Arduino communication..."

# Disable serial console
sudo raspi-config nonint do_serial 1

# Enable serial port hardware
sudo raspi-config nonint do_serial_hw 0

print_info "Adding user to dialout group..."
sudo usermod -a -G dialout $USER

print_success "Serial port configured!"

#=============================================================================
# Test Camera
#=============================================================================
print_header "Step 7: Testing Camera"

print_info "Testing camera connection..."
python3 -c "
import cv2
import sys
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print('ERROR: Camera not detected!')
    sys.exit(1)
ret, frame = cap.read()
cap.release()
if ret:
    print('SUCCESS: Camera is working!')
    sys.exit(0)
else:
    print('ERROR: Could not read from camera!')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    print_success "Camera test passed!"
else
    print_warning "Camera test failed. You may need to check the camera connection."
    print_info "After reboot, run: vcgencmd get_camera"
fi

#=============================================================================
# Test Python Imports
#=============================================================================
print_header "Step 8: Testing Python Imports"

print_info "Testing OpenCV..."
python3 -c "import cv2; print(f'OpenCV version: {cv2.__version__}')" && print_success "OpenCV OK"

print_info "Testing MediaPipe..."
python3 -c "import mediapipe; print(f'MediaPipe version: {mediapipe.__version__}')" && print_success "MediaPipe OK"

print_info "Testing face_recognition..."
python3 -c "import face_recognition; print('face_recognition imported successfully')" && print_success "face_recognition OK"

print_info "Testing NumPy..."
python3 -c "import numpy; print(f'NumPy version: {numpy.__version__}')" && print_success "NumPy OK"

print_info "Testing imutils..."
python3 -c "import imutils; print('imutils imported successfully')" && print_success "imutils OK"

print_info "Testing pySerial..."
python3 -c "import serial; print(f'pySerial version: {serial.__version__}')" && print_success "pySerial OK"

#=============================================================================
# Create Run Script
#=============================================================================
print_header "Step 9: Creating Run Script"

cat > run_wheelchair.sh << 'EOF'
#!/bin/bash
# Quick run script for wheelchair control system

cd "$(dirname "$0")/src"

echo "Starting Face-Controlled Wheelchair System..."
echo "Press Ctrl+C to exit"
echo ""

python3 main.py
EOF

chmod +x run_wheelchair.sh
print_success "Run script created: ./run_wheelchair.sh"

#=============================================================================
# Create Test Scripts
#=============================================================================
print_header "Step 10: Creating Test Scripts"

# Camera test script
cat > test_camera.sh << 'EOF'
#!/bin/bash
# Test camera functionality

echo "Testing camera..."
python3 << 'PYTHON'
import cv2
import time

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("ERROR: Cannot open camera")
    exit(1)

print("Camera opened successfully!")
print("Resolution: {}x{}".format(int(cap.get(3)), int(cap.get(4))))
print("FPS: {}".format(cap.get(5)))

print("\nCapturing 5 frames...")
for i in range(5):
    ret, frame = cap.read()
    if ret:
        print(f"Frame {i+1}: OK ({frame.shape})")
    else:
        print(f"Frame {i+1}: FAILED")
    time.sleep(0.2)

cap.release()
print("\nCamera test complete!")
PYTHON
EOF

chmod +x test_camera.sh

# Serial test script
cat > test_serial.sh << 'EOF'
#!/bin/bash
# Test Arduino serial connection

echo "Checking for connected serial devices..."
echo ""

if ls /dev/ttyUSB* 1> /dev/null 2>&1 || ls /dev/ttyACM* 1> /dev/null 2>&1; then
    echo "Found serial devices:"
    ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
    echo ""
    echo "Testing connection with CommManager..."
    cd src
    python3 -c "
import CommManager
import time
print('Initializing CommManager...')
cm = CommManager.CommManager()
cm.start()
if cm.ser is not None:
    print('Successfully connected to Arduino!')
    print(f'Port: {cm.ser.port}')
else:
    print('Could not connect to Arduino. Check USB connection.')
"
else
    echo "No serial devices found!"
    echo "Please connect your Arduino via USB and try again."
fi
EOF

chmod +x test_serial.sh

print_success "Test scripts created:"
print_info "  - ./test_camera.sh (Test camera)"
print_info "  - ./test_serial.sh (Test Arduino connection)"

#=============================================================================
# Create Quick Reference
#=============================================================================
cat > QUICK_START.txt << 'EOF'
═══════════════════════════════════════════════════════════════
  FACE-CONTROLLED WHEELCHAIR - QUICK START GUIDE
═══════════════════════════════════════════════════════════════

📋 SYSTEM STATUS CHECK:
  After reboot, verify everything is working:
  
  1. Test camera:          ./test_camera.sh
  2. Test Arduino:         ./test_serial.sh
  3. Check imports:        python3 -c "import cv2, mediapipe, face_recognition"

🚀 RUNNING THE SYSTEM:
  
  Simple way:              ./run_wheelchair.sh
  
  Manual way:              cd src && python3 main.py

🔧 HARDWARE SETUP:
  
  1. Connect USB camera to Raspberry Pi
  2. Connect Arduino to Raspberry Pi via USB
  3. Ensure Arduino is running the wheelchair_arduino-main code
  4. Power on wheelchair electronics

👤 ADDING USERS:
  
  1. Run the system
  2. Click "Add User" button on the right menu
  3. Follow on-screen instructions
  4. User images stored in: user_images/<username>/

⚙️ CALIBRATION:
  
  1. System auto-calibrates when new user logs in
  2. Manual calibration: Click "Calibrate" button
  3. Follow the instructions:
     - Position head neutrally
     - Raise eyebrows
     - Lower eyebrows

🎮 CONTROLS:
  
  HEAD MOVEMENT:
    - Tilt forward/back    → Speed control
    - Turn left/right      → Steering
  
  EYEBROW GESTURE:
    - Raise for 2 seconds  → Enable/Disable control
  
  TOUCH MENU:
    - Add User    → Register new user
    - Calibrate   → Recalibrate gestures
    - Home        → Reset steering to center
    - Exit        → Safely shutdown

🚨 TROUBLESHOOTING:
  
  Camera not working:
    - Check cable connection
    - Run: vcgencmd get_camera
    - Should show: supported=1 detected=1
  
  Arduino not detected:
    - Check USB connection
    - Run: ls /dev/ttyUSB* /dev/ttyACM*
    - Run: ./test_serial.sh
  
  System slow/laggy:
    - Close other applications
    - Check CPU temperature: vcgencmd measure_temp
    - Ensure good ventilation
  
  "Permission denied" errors:
    - Reboot after initial setup (required!)
    - Check groups: groups (should include video, dialout)

📁 PROJECT STRUCTURE:
  
  src/                     → Main application code
  user_images/             → User face images
  resources/               → UI images and backgrounds
  old-test/                → Legacy test scripts
  
  Key files:
    main.py                → Main application
    FaceMesh.py            → Head pose tracking
    GestureRecognizer.py   → Eyebrow detection
    FaceRecognizer.py      → User identification
    CommManager.py         → Arduino communication

🔒 SAFETY FEATURES:
  
  - 400ms timeout (no signal → stop)
  - Speed limited to 20%
  - Enable/disable control via gesture
  - Manual emergency stop button recommended

═══════════════════════════════════════════════════════════════
For issues or questions, check the README.md file.
═══════════════════════════════════════════════════════════════
EOF

print_success "Quick start guide created: QUICK_START.txt"

#=============================================================================
# Restore Normal Swap Size
#=============================================================================
print_header "Step 11: Restoring Swap Size"

print_info "Reducing swap back to default (100MB)..."
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=100/' /etc/dphys-swapfile

print_success "Swap size will be restored after reboot"

#=============================================================================
# Final Summary
#=============================================================================
print_header "✅ SETUP COMPLETE!"

echo ""
print_success "All components have been installed successfully!"
echo ""
print_info "📋 What was installed:"
echo "   ✓ System packages and dependencies"
echo "   ✓ Python 3 and pip"
echo "   ✓ OpenCV (computer vision)"
echo "   ✓ MediaPipe (face mesh tracking)"
echo "   ✓ face_recognition (user identification)"
echo "   ✓ pySerial (Arduino communication)"
echo "   ✓ Camera interface enabled"
echo "   ✓ Serial port configured"
echo ""
print_info "📝 Created helper scripts:"
echo "   ✓ run_wheelchair.sh - Quick start script"
echo "   ✓ test_camera.sh - Test camera"
echo "   ✓ test_serial.sh - Test Arduino"
echo "   ✓ QUICK_START.txt - Reference guide"
echo ""
print_warning "⚠️  IMPORTANT: You must reboot for all changes to take effect!"
echo ""
print_info "After reboot, test your setup:"
echo "   1. Run: ./test_camera.sh"
echo "   2. Run: ./test_serial.sh"
echo "   3. Run: ./run_wheelchair.sh"
echo ""
print_info "📖 Read QUICK_START.txt for detailed instructions"
echo ""
read -p "Would you like to reboot now? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Rebooting in 3 seconds..."
    sleep 3
    sudo reboot
else
    print_warning "Please reboot manually when ready:"
    print_info "sudo reboot"
fi
