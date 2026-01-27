# 🚀 Setup Instructions for Face-Controlled Wheelchair System

## Prerequisites

- **Hardware:**
  - Raspberry Pi 4 (recommended) or Raspberry Pi 3B+
  - New SD card (16GB minimum, 32GB recommended)
  - USB Camera or Raspberry Pi Camera Module
  - Arduino with wheelchair control code
  - USB cable for Arduino connection

- **Software:**
  - Raspberry Pi OS (Legacy, 32-bit) - Buster version
  - Raspberry Pi Imager (for flashing SD card)

---

## 🔥 Quick Setup (Automated)

### Step 1: Flash SD Card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Insert your SD card into your computer
3. Open Raspberry Pi Imager
4. **Choose OS:** Raspberry Pi OS (other) → **Raspberry Pi OS (Legacy, 32-bit)**
5. **Choose Storage:** Your SD card
6. **Click ⚙️ (Settings)** and configure:
   - ✅ Enable SSH
   - ✅ Set username: `pi` (or your preference)
   - ✅ Set password
   - ✅ Configure WiFi (optional)
   - ✅ Set locale and timezone
7. Click **Write** and wait (~15 minutes)

### Step 2: Boot Raspberry Pi

1. Insert SD card into Raspberry Pi
2. Connect monitor, keyboard, mouse
3. Power on
4. Wait for boot (first boot takes longer)

### Step 3: Transfer Project Files

Choose one method:

**Option A - USB Drive:**
```bash
# Insert USB drive, then copy
sudo mount /dev/sda1 /mnt
cp -r /mnt/face-pose-main ~/
cd ~/face-pose-main
```

**Option B - From Windows PC via SCP:**
```powershell
# On Windows PC (in PowerShell)
scp -r "c:\Users\Ali\Downloads\bitirme\Face Pose Main\face-pose-main" pi@<raspberry-pi-ip>:~/
```

**Option C - Git Clone:**
```bash
# If you have it on GitHub
git clone <your-repo-url>
cd face-pose-main
```

### Step 4: Run Automated Setup

```bash
cd ~/face-pose-main
chmod +x setup.sh
bash setup.sh
```

**⏱️ Time Required:** 
- System updates: 5-10 minutes
- Python packages: 45-90 minutes (most time spent on dlib/face_recognition)
- **Total: ~1-2 hours** (go have lunch! 🍕)

### Step 5: Reboot

After setup completes, reboot:
```bash
sudo reboot
```

### Step 6: Test Everything

```bash
cd ~/face-pose-main

# Test camera
./test_camera.sh

# Test Arduino connection
./test_serial.sh

# Run the system
./run_wheelchair.sh
```

---

## 🛠️ Manual Setup (If Automated Fails)

### 1. Update System
```bash
sudo apt update
sudo apt upgrade -y
```

### 2. Install System Dependencies
```bash
# Python and build tools
sudo apt install -y python3 python3-pip python3-dev cmake build-essential

# Image processing libraries
sudo apt install -y libopencv-dev python3-opencv libatlas-base-dev
sudo apt install -y libhdf5-dev libhdf5-serial-dev libjasper-dev
sudo apt install -y libqtgui4 libqt4-test libjpeg-dev libpng-dev

# Machine learning libraries
sudo apt install -y libopenblas-dev liblapack-dev gfortran

# Camera support
sudo apt install -y python3-picamera2 v4l-utils
```

### 3. Increase Swap (Temporary - for compilation)
```bash
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo systemctl restart dphys-swapfile
```

### 4. Install Python Packages
```bash
# Upgrade pip
pip3 install --upgrade pip

# Install packages (in order)
pip3 install numpy
pip3 install opencv-python==4.5.3.56
pip3 install mediapipe==0.8.10
pip3 install dlib  # This takes 30-60 minutes!
pip3 install face_recognition
pip3 install imutils
pip3 install pyserial
```

### 5. Configure Camera
```bash
# Enable camera
sudo raspi-config
# Navigate: Interface Options → Camera → Enable

# Add user to video group
sudo usermod -a -G video $USER
```

### 6. Configure Serial Port
```bash
# Disable serial console
sudo raspi-config
# Navigate: Interface Options → Serial Port
# Login shell: No
# Serial hardware: Yes

# Add user to dialout group
sudo usermod -a -G dialout $USER
```

### 7. Restore Swap Size
```bash
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=100/' /etc/dphys-swapfile
```

### 8. Reboot
```bash
sudo reboot
```

---

## 🧪 Testing

### Test Camera
```bash
vcgencmd get_camera  # Should show: supported=1 detected=1

python3 -c "
import cv2
cap = cv2.VideoCapture(0)
ret, frame = cap.read()
print('Camera OK' if ret else 'Camera FAILED')
cap.release()
"
```

### Test Python Imports
```bash
python3 -c "import cv2; print('OpenCV:', cv2.__version__)"
python3 -c "import mediapipe; print('MediaPipe OK')"
python3 -c "import face_recognition; print('face_recognition OK')"
python3 -c "import serial; print('pySerial OK')"
```

### Test Arduino Connection
```bash
# List serial devices
ls /dev/ttyUSB* /dev/ttyACM*

# Test with CommManager
cd ~/face-pose-main/src
python3 -c "
import CommManager
cm = CommManager.CommManager()
cm.start()
print('Arduino connected!' if cm.ser else 'Arduino not found')
"
```

---

## 🚨 Troubleshooting

### Camera Issues

**Problem:** Camera not detected
```bash
# Check camera interface
sudo raspi-config
# Ensure camera is enabled

# Check cable connection (if using ribbon cable)
# Check USB connection (if using USB camera)

# Test with raspistill (for Pi camera)
raspistill -o test.jpg

# Test with v4l (for USB camera)
v4l2-ctl --list-devices
```

