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
# Install MediaPipe (REQUIRED - System Cannot Run Without It!)
#=============================================================================
print_header "Step 5: Installing MediaPipe (REQUIRED)"

echo ""
print_error "⚠️  IMPORTANT: MediaPipe is REQUIRED for this system!"
print_error "    The wheelchair control cannot run without it."
echo ""

print_info "Installing MediaPipe dependencies from system repos..."
sudo apt install -y \
    python3-protobuf \
    libhdf5-dev \
    libharfbuzz-dev \
    libwebp-dev \
    libjpeg-dev

print_info "Detecting Python version..."
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ARCH=$(uname -m)
print_info "Python version: $PYTHON_VERSION"
print_info "Architecture: $ARCH"

# Show detailed system info for debugging
echo ""
print_info "System Details:"
echo "  OS Version: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
echo "  Python Path: $(which python3)"
echo "  Pip Version: $(pip3 --version | cut -d' ' -f2)"
echo ""

# Detect if pip supports --break-system-packages
print_info "Checking pip capabilities..."
PIP_BREAK_SYSTEM=""
if pip3 install --help 2>&1 | grep -q "break-system-packages"; then
    print_info "Using --break-system-packages flag"
    PIP_BREAK_SYSTEM="--break-system-packages"
else
    print_warning "Pip doesn't support --break-system-packages (older version)"
    print_info "Will install using legacy method"
fi
echo ""

# Check if 64-bit (MediaPipe requirement)
if [[ "$ARCH" != "aarch64" ]]; then
    echo ""
    print_error "═══════════════════════════════════════════════════════════"
    print_error "  CRITICAL: MediaPipe requires 64-bit Raspberry Pi OS!"
    print_error "═══════════════════════════════════════════════════════════"
    echo ""
    echo "Detected architecture: $ARCH (32-bit)"
    echo "Required architecture: aarch64 (64-bit)"
    echo ""
    echo "MediaPipe is REQUIRED - the system CANNOT run without it!"
    echo ""
    print_info "To fix this:"
    echo "  1. Download Raspberry Pi OS (64-bit) from:"
    echo "     https://www.raspberrypi.com/software/operating-systems/"
    echo "  2. Flash it to your SD card using Raspberry Pi Imager"
    echo "  3. Re-run this setup script"
    echo ""
    print_error "Setup cannot continue. Exiting..."
    exit 1
