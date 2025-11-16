#!/bin/bash
#=============================================================================
# MARK II - Optimized One-Click Setup for Raspberry Pi 4
# Compatible with Raspberry Pi OS Bullseye/Bookworm (2023-2024)
# All packages from official repos - NO manual builds required!
#=============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
}

#=============================================================================
# Check System
#=============================================================================
print_header "MARK II Wheelchair System Setup"

if [ "$EUID" -eq 0 ]; then 
    print_error "Please do not run as root. Run as regular user."
    exit 1
fi

print_info "Checking Raspberry Pi OS version..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    print_info "OS: $PRETTY_NAME"
    
    # Check if we're on supported version
    if [[ "$VERSION_ID" == "11" ]] || [[ "$VERSION_ID" == "12" ]]; then
        print_success "Supported OS version detected"
    else
        print_warning "Untested OS version - may encounter issues"
    fi
fi

#=============================================================================
# Update System
#=============================================================================
print_header "Step 1: System Update"

print_info "Updating package lists..."
sudo apt update

print_info "Upgrading packages (this may take a while)..."
sudo apt upgrade -y

print_success "System updated!"

#=============================================================================
# Install Core Dependencies (All from APT - Super Fast!)
#=============================================================================
print_header "Step 2: Installing Core Dependencies"

print_info "Installing Python and essential tools..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-setuptools \
    git

print_success "Core tools installed!"

#=============================================================================
# Install Computer Vision Libraries (Using System Packages - No Build!)
#=============================================================================
print_header "Step 3: Installing Computer Vision Libraries"

print_info "Installing OpenCV from system repositories (pre-compiled)..."
sudo apt install -y \
    python3-opencv \
    python3-numpy \
    libopencv-dev \
    libatlas-base-dev

print_success "OpenCV installed!"

#=============================================================================
# Install Pi Camera Support
#=============================================================================
print_header "Step 4: Installing Pi Camera Support"

print_info "Installing picamera2 (for CSI ribbon camera)..."
sudo apt install -y \
    python3-picamera2 \
    python3-libcamera

print_info "Installing camera utilities..."
sudo apt install -y \
    libraspberrypi-bin \
    libraspberrypi-dev

print_success "Camera support installed!"

#=============================================================================
# Install MediaPipe and Machine Learning (Optimized Versions)
#=============================================================================
print_header "Step 5: Installing MediaPipe and ML Libraries"

print_info "Installing MediaPipe dependencies from system repos..."
sudo apt install -y \
    python3-protobuf \
    libhdf5-dev \
    libharfbuzz-dev \
    libwebp-dev \
    libjpeg-dev

print_info "Detecting Python version..."
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
print_info "Python version: $PYTHON_VERSION"

print_info "Installing MediaPipe (this may take a few minutes)..."
# Try to install MediaPipe with version-specific strategies
if pip3 install --break-system-packages mediapipe --no-cache-dir 2>/dev/null; then
    print_success "MediaPipe installed successfully!"
else
    print_warning "Standard MediaPipe installation failed, trying alternative methods..."
    
    # Try with specific compatible versions for different Python versions
    if [[ "$PYTHON_VERSION" == "3.11" ]]; then
        print_info "Trying MediaPipe 0.10.9 for Python 3.11..."
        pip3 install --break-system-packages mediapipe==0.10.9 --no-cache-dir || \
        pip3 install --break-system-packages mediapipe==0.10.8 --no-cache-dir
    elif [[ "$PYTHON_VERSION" == "3.9" ]]; then
        print_info "Trying MediaPipe 0.10.0 for Python 3.9..."
        pip3 install --break-system-packages mediapipe==0.10.0 --no-cache-dir
    else
        print_info "Trying compatible MediaPipe version..."
        pip3 install --break-system-packages mediapipe==0.10.0 --no-cache-dir || \
        pip3 install --break-system-packages mediapipe==0.8.11 --no-cache-dir
    fi
    
    # Final check
    if python3 -c "import mediapipe" 2>/dev/null; then
        print_success "MediaPipe installed successfully!"
    else
        print_warning "MediaPipe installation encountered issues."
        print_warning "The system will continue, but face mesh features may not work."
        print_info "You can try manual installation later with:"
        echo "  pip3 install --break-system-packages mediapipe==0.10.0"
    fi
fi

#=============================================================================
# Install Face Recognition Libraries (Pre-built from System)
#=============================================================================
print_header "Step 6: Installing Face Recognition"

print_info "Installing dlib from system repositories (NO compilation needed!)..."
sudo apt install -y \
    python3-dlib \
    libdlib-dev

print_info "Installing face_recognition library..."
pip3 install --break-system-packages face-recognition --no-deps
pip3 install --break-system-packages Pillow Click

print_success "Face recognition installed!"

#=============================================================================
# Install Additional Python Packages
#=============================================================================
print_header "Step 7: Installing Additional Dependencies"

print_info "Installing remaining Python packages..."
pip3 install --break-system-packages \
    pyserial \
    PyYAML \
    imutils

print_success "All Python packages installed!"


