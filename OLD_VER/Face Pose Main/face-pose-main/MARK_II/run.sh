#!/bin/bash
# MARK II Wheelchair Control System - Launch Script

# Change to the MARK_II directory
cd "$(dirname "$0")"

echo "=========================================="
echo "  MARK II - Face-Controlled Wheelchair"
echo "  Version 2.0.0"
echo "=========================================="
echo ""

# Kill any existing Python processes that might be holding the camera
echo "[INFO] Cleaning up old processes..."
pkill -9 -f "python.*main.py" 2>/dev/null || true
pkill -9 -f "libcamera" 2>/dev/null || true
sleep 1

# Check if we're on Raspberry Pi
if [ -f /etc/rpi-issue ]; then
    echo "[INFO] Running on Raspberry Pi"
    
    # Release camera by quick libcamera test
    if command -v libcamera-hello &> /dev/null; then
        timeout 1 libcamera-hello --nopreview -t 1 2>/dev/null || true
        sleep 0.5
    fi
    
    # Check if camera is available
    if [ -e /dev/video0 ] || vcgencmd get_camera 2>/dev/null | grep -q "detected=1"; then
        echo "[INFO] Camera detected"
    else
        echo "[WARNING] No camera detected!"
    fi
fi

# Check for required Python version
python_version=$(python3 --version 2>&1)
echo "[INFO] Python version: $python_version"

# Check for config file
if [ ! -f config/config.yaml ]; then
    echo "[ERROR] Configuration file not found: config/config.yaml"
    exit 1
fi
echo "[INFO] Configuration file found"

# Create logs directory if it doesn't exist
mkdir -p logs/sessions logs/telemetry src/logs

# Run the application
echo ""
echo "[INFO] Starting MARK II..."
echo ""

cd src
python3 main.py "$@"

exit_code=$?

# Cleanup on exit
echo ""
echo "[INFO] Cleaning up..."
pkill -9 -f "python.*main.py" 2>/dev/null || true
sleep 0.5

echo "[INFO] MARK II exited with code: $exit_code"