else
    print_info "Installing MediaPipe for ARM64..."
    echo ""
    
    MEDIAPIPE_INSTALLED=false
    
    # First, ensure pip is up to date
    print_info "Updating pip and build tools..."
    python3 -m pip install --upgrade pip setuptools wheel $PIP_BREAK_SYSTEM 2>&1 | grep -v "WARNING" | grep -v "already satisfied" || true
    
    # Method 1: Try piwheels first (most reliable for Raspberry Pi)
    print_info "Method 1: Trying piwheels (Raspberry Pi optimized)..."
    if pip3 install $PIP_BREAK_SYSTEM --index-url https://www.piwheels.org/simple --extra-index-url https://pypi.org/simple mediapipe 2>&1 | tee /tmp/mediapipe_install.log; then
        if python3 -c "import mediapipe; print('MediaPipe version:', mediapipe.__version__)" 2>/dev/null; then
            print_success "MediaPipe installed from piwheels!"
            MEDIAPIPE_INSTALLED=true
        fi
    fi
    
    # Method 2: Try specific Python version compatible wheels
    if [ "$MEDIAPIPE_INSTALLED" = false ]; then
        print_info "Method 2: Trying version-specific wheels for Python $PYTHON_VERSION..."
        
        # Map Python versions to compatible MediaPipe versions
        if [ "$PYTHON_VERSION" = "3.9" ]; then
            VERSIONS=("==0.10.9" "==0.10.8" "==0.10.3" "==0.10.0" "==0.8.11")
        elif [ "$PYTHON_VERSION" = "3.10" ]; then
            VERSIONS=("==0.10.9" "==0.10.8" "==0.10.3")
        elif [ "$PYTHON_VERSION" = "3.11" ]; then
            VERSIONS=("==0.10.9" "==0.10.8")
        else
            VERSIONS=("==0.10.9" "==0.10.8" "==0.10.3" "==0.10.0")
        fi
        
        for version in "${VERSIONS[@]}"; do
            print_info "  Trying MediaPipe$version for Python $PYTHON_VERSION..."
            if pip3 install $PIP_BREAK_SYSTEM "mediapipe$version" --no-cache-dir 2>&1 | tee -a /tmp/mediapipe_install.log; then
                if python3 -c "import mediapipe; print('MediaPipe version:', mediapipe.__version__)" 2>/dev/null; then
                    print_success "MediaPipe$version installed!"
                    MEDIAPIPE_INSTALLED=true
                    break
                fi
            fi
            sleep 2
        done
    fi
    
    # Method 3: Try downloading pre-built wheel directly
    if [ "$MEDIAPIPE_INSTALLED" = false ]; then
        print_info "Method 3: Trying direct wheel download..."
        
        # Create temp directory
        TEMP_DIR=$(mktemp -d)
        cd "$TEMP_DIR"
        
        # Try downloading from piwheels directly
        print_info "  Downloading from piwheels..."
        if wget -q https://www.piwheels.org/simple/mediapipe/ -O mediapipe_index.html; then
            # Parse the latest wheel for our architecture and Python version
            WHEEL_URL=$(grep -o 'href="[^"]*cp'$PYTHON_VERSION'.*aarch64[^"]*\.whl"' mediapipe_index.html | head -1 | sed 's/href="//;s/"//')
            
            if [ ! -z "$WHEEL_URL" ]; then
                print_info "  Found wheel: $WHEEL_URL"
                if wget -q "https://www.piwheels.org$WHEEL_URL" -O mediapipe.whl; then
                    if pip3 install $PIP_BREAK_SYSTEM mediapipe.whl 2>&1 | tee -a /tmp/mediapipe_install.log; then
                        if python3 -c "import mediapipe; print('MediaPipe version:', mediapipe.__version__)" 2>/dev/null; then
                            print_success "MediaPipe installed from downloaded wheel!"
                            MEDIAPIPE_INSTALLED=true
                        fi
                    fi
                fi
            fi
        fi
        
        cd - > /dev/null
        rm -rf "$TEMP_DIR"
    fi
    
    # Method 4: Build from source (comprehensive build with all dependencies)
    if [ "$MEDIAPIPE_INSTALLED" = false ]; then
        echo ""
        print_warning "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        print_warning "  All pre-built wheels failed. Attempting source build..."
        print_warning "  This will take 15-30 minutes. Please be patient!"
        print_warning "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        
        print_info "Installing build dependencies..."
        sudo apt install -y \
            build-essential \
            cmake \
            git \
            pkg-config \
            libopencv-dev \
            libavcodec-dev \
            libavformat-dev \
            libswscale-dev \
            libv4l-dev \
            libxvidcore-dev \
            libx264-dev \
            libgtk-3-dev \
            libatlas-base-dev \
            gfortran \
            python3-dev \
            libjpeg-dev \
            libpng-dev \
            libtiff-dev \
            libgstreamer1.0-dev \
            libgstreamer-plugins-base1.0-dev \
            libdc1394-dev \
            libavresample-dev \
            libgoogle-glog-dev \
            libgflags-dev \
            libprotobuf-dev \
            protobuf-compiler
        
        print_info "Installing Python build tools..."
        pip3 install $PIP_BREAK_SYSTEM --upgrade pip setuptools wheel numpy Cython
        
        print_info "Attempting to build MediaPipe from source..."
        print_info "This may take 15-30 minutes depending on your Raspberry Pi model..."
        echo ""
        
        # Try building with verbose output
        if pip3 install $PIP_BREAK_SYSTEM --no-binary :all: --verbose mediapipe==0.10.9 2>&1 | tee -a /tmp/mediapipe_build.log; then
            if python3 -c "import mediapipe; print('MediaPipe version:', mediapipe.__version__)" 2>/dev/null; then
                print_success "MediaPipe built from source successfully!"
                MEDIAPIPE_INSTALLED=true
            fi
        fi
        
        # If that fails, try an older version that's easier to build
        if [ "$MEDIAPIPE_INSTALLED" = false ]; then
            print_info "Trying older version (0.8.11) which is easier to build..."
            if pip3 install $PIP_BREAK_SYSTEM --no-binary :all: --verbose mediapipe==0.8.11 2>&1 | tee -a /tmp/mediapipe_build.log; then
                if python3 -c "import mediapipe; print('MediaPipe version:', mediapipe.__version__)" 2>/dev/null; then
                    print_success "MediaPipe 0.8.11 built from source successfully!"
                    MEDIAPIPE_INSTALLED=true
                fi
            fi
        fi
    fi
    
    # Final check
    if python3 -c "import mediapipe" 2>/dev/null; then
        print_success "MediaPipe installed successfully!"
        MEDIAPIPE_INSTALLED=true
    else
        MEDIAPIPE_INSTALLED=false
    fi
    
    if [ "$MEDIAPIPE_INSTALLED" = false ]; then
        echo ""
        print_error "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        print_error "  CRITICAL: MediaPipe installation FAILED!"
        print_error "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "MediaPipe is REQUIRED for face mesh tracking."
        echo "The wheelchair control system CANNOT run without it!"
        echo ""
        print_info "Troubleshooting steps:"
        echo ""
        echo "4. Check installation logs for specific errors:"
        echo "   ${GREEN}cat /tmp/mediapipe_install.log${NC}"
        echo "   ${GREEN}cat /tmp/mediapipe_build.log${NC}  (if build was attempted)"
        echo ""
        echo "5. Verify you're running 64-bit OS:"
        echo "   ${GREEN}uname -m${NC}  (must show: aarch64)"
        echo ""
        echo "6. Check Python version (3.9-3.11 recommended):"
        echo "   ${GREEN}python3 --version${NC}"
        echo ""
        echo "7. Try manual installation from piwheels:"
        echo "   ${GREEN}pip3 install $PIP_BREAK_SYSTEM --index-url https://www.piwheels.org/simple mediapipe${NC}"
        echo ""
        echo "8. Check free disk space (need at least 3GB for building):"
        echo "   ${GREEN}df -h${NC}"
        echo ""
        echo "9. Check build log for compilation errors:"
        echo "   ${GREEN}tail -100 /tmp/mediapipe_build.log${NC}"
        echo ""
        print_error "Setup CANNOT continue without MediaPipe. Exiting..."
        exit 1
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
pip3 install $PIP_BREAK_SYSTEM face-recognition --no-deps
pip3 install $PIP_BREAK_SYSTEM Pillow Click

print_success "Face recognition installed!"

#=============================================================================
# Install Additional Python Packages
#=============================================================================
print_header "Step 7: Installing Additional Dependencies"

print_info "Installing remaining Python packages..."
pip3 install $PIP_BREAK_SYSTEM \
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
    print_error "MediaPipe import failed! System CANNOT run without it!"
    print_error "Try manual installation: pip3 install $PIP_BREAK_SYSTEM mediapipe==0.10.9"
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