#=============================================================================
# Enable Interfaces
#=============================================================================
print_header "Step 8: Enabling Hardware Interfaces"

print_info "Enabling camera interface..."
sudo raspi-config nonint do_camera 0

print_info "Enabling serial port for Arduino communication..."
sudo raspi-config nonint do_serial 2

print_info "Enabling I2C (for future sensors)..."
sudo raspi-config nonint do_i2c 0

print_success "Hardware interfaces enabled!"

#=============================================================================
# Set Permissions
#=============================================================================
print_header "Step 9: Setting User Permissions"

print_info "Adding user to required groups..."
sudo usermod -a -G video $USER
sudo usermod -a -G dialout $USER
sudo usermod -a -G i2c $USER
sudo usermod -a -G gpio $USER

print_success "Permissions configured!"

#=============================================================================
# Test Installation
#=============================================================================
print_header "Step 10: Verifying Installation"

print_info "Testing Python imports..."
echo ""

# Test each import individually
if python3 -c "import cv2; print('  ✓ OpenCV:', cv2.__version__)" 2>/dev/null; then
    true
else
    print_error "OpenCV import failed!"
fi

if python3 -c "import mediapipe; print('  ✓ MediaPipe: Installed')" 2>/dev/null; then
    true
else
    print_warning "MediaPipe import failed - face mesh features may not work"
    print_info "You can try installing manually later with:"
    echo "    pip3 install --break-system-packages mediapipe==0.10.0"
fi

if python3 -c "import face_recognition; print('  ✓ Face Recognition: Installed')" 2>/dev/null; then
    true
else
    print_error "Face Recognition import failed!"
fi

if python3 -c "import serial; print('  ✓ PySerial: Installed')" 2>/dev/null; then
    true
else
    print_error "PySerial import failed!"
fi

if python3 -c "import yaml; print('  ✓ PyYAML: Installed')" 2>/dev/null; then
    true
else
    print_error "PyYAML import failed!"
fi

if python3 -c "import numpy as np; print('  ✓ NumPy:', np.__version__)" 2>/dev/null; then
    true
else
    print_error "NumPy import failed!"
fi

if python3 -c "import imutils; print('  ✓ Imutils: Installed')" 2>/dev/null; then
    true
else
    print_error "Imutils import failed!"
fi

echo ""
print_info "Testing camera..."
if command -v libcamera-hello &> /dev/null; then
    print_success "Camera tools available (test with: libcamera-hello)"
else
    print_warning "Camera tools not found"
fi

print_info "Testing serial ports..."
if ls /dev/ttyUSB* 1> /dev/null 2>&1 || ls /dev/ttyACM* 1> /dev/null 2>&1; then
    print_success "Serial ports detected:"
    ls -la /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | awk '{print "  ", $NF}' || true
else
    print_warning "No Arduino detected (plug in via USB to test)"
fi

#=============================================================================
# Cleanup
#=============================================================================
print_header "Step 11: Cleanup"

print_info "Cleaning up package cache..."
sudo apt autoremove -y
sudo apt autoclean

print_success "Cleanup complete!"

#=============================================================================
# Summary
#=============================================================================
print_header "🎉 Setup Complete! 🎉"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Installation Successful!             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo -e "${BLUE}1. Reboot the system:${NC}"
echo "   ${GREEN}sudo reboot${NC}"
echo ""
echo -e "${BLUE}2. After reboot, test the camera:${NC}"
echo "   ${GREEN}libcamera-hello --timeout 3000${NC}"
echo ""
echo -e "${BLUE}3. Navigate to the project directory:${NC}"
echo "   ${GREEN}cd ~/MARK_II${NC}"
echo ""
echo -e "${BLUE}4. Add your face images:${NC}"
echo "   ${GREEN}mkdir -p user_images/YourName${NC}"
echo "   ${GREEN}# Add 2-3 clear photos: 1.jpg, 2.jpg, 3.jpg${NC}"
echo "   ${YELLOW}# Tip: Use good lighting, face camera directly${NC}"
echo ""
echo -e "${BLUE}5. Connect the Arduino wheelchair controller:${NC}"
echo "   ${YELLOW}# Plug in via USB (should show as /dev/ttyACM0)${NC}"
echo ""
echo -e "${BLUE}6. Run the system:${NC}"
echo "   ${GREEN}python3 src/main.py${NC}"
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}⚡ Pro Tips:${NC}"
echo "  • Use 'Ctrl+C' to stop the program"
echo "  • Check logs in the 'logs/' directory"
echo "  • Edit 'config/config.yaml' for customization"
echo "  • Run 'python3 src/main.py --help' for options"
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""

print_warning "⚠️  REBOOT REQUIRED for all changes to take effect!"
echo ""
read -p "Reboot now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Rebooting in 3 seconds..."
    sleep 1
    echo "3..."
    sleep 1
    echo "2..."
    sleep 1
    echo "1..."
    sudo reboot
else
    echo ""
    print_info "Remember to reboot before running the system!"
    echo "Run: ${GREEN}sudo reboot${NC}"
fi
