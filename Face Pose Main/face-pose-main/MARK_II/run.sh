#!/bin/bash
# MARK II Wheelchair Control System - Launch Script

# Change to the MARK_II directory
cd "$(dirname "$0")"

echo "=========================================="
echo "  MARK II - Face-Controlled Wheelchair"
echo "  Version 2.0.0"
echo "=========================================="
echo ""

# Check if we're on Raspberry Pi
if [ -f /etc/rpi-issue ]; then
    echo "[INFO] Running on Raspberry Pi"
    
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
mkdir -p logs/sessions logs/telemetry

# Run the application
echo ""
echo "[INFO] Starting MARK II..."
echo ""

cd src
python3 main.py "$@"

exit_code=$?

echo ""
echo "[INFO] MARK II exited with code: $exit_code"
