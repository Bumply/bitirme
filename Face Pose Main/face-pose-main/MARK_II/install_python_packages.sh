#!/bin/bash
#=============================================================================
# IMMEDIATE FIX - Install Python Packages with PEP 668 Override
# Run this to continue after "externally-managed-environment" error
#=============================================================================

echo "========================================="
echo "Installing Python Packages"
echo "========================================="
echo ""

echo "Checking Python version..."
python3 --version

echo ""
echo "Installing packages with --break-system-packages flag..."
echo "(This is safe for a dedicated Raspberry Pi)"
echo ""

# Install dlib first (takes longest)
echo "[1/8] Installing dlib (10-20 minutes, be patient)..."
pip3 install --break-system-packages --no-cache-dir dlib==19.22.0

# Install other packages
echo "[2/8] Installing OpenCV..."
pip3 install --break-system-packages opencv-python==4.5.3.56

echo "[3/8] Installing MediaPipe..."
pip3 install --break-system-packages mediapipe==0.8.10

echo "[4/8] Installing face-recognition..."
pip3 install --break-system-packages face-recognition==1.3.0

echo "[5/8] Installing PySerial..."
pip3 install --break-system-packages pyserial==3.5

echo "[6/8] Installing PyYAML..."
pip3 install --break-system-packages PyYAML==6.0

echo "[7/8] Installing NumPy..."
pip3 install --break-system-packages numpy==1.21.0

echo "[8/8] Installing imutils..."
pip3 install --break-system-packages imutils==0.5.4

echo ""
echo "========================================="
echo "Testing Installation"
echo "========================================="
echo ""

python3 -c "import cv2; print('✓ OpenCV:', cv2.__version__)" || echo "✗ OpenCV failed"
python3 -c "import mediapipe; print('✓ MediaPipe works')" || echo "✗ MediaPipe failed"
python3 -c "import face_recognition; print('✓ Face Recognition works')" || echo "✗ Face Recognition failed"
python3 -c "import serial; print('✓ PySerial works')" || echo "✗ PySerial failed"
python3 -c "import yaml; print('✓ PyYAML works')" || echo "✗ PyYAML failed"
python3 -c "import numpy; print('✓ NumPy:', numpy.__version__)" || echo "✗ NumPy failed"
python3 -c "import imutils; print('✓ imutils works')" || echo "✗ imutils failed"

echo ""
echo "========================================="
echo "Installation Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. sudo reboot"
echo "2. cd /home/pi/MARK_II"
echo "3. python3 src/main.py"
echo ""
