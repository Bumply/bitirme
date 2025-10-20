#!/bin/bash
#=============================================================================
# System Diagnostics Script
# Run this if you're having issues with the wheelchair system
#=============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  WHEELCHAIR SYSTEM DIAGNOSTICS${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

#=============================================================================
# System Information
#=============================================================================
echo -e "${GREEN}[1] System Information${NC}"
echo "-------------------------------------------"
echo "Hostname: $(hostname)"
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
echo "Kernel: $(uname -r)"
echo "Architecture: $(uname -m)"
echo "Uptime: $(uptime -p)"
echo "Temperature: $(vcgencmd measure_temp 2>/dev/null || echo 'N/A')"
echo "Memory:"
free -h | grep Mem
echo "Swap:"
free -h | grep Swap
echo ""

#=============================================================================
# Python Environment
#=============================================================================
echo -e "${GREEN}[2] Python Environment${NC}"
echo "-------------------------------------------"
echo "Python version: $(python3 --version)"
echo "Pip version: $(pip3 --version | cut -d' ' -f1-2)"
echo ""

#=============================================================================
# Python Packages
#=============================================================================
echo -e "${GREEN}[3] Required Python Packages${NC}"
echo "-------------------------------------------"

check_package() {
    local package=$1
    python3 -c "import $package; print('$package:', $package.__version__ if hasattr($package, '__version__') else 'installed')" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} $package is installed"
    else
        echo -e "  ${RED}✗${NC} $package is MISSING"
    fi
}

check_package "cv2"
check_package "mediapipe"
check_package "face_recognition"
check_package "numpy"
check_package "imutils"
check_package "serial"
echo ""

#=============================================================================
# Camera Check
#=============================================================================
echo -e "${GREEN}[4] Camera Status${NC}"
echo "-------------------------------------------"

# Check camera interface
if command -v vcgencmd &> /dev/null; then
    camera_status=$(vcgencmd get_camera 2>/dev/null)
    echo "Camera interface: $camera_status"
    if [[ $camera_status == *"detected=1"* ]]; then
        echo -e "  ${GREEN}✓${NC} Camera is detected"
    else
        echo -e "  ${RED}✗${NC} Camera not detected"
    fi
else
    echo "  vcgencmd not available (not a Raspberry Pi?)"
fi

# Check video devices
echo "Video devices:"
if ls /dev/video* 1> /dev/null 2>&1; then
    ls -l /dev/video*
    echo -e "  ${GREEN}✓${NC} Video devices found"
else
    echo -e "  ${RED}✗${NC} No video devices found"
fi

# Check video group membership
if groups | grep -q video; then
    echo -e "  ${GREEN}✓${NC} User is in 'video' group"
else
    echo -e "  ${RED}✗${NC} User is NOT in 'video' group"
    echo "  Fix: sudo usermod -a -G video $USER && sudo reboot"
fi

# Test camera capture
echo "Testing camera capture..."
python3 << 'PYTHON'
import cv2
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("  ✗ Cannot open camera")
    exit(1)
ret, frame = cap.read()
cap.release()
if ret:
    print(f"  ✓ Camera capture successful ({frame.shape})")
else:
    print("  ✗ Cannot read from camera")
PYTHON
echo ""

#=============================================================================
# Serial/Arduino Check
#=============================================================================
echo -e "${GREEN}[5] Arduino/Serial Connection${NC}"
echo "-------------------------------------------"

# Check USB devices
echo "USB devices:"
lsusb 2>/dev/null || echo "lsusb not available"

# Check serial ports
echo "Serial ports:"
if ls /dev/ttyUSB* /dev/ttyACM* 1> /dev/null 2>&1; then
    ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
    echo -e "  ${GREEN}✓${NC} Serial devices found"
else
    echo -e "  ${RED}✗${NC} No serial devices found"
    echo "  Check: Is Arduino connected via USB?"
fi

# Check dialout group membership
if groups | grep -q dialout; then
    echo -e "  ${GREEN}✓${NC} User is in 'dialout' group"
else
    echo -e "  ${RED}✗${NC} User is NOT in 'dialout' group"
    echo "  Fix: sudo usermod -a -G dialout $USER && sudo reboot"
fi

# Test Arduino connection
if [ -f "src/CommManager.py" ]; then
    echo "Testing Arduino connection..."
    cd src
    python3 << 'PYTHON'
import CommManager
import sys
try:
    cm = CommManager.CommManager()
    cm.start()
    if cm.ser is not None and cm.ser.port is not None:
        print(f"  ✓ Arduino connected on {cm.ser.port}")
        sys.exit(0)
    else:
        print("  ✗ Arduino not connected")
        sys.exit(1)
except Exception as e:
    print(f"  ✗ Error: {e}")
    sys.exit(1)
PYTHON
    cd ..
else
    echo "  CommManager.py not found (run from project root)"
fi
echo ""

#=============================================================================
# Disk Space
#=============================================================================
echo -e "${GREEN}[6] Disk Space${NC}"
echo "-------------------------------------------"
df -h / | tail -n 1
available=$(df / | tail -n 1 | awk '{print $4}')
if [ $available -lt 1000000 ]; then
    echo -e "  ${YELLOW}⚠${NC} Low disk space!"
else
    echo -e "  ${GREEN}✓${NC} Sufficient disk space"
fi
echo ""

#=============================================================================
# Network
#=============================================================================
echo -e "${GREEN}[7] Network${NC}"
echo "-------------------------------------------"
hostname -I
if [ $? -eq 0 ]; then
    echo -e "  ${GREEN}✓${NC} Network is connected"
else
    echo -e "  ${RED}✗${NC} Network issue"
fi
echo ""

#=============================================================================
# Project Files
#=============================================================================
echo -e "${GREEN}[8] Project Files${NC}"
echo "-------------------------------------------"

check_file() {
    if [ -f "$1" ]; then
        echo -e "  ${GREEN}✓${NC} $1"
    else
        echo -e "  ${RED}✗${NC} $1 (MISSING)"
    fi
}

check_file "src/main.py"
check_file "src/FaceMesh.py"
check_file "src/GestureRecognizer.py"
check_file "src/FaceRecognizer.py"
check_file "src/CommManager.py"
check_file "src/Capture.py"
check_file "resources/black_bg.jpg"
check_file "resources/atilim_logo_bg.jpg"

if [ -d "user_images" ]; then
    user_count=$(find user_images -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
    echo -e "  ${GREEN}✓${NC} user_images/ directory exists ($user_count users)"
else
    echo -e "  ${YELLOW}⚠${NC} user_images/ directory missing (will be created)"
fi
echo ""

#=============================================================================
# Process Check
#=============================================================================
echo -e "${GREEN}[9] Running Processes${NC}"
echo "-------------------------------------------"
if pgrep -f "main.py" > /dev/null; then
    echo -e "  ${GREEN}✓${NC} Wheelchair system is running"
    echo "  PID: $(pgrep -f "main.py")"
else
    echo -e "  ${BLUE}ℹ${NC} Wheelchair system is not running"
fi
echo ""

#=============================================================================
# Summary
#=============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  DIAGNOSTICS COMPLETE${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Common fixes:"
echo "  • Camera not working: sudo raspi-config → Interface → Camera"
echo "  • Permission errors: sudo reboot (after adding to groups)"
echo "  • Arduino not found: Check USB cable, try different port"
echo "  • Package errors: pip3 install --upgrade <package>"
echo "  • Low memory: Increase swap or reduce camera resolution"
echo ""
echo "For detailed troubleshooting, see SETUP_INSTRUCTIONS.md"
echo ""
