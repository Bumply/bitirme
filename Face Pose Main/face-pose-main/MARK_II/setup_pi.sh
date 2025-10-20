#!/bin/bash
#=============================================================================
# MARK II - Modern Setup Script for Raspberry Pi
# Compatible with Raspberry Pi OS Bullseye/Bookworm (2023+)
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
# Install Core Dependencies
#=============================================================================
print_header "Step 2: Installing Core Dependencies"

print_info "Installing Python and build tools..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-setuptools \
    python3-venv \
    cmake \
    build-essential \
    pkg-config \
    git

print_success "Core tools installed!"

#=============================================================================
# Install Computer Vision Libraries
#=============================================================================
print_header "Step 3: Installing Computer Vision Libraries"

print_info "Installing OpenCV and dependencies..."
sudo apt install -y \
    python3-opencv \
    libopencv-dev \
    libatlas-base-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev

print_success "OpenCV installed!"

#=============================================================================
# Install Pi Camera Support
#=============================================================================
print_header "Step 4: Installing Pi Camera Support"

print_info "Installing picamera2 (for CSI ribbon camera)..."
sudo apt install -y \
    python3-picamera2 \
    python3-libcamera

print_info "Installing legacy camera support..."
sudo apt install -y \
    libraspberrypi-bin \
    libraspberrypi-dev

print_success "Camera support installed!"

#=============================================================================
# Install Machine Learning Libraries
#=============================================================================
print_header "Step 5: Installing Machine Learning Libraries"

print_info "Installing dlib dependencies..."
sudo apt install -y \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev

print_info "Installing dlib (this will take 10-20 minutes)..."
pip3 install --break-system-packages --no-cache-dir dlib==19.22.0

print_success "Machine learning libraries installed!"

#=============================================================================
# Install Python Packages
#=============================================================================
print_header "Step 6: Installing Python Packages"

print_info "Installing core Python packages..."
pip3 install --break-system-packages --upgrade pip setuptools wheel

print_info "Installing project dependencies..."
pip3 install --break-system-packages \
    opencv-python==4.5.3.56 \
    mediapipe==0.8.10 \
    face-recognition==1.3.0 \
    pyserial==3.5 \
    PyYAML==6.0 \
    numpy==1.21.0 \
    imutils==0.5.4

print_success "Python packages installed!"

#=============================================================================
# Enable Interfaces
#=============================================================================
print_header "Step 7: Enabling Hardware Interfaces"

print_info "Enabling camera interface..."
sudo raspi-config nonint do_camera 0

print_info "Enabling serial port..."
sudo raspi-config nonint do_serial 2

print_info "Enabling I2C (for sensors)..."
sudo raspi-config nonint do_i2c 0

print_success "Hardware interfaces enabled!"

#=============================================================================
# Set Permissions
#=============================================================================
print_header "Step 8: Setting Permissions"

print_info "Adding user to required groups..."
sudo usermod -a -G video $USER
sudo usermod -a -G dialout $USER
sudo usermod -a -G i2c $USER
sudo usermod -a -G gpio $USER

print_success "Permissions configured!"

#=============================================================================
# Test Installation
#=============================================================================
print_header "Step 9: Testing Installation"

print_info "Testing Python imports..."
python3 -c "import cv2; print('✓ OpenCV:', cv2.__version__)" || print_error "OpenCV import failed"
python3 -c "import mediapipe; print('✓ MediaPipe installed')" || print_error "MediaPipe import failed"
python3 -c "import face_recognition; print('✓ Face Recognition installed')" || print_error "Face Recognition import failed"
python3 -c "import serial; print('✓ PySerial installed')" || print_error "PySerial import failed"
python3 -c "import yaml; print('✓ PyYAML installed')" || print_error "PyYAML import failed"

print_info "Testing camera..."
if command -v libcamera-hello &> /dev/null; then
    print_success "Camera tools available (test with: libcamera-hello)"
else
    print_warning "Camera tools not found"
fi

print_info "Testing serial ports..."
if ls /dev/ttyUSB* 1> /dev/null 2>&1 || ls /dev/ttyACM* 1> /dev/null 2>&1; then
    print_success "Serial ports detected:"
    ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
else
    print_warning "No Arduino detected (plug in via USB)"
fi

#=============================================================================
# Cleanup
#=============================================================================
print_header "Step 10: Cleanup"

print_info "Cleaning up..."
sudo apt autoremove -y
sudo apt autoclean

print_success "Cleanup complete!"

#=============================================================================
# Summary
#=============================================================================
print_header "Setup Complete! 🎉"

echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo ""
echo "1. ${YELLOW}Reboot${NC} to apply all changes:"
echo "   ${BLUE}sudo reboot${NC}"
echo ""
echo "2. After reboot, ${YELLOW}test camera${NC}:"
echo "   ${BLUE}libcamera-hello --timeout 3000${NC}"
echo ""
echo "3. ${YELLOW}Navigate to project${NC}:"
echo "   ${BLUE}cd /home/pi/MARK_II${NC}"
echo ""
echo "4. ${YELLOW}Add your face images${NC}:"
echo "   ${BLUE}mkdir -p user_images/YourName${NC}"
echo "   ${BLUE}# Add 2-3 photos as 1.jpg, 2.jpg, 3.jpg${NC}"
echo ""
echo "5. ${YELLOW}Run the system${NC}:"
echo "   ${BLUE}python3 src/main.py${NC}"
echo ""
echo -e "${GREEN}========================================${NC}"
echo ""

print_warning "REBOOT REQUIRED for all changes to take effect!"
echo ""
read -p "Reboot now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Rebooting in 3 seconds..."
    sleep 3
    sudo reboot
fi
