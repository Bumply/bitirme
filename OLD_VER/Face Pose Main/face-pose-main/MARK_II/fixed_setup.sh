#!/bin/bash
#=============================================================================
# MARK II - Fixed Setup Script for Raspberry Pi (FIXED dlib compilation)
# Compatible with Raspberry Pi OS Bullseye/Bookworm (2023+)
# This version handles memory issues during dlib compilation
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
print_header "MARK II Wheelchair System Setup (FIXED)"

if [ "$EUID" -eq 0 ]; then 
    print_error "Please do not run as root. Run as regular user."
    exit 1
fi

print_info "Checking Raspberry Pi OS version..."
if [ -f /etc/os-release ]; then
    . /etc/os-release
    print_info "OS: $PRETTY_NAME"
fi

print_info "Checking available memory..."
free -h

#=============================================================================
# Increase Swap Space (Critical for dlib compilation)
#=============================================================================
print_header "Step 0: Increasing Swap Space"

print_info "Current swap configuration:"
free -h | grep Swap

print_warning "Increasing swap to 2GB for compilation..."
print_info "This prevents out-of-memory errors during dlib compilation"

sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon

print_info "New swap configuration:"
free -h | grep Swap

print_success "Swap space increased to 2GB!"

#=============================================================================
# Update System
#=============================================================================
print_header "Step 1: System Update"

print_info "Updating package lists..."
sudo apt update

print_info "Upgrading packages (this may take 5-10 minutes)..."
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
    git \
    wget

print_success "Core tools installed!"

#=============================================================================
# Install Computer Vision Libraries
#=============================================================================
print_header "Step 3: Installing Computer Vision Libraries"

print_info "Installing OpenCV and dependencies..."
sudo apt install -y \
    python3-opencv \
    python3-numpy \
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
# Install dlib Dependencies (CRITICAL - Added libboost)
#=============================================================================
print_header "Step 5: Installing dlib Dependencies"

print_info "Installing ALL dlib compilation dependencies..."
sudo apt install -y \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libboost-all-dev

print_success "dlib dependencies installed!"

#=============================================================================
# Enable Interfaces
#=============================================================================
print_header "Step 6: Enabling Hardware Interfaces"

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
print_header "Step 7: Setting Permissions"

print_info "Adding user to required groups..."
sudo usermod -a -G video $USER
sudo usermod -a -G dialout $USER
sudo usermod -a -G i2c $USER
sudo usermod -a -G gpio $USER

print_success "Permissions configured!"

#=============================================================================
# Install Python Packages (FIXED ORDER - Lightweight first, heavy last)
#=============================================================================
print_header "Step 8: Installing Python Packages"

print_info "Upgrading pip..."
pip3 install --break-system-packages --upgrade pip setuptools wheel

print_info "Installing lightweight packages first..."
pip3 install --break-system-packages \
    pyserial==3.5 \
    PyYAML==6.0 \
    imutils==0.5.4

print_success "Lightweight packages installed!"

print_warning "========================================="
print_warning "Installing dlib - This takes 15-30 minutes!"
print_warning "========================================="
print_info "☕ Perfect time for a coffee/tea break!"
print_info ""
print_info "You can monitor progress in another terminal with:"
print_info "  - htop (press 'q' to quit)"
print_info "  - top"
print_info ""
print_info "If CPU is at 100%, it's working. Don't interrupt!"
print_info "Starting dlib compilation now..."
print_info ""

# Install dlib with verbose output so user sees progress
pip3 install --break-system-packages --no-cache-dir --verbose dlib==19.22.0

print_success "========================================="
print_success "dlib compiled and installed successfully!"
print_success "========================================="

print_info "Installing face-recognition (quick, depends on dlib)..."
pip3 install --break-system-packages face-recognition==1.3.0

print_success "face-recognition installed!"

print_warning "Installing MediaPipe (this may take 5-10 minutes)..."
pip3 install --break-system-packages mediapipe==0.8.10

print_success "MediaPipe installed!"

print_info "Installing remaining packages..."
pip3 install --break-system-packages \
    opencv-python==4.5.3.56 \
    numpy==1.21.0

print_success "All Python packages installed!"

