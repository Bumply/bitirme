# Quick Start Guide - MARK II

## 🚀 Ultra-Fast Setup (15 Minutes Total!)

### Prerequisites
- Raspberry Pi 4 (2GB+ RAM recommended)
- Raspberry Pi OS Bullseye or Bookworm
- Internet connection
- CSI Camera Module or USB webcam
- Arduino-based wheelchair controller

---

## 📦 Step 1: One-Click Installation (~10-15 minutes)

Run the optimized setup script that installs everything automatically:

```bash
cd ~/MARK_II
bash setup_pi.sh
```

**What it does:**
- ✅ Updates system packages
- ✅ Installs pre-compiled OpenCV (no build!)
- ✅ Installs pre-built Dlib (no compilation!)
- ✅ Installs MediaPipe with ARM wheels
- ✅ Configures camera and serial interfaces
- ✅ Sets up all permissions
- ✅ Verifies installation

**When prompted, reboot the system:**
```bash
sudo reboot
```

---

## 🎮 Step 2: Launch the System (EASIEST WAY!)

After reboot, use the **interactive launcher**:

```bash
cd ~/MARK_II
python3 launcher.py
```

This gives you a nice menu:
```
╔══════════════════════════════════════════════════════════╗
║  MARK II - Face-Controlled Wheelchair System             ║
╚══════════════════════════════════════════════════════════╝

Main Menu:
─────────────────────────────────────
  1) ▶  Start Application
  2) ◼  Stop Application
  3) 📋 View Recent Logs
  4) ⚠  View Error Logs
  5) 🗑  Clear Logs
  6) 📷 Reset Camera
  7) ⬇  Update from GitHub
  8) ❓ Help / How to Use
  0) ✕  Exit
```

**Press `1` to start, then follow on-screen instructions!**

---

## 🎯 Step 3: Add Your Face Images (~2 minutes)

Add your face images:

```bash
cd ~/MARK_II
mkdir -p user_images/YourName

# Copy 2-3 clear photos of your face
# Name them: 1.jpg, 2.jpg, 3.jpg
# Tips:
# - Use good lighting
# - Face the camera directly
# - No sunglasses or masks
# - Different angles/expressions help
```

**Quick test with picamera:**
```bash
libcamera-still -o test_photo.jpg
mv test_photo.jpg user_images/YourName/1.jpg
```

---

## ⚙️ Step 3: Configure Settings (~1 minute)

Edit `config/config.yaml` if needed (defaults work for most setups):

```yaml
# Camera settings
camera:
  source: 0  # 0 for USB camera, "picamera" for CSI module
  width: 640
  height: 480
  fps: 30

# Arduino communication
arduino:
  auto_detect: true  # Automatically finds Arduino
  # OR manually specify: port: "/dev/ttyACM0"

# Control settings (start conservative!)
control:
  max_speed_percent: 20  # Start at 20% for safety testing
  calibration_time_sec: 3  # Auto-calibration duration

# Gesture thresholds (fine-tune after testing)
gestures:
  pitch_threshold: 15  # Degrees up/down to trigger
  yaw_threshold: 20    # Degrees left/right to trigger
```

---

## 🎮 Step 4: Run the System (~1 minute)

Connect the Arduino wheelchair controller via USB, then:

```bash
cd ~/MARK_II
python3 src/main.py
```

**Expected output:**
```
[INFO] Starting MARK II Wheelchair Control System...
[INFO] Camera initialized: 640x480 @ 30 fps
[INFO] Arduino detected: /dev/ttyACM0
[INFO] Face recognition ready: 1 user(s) loaded
[INFO] System ready! Press Ctrl+C to stop
```

---

## 📖 First Time Usage

### Calibration (Automatic)
1. **Keep head in neutral position** - Look straight at camera
2. **Wait 3 seconds** - System calibrates automatically
3. **You'll see "Calibration complete"** message

### Controls
- **Enable Control**: Raise eyebrows and hold for 2 seconds
- **Move Forward**: Look down
- **Turn Left**: Look left
- **Turn Right**: Look right
- **Stop**: Look straight ahead
- **Disable Control**: Raise eyebrows and hold for 2 seconds again

