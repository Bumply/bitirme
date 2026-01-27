#!/bin/bash
# Launch MARK II on the main display (HDMI)
# Usage: bash run_remote.sh

print_msg() {
    echo -e "\033[1;36m[MARK II Launcher]\033[0m $1"
}

print_msg "Setting display to :0 (HDMI Output)..."
export DISPLAY=:0

# Optional: Add xhost permission if needed (usually not needed for same user)
# xhost +local:

print_msg "Starting Application..."
python3 app.py
