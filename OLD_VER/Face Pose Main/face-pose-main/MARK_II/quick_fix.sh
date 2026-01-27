#!/bin/bash
#=============================================================================
# Quick Fix Script - Continue After Failed Setup
# Run this to fix the Qt4 package errors and continue installation
#=============================================================================

echo "========================================="
echo "Quick Fix for Qt4 Package Errors"
echo "========================================="
echo ""

echo "[1/5] Installing core dependencies (skipping old Qt4 packages)..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-setuptools \
    cmake \
    build-essential \
    pkg-config \
    libopencv-dev \
    python3-opencv \
    libatlas-base-dev \
    libhdf5-dev \
    libhdf5-serial-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libopenblas-dev \
    python3-picamera2 \
    python3-libcamera

echo ""
echo "[2/5] Enabling camera..."
sudo raspi-config nonint do_camera 0

echo ""
echo "[3/5] Setting permissions..."
sudo usermod -a -G video,dialout,i2c,gpio $USER

echo ""
echo "[4/5] Installing Python packages..."
cd /home/pi/MARK_II 2>/dev/null || cd ~

pip3 install --break-system-packages --upgrade pip setuptools wheel
pip3 install --break-system-packages \
    opencv-python==4.5.3.56 \
    mediapipe==0.8.10 \
    face-recognition==1.3.0 \
    pyserial==3.5 \
    PyYAML==6.0 \
    numpy==1.21.0 \
    imutils==0.5.4

echo ""
echo "[5/5] Testing installation..."
python3 -c "import cv2; print('✓ OpenCV works')" || echo "✗ OpenCV failed"
python3 -c "import mediapipe; print('✓ MediaPipe works')" || echo "✗ MediaPipe failed"
python3 -c "import face_recognition; print('✓ Face Recognition works')" || echo "✗ Face Recognition failed"

echo ""
echo "========================================="
echo "Quick fix complete!"
echo "========================================="
echo ""
echo "Next: sudo reboot"
echo ""