#=============================================================================
# Test Installation
#=============================================================================
print_header "Step 9: Testing Installation"

print_info "Testing Python imports..."
python3 << 'EOF'
import sys

packages = [
    ('cv2', 'OpenCV'),
    ('mediapipe', 'MediaPipe'),
    ('face_recognition', 'Face Recognition'),
    ('serial', 'PySerial'),
    ('yaml', 'PyYAML'),
    ('numpy', 'NumPy'),
    ('imutils', 'imutils')
]

failed = []
for module, name in packages:
    try:
        mod = __import__(module)
        version = getattr(mod, '__version__', 'installed')
        print(f'✓ {name}: {version}')
    except Exception as e:
        print(f'✗ {name}: FAILED - {e}')
        failed.append(name)

if failed:
    print(f'\n⚠️  Failed packages: {", ".join(failed)}')
    sys.exit(1)
else:
    print('\n✓ All packages imported successfully!')
EOF

print_info "Testing camera..."
if command -v libcamera-hello &> /dev/null; then
    print_success "Camera tools available"
    print_info "Test with: libcamera-hello --timeout 3000"
else
    print_warning "Camera tools not found"
fi

print_info "Testing serial ports..."
if ls /dev/ttyUSB* 1> /dev/null 2>&1 || ls /dev/ttyACM* 1> /dev/null 2>&1; then
    print_success "Serial ports detected:"
    ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
else
    print_warning "No Arduino detected (plug in via USB to test)"
fi

#=============================================================================
# Cleanup & Restore Swap
#=============================================================================
print_header "Step 10: Cleanup & Restore Swap"

print_info "Cleaning up apt packages..."
sudo apt autoremove -y
sudo apt autoclean

print_info "Restoring normal swap size (100MB)..."
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=100/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon

print_info "Final swap configuration:"
free -h | grep Swap

print_success "Cleanup complete! Swap restored to 100MB."

#=============================================================================
# Summary
#=============================================================================
print_header "Setup Complete! 🎉"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Installation Summary               ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} System updated"
echo -e "  ${GREEN}✓${NC} OpenCV & camera support (picamera2)"
echo -e "  ${GREEN}✓${NC} dlib & face-recognition"
echo -e "  ${GREEN}✓${NC} MediaPipe for face mesh"
echo -e "  ${GREEN}✓${NC} All Python dependencies"
echo -e "  ${GREEN}✓${NC} Hardware interfaces enabled"
echo -e "  ${GREEN}✓${NC} User permissions configured"
echo -e "  ${GREEN}✓${NC} Swap restored to normal"
echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          Next Steps                    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}1. REBOOT${NC} (required for permissions and interfaces):"
echo -e "   ${BLUE}sudo reboot${NC}"
echo ""
echo -e "${YELLOW}2. Test Camera${NC} (after reboot):"
echo -e "   ${BLUE}libcamera-hello --timeout 3000${NC}"
echo ""
echo -e "${YELLOW}3. Navigate to Project:${NC}"
echo -e "   ${BLUE}cd /home/pi/MARK_II${NC}"
echo ""
echo -e "${YELLOW}4. Add Your Face Images:${NC}"
echo -e "   ${BLUE}mkdir -p user_images/YourName${NC}"
echo -e "   ${BLUE}libcamera-still -o user_images/YourName/1.jpg${NC}"
echo -e "   ${BLUE}libcamera-still -o user_images/YourName/2.jpg${NC}"
echo -e "   ${BLUE}libcamera-still -o user_images/YourName/3.jpg${NC}"
echo ""
echo -e "${YELLOW}5. Connect Arduino:${NC}"
echo -e "   - Upload wheelchair_arduino code to Arduino"
echo -e "   - Connect via USB to Raspberry Pi"
echo ""
echo -e "${YELLOW}6. Run the Wheelchair System:${NC}"
echo -e "   ${BLUE}python3 src/main.py${NC}"
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""

print_warning "⚠️  REBOOT IS REQUIRED for all changes to take effect!"
echo ""
read -p "Reboot now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Rebooting in 5 seconds..."
    print_info "Reconnect via SSH after reboot!"
    sleep 5
    sudo reboot
else
    print_info "Remember to reboot before running the system!"
    print_info "Run: sudo reboot"
fi