### Safety
- System **starts disabled** - must enable with eyebrow raise
- **Maximum speed limited** to 20% by default
- **Face lost detection** - stops if you look away for 2+ seconds
- **Emergency stop** - Press Ctrl+C

---

## 🔧 Configuration Tips

### Speed Too Slow?
```yaml
control:
  max_speed_percent: 30  # Increase gradually
```

### Not Detecting Head Movement?
```yaml
control:
  min_control_pitch: 3   # Reduce (more sensitive)
  min_control_yaw: 3     # Reduce (more sensitive)
```

### Eyebrow Detection Issues?
```yaml
gesture:
  eyebrow_threshold: 60  # Reduce (more sensitive)
  hold_time: 1.5         # Reduce hold time
```

### Camera Issues?
```yaml
camera:
  width: 320      # Lower resolution = faster
  height: 240
  fps: 30
```

---

## 📝 Logs

### View Logs in Real-Time
```bash
tail -f logs/wheelchair.log
```

### Check for Errors
```bash
cat logs/wheelchair_error.log
```

### Enable Debug Mode
Edit `config/config.yaml`:
```yaml
logging:
  level: "DEBUG"  # Detailed logging
```

---

## 🆘 Troubleshooting

### Camera Not Found
```bash
# List cameras
ls -l /dev/video*

# Test camera
python3 -c "import cv2; cap = cv2.VideoCapture(0); print(cap.read()[0])"
```

### Arduino Not Found
```bash
# List serial ports
ls -l /dev/ttyUSB* /dev/ttyACM*

# Check permissions
sudo usermod -a -G dialout $USER
# Then reboot
```

### Face Not Recognized
1. Add more photos (at least 3)
2. Ensure good lighting
3. Photos should be clear, front-facing
4. Different angles/expressions help

### System Slow
```yaml
face_recognition:
  use_low_res: true  # Enable low-res mode
  
camera:
  width: 320   # Lower resolution
  height: 240
```

---

## ⚙️ Advanced Configuration

### Full Configuration File Location
```
MARK_II/config/config.yaml
```

### Key Sections
- **application**: App name, version
- **logging**: Log levels, file sizes
- **camera**: Camera settings
- **face_mesh**: Face tracking parameters
- **gesture**: Gesture detection
- **face_recognition**: Face recognition settings
- **control**: Movement control
- **arduino**: Serial communication
- **safety**: Safety limits
- **performance**: Performance tuning

### See README.md for Complete Documentation

---

## 📊 Check System Status

### While Running
Watch the console output:
- **Green "ENABLED"** = Control active
- **Red "DISABLED"** = Control inactive
- **FPS counter** = Performance
- **User name** = Recognition status

### Statistics
Logged every 300 frames (~10 seconds):
- Frames per second (FPS)
- Total frames processed
- Current user
- Wheelchair status

---

## 🎯 Next Steps

1. **Test in Safe Environment** - Open space, no obstacles
2. **Start with Low Speed** - 10-20% maximum
3. **Practice Gestures** - Get comfortable with controls
4. **Adjust Sensitivity** - Tune config.yaml to your preferences
5. **Add More Users** - Create folders in user_images/

---

## 📞 Support

### Check Logs First
```bash
# Main log
cat logs/wheelchair.log

# Errors only
cat logs/wheelchair_error.log
```

### Enable Debug Logging
```yaml
logging:
  level: "DEBUG"
```

### Common Issues
1. **"Camera not found"** → Check `/dev/video*` and permissions
2. **"Arduino not detected"** → Check `/dev/ttyUSB*` and permissions
3. **"Face not recognized"** → Add more photos with good lighting
4. **"System slow"** → Enable low-res mode, reduce resolution

---

## ✅ Checklist Before First Run

- [ ] Dependencies installed (`pip3 install -r requirements.txt`)
- [ ] Camera connected and working
- [ ] Arduino connected and recognized
- [ ] At least one user folder with photos in `user_images/`
- [ ] Config file edited (`config/config.yaml`)
- [ ] Permissions set (camera + serial groups)
- [ ] Safe testing environment prepared
- [ ] Emergency stop accessible (Ctrl+C)

---

**Ready to go! Run `python3 src/main.py` and enjoy your professional wheelchair control system!** 🎉