**Problem:** "Permission denied" on camera
```bash
# Add user to video group
sudo usermod -a -G video $USER
sudo reboot
```

### Arduino Issues

**Problem:** Arduino not detected
```bash
# Check USB connection
lsusb  # Should show Arduino device

# Check serial ports
ls -l /dev/ttyUSB* /dev/ttyACM*

# Give permissions
sudo chmod 666 /dev/ttyUSB0  # or ttyACM0
```

**Problem:** "Permission denied" on serial port
```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER
sudo reboot

# Verify group membership
groups  # Should include 'dialout'
```

### Installation Issues

**Problem:** dlib or face_recognition won't install
```bash
# Increase swap space first
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo systemctl restart dphys-swapfile

# Install dependencies
sudo apt install -y cmake libopenblas-dev liblapack-dev gfortran

# Try again
pip3 install dlib
pip3 install face_recognition
```

**Problem:** "Out of memory" during compilation
```bash
# Close all programs
# Increase swap to 4GB
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=4096/' /etc/dphys-swapfile
sudo systemctl restart dphys-swapfile

# Try installation again
```

**Problem:** MediaPipe import error
```bash
# Ensure 32-bit OS (not 64-bit)
uname -m  # Should show: armv7l (32-bit) not aarch64 (64-bit)

# If 64-bit, reflash SD card with 32-bit OS
```

### Performance Issues

**Problem:** System is too slow
```bash
# Check CPU temperature
vcgencmd measure_temp

# If overheating (>80°C), add cooling:
# - Heatsinks
# - Fan
# - Better ventilation

# Reduce camera resolution in Capture.py
# Already set to low_res=True in FaceRecognizer
```

**Problem:** Face recognition too slow
- Already optimized with `low_res=True`
- Consider using fewer training images per user
- Reduce camera FPS if needed

---

## 📁 Project Structure

```
face-pose-main/
├── setup.sh              # Automated setup script (NEW!)
├── run_wheelchair.sh     # Quick run script (created by setup)
├── test_camera.sh        # Camera test script (created by setup)
├── test_serial.sh        # Arduino test script (created by setup)
├── QUICK_START.txt       # Quick reference (created by setup)
├── README.md             # Original documentation
├── src/
│   ├── main.py           # Main application
│   ├── FaceMesh.py       # Head pose tracking
│   ├── GestureRecognizer.py  # Eyebrow detection
│   ├── FaceRecognizer.py     # User identification
│   ├── CommManager.py    # Arduino communication
│   ├── Capture.py        # Camera interface
│   ├── TouchMenu.py      # UI menu
│   ├── TouchKeyboard.py  # Virtual keyboard
│   ├── Settings.py       # Configuration
│   └── User.py           # User data class
├── resources/
│   ├── atilim_logo_bg.jpg
│   ├── black_bg.jpg
│   └── user_list.txt
├── user_images/          # User face images (create during runtime)
│   ├── User1/
│   │   └── 1.jpg
│   └── User2/
│       └── 1.jpg
└── old-test/             # Legacy test scripts
```

---

## 🎮 First Run

### 1. Start the System
```bash
cd ~/face-pose-main
./run_wheelchair.sh
```

### 2. Add Your First User
1. Click **"Add User"** button on the right menu
2. Enter username
3. Enter password (set in Settings.py, default: check the file)
4. Face the camera - it will capture your face
5. User saved to `user_images/<username>/`

### 3. Calibrate
1. System auto-calibrates on first login
2. Follow on-screen instructions:
   - **Position head neutrally** (5 seconds)
   - **Stay still** (3 seconds)
   - **Raise eyebrows** (3 seconds)
   - **Lower eyebrows** (1 second)

### 4. Test Control
1. Raise eyebrows for 2 seconds → Enable control
2. Move head to test steering/speed
3. Raise eyebrows again for 2 seconds → Disable control

---

## 🔒 Safety Checklist

Before operating wheelchair:

- ✅ Test in safe, open area first
- ✅ Have physical emergency stop accessible
- ✅ Ensure Arduino failsafe works (400ms timeout)
- ✅ Test all gestures work reliably
- ✅ Verify speed limit (max 20%)
- ✅ Have someone nearby to assist
- ✅ Check battery levels
- ✅ Test "enable/disable" gesture works

---

## 💾 Backup Your SD Card

After successful setup:

### Windows:
1. Use [Win32 Disk Imager](https://sourceforge.net/projects/win32diskimager/)
2. Read SD card to .img file
3. Store backup safely

### Linux:
```bash
sudo dd if=/dev/sdX of=~/wheelchair_backup.img bs=4M status=progress
```

### Also backup user images:
```bash
cd ~/face-pose-main
tar -czf backup_$(date +%Y%m%d).tar.gz user_images/
```

---

## 📞 Getting Help

If you encounter issues:

1. Check **QUICK_START.txt** for common solutions
2. Read **Troubleshooting** section above
3. Check terminal output for error messages
4. Verify all hardware connections
5. Ensure you rebooted after initial setup

---

## ⚡ Performance Tips

- Use good quality USB camera (720p recommended)
- Ensure proper lighting for face detection
- Keep Raspberry Pi cool (heatsinks/fan)
- Close unnecessary programs
- Use wired connection if possible (not WiFi)
- Keep system updated: `sudo apt update && sudo apt upgrade`

---

## 🎓 Understanding the System

Read the detailed explanation in the main README.md to understand:
- How face tracking works
- Communication protocol
- Gesture detection
- Calibration process
- Safety features

---

**Good luck with your graduation project! 🎓🚀**
