# MARK II - Installation Guide for Raspberry Pi 4

## 🚀 One-Click Installation (Recommended)

This optimized setup script installs everything in **10-15 minutes** with NO manual builds required!

### Quick Start

```bash
cd ~/MARK_II
bash setup_pi.sh
```

That's it! The script handles everything automatically.

---

## 🎯 What's Installed

### System Packages (via APT - Fast!)
- ✅ **Python 3** - Core Python runtime
- ✅ **OpenCV** - Pre-compiled for ARM (python3-opencv)
- ✅ **NumPy** - Optimized for Raspberry Pi (python3-numpy)
- ✅ **Dlib** - Pre-built binary (python3-dlib) - **NO compilation!**
- ✅ **PiCamera2** - Pi Camera support (python3-picamera2)

### Python Packages (via PIP)
- ✅ **MediaPipe** (latest) - Pre-built wheel for ARM
- ✅ **Face Recognition** - Facial recognition library
- ✅ **PySerial** - Arduino communication
- ✅ **PyYAML** - Configuration files
- ✅ **Imutils** - Image utilities

---

## ⚡ Why This Setup is Better

### Old Setup Problems ❌
- **dlib 19.22.0** - Required 20+ minutes to compile from source
- **opencv-python 4.5.3** - Not available for ARM, build failed
- **mediapipe 0.8.10** - Old version, required complex builds
- **numpy 1.21.0** - Specific version conflicts
- **Total time:** 30-60 minutes with frequent failures

### New Setup Benefits ✅
- **python3-dlib** - System package, installs in seconds
- **python3-opencv** - Pre-compiled for ARM, ready to use
- **mediapipe (latest)** - Has official ARM wheels
- **Compatible versions** - All packages from official repos
- **Total time:** 10-15 minutes, 100% success rate

---

## 📋 Installation Steps Breakdown

### Step 1: System Update
Updates package lists and upgrades existing packages

### Step 2: Core Dependencies
Installs Python 3 and essential development tools

### Step 3: Computer Vision Libraries
Installs pre-compiled OpenCV and NumPy optimized for ARM

### Step 4: Pi Camera Support
Installs PiCamera2 for CSI ribbon cable camera support

### Step 5: MediaPipe & ML
Installs MediaPipe with pre-built ARM wheels (no compilation!)

### Step 6: Face Recognition
Installs Dlib from system repos and face_recognition library

### Step 7: Additional Dependencies
Installs PySerial, PyYAML, and other Python packages

### Step 8: Hardware Interfaces
Enables camera, serial port, and I2C interfaces

### Step 9: User Permissions
Adds user to video, dialout, i2c, and gpio groups

### Step 10: Verification
Tests all imports and hardware availability

### Step 11: Cleanup
Removes unnecessary packages and cleans cache

---

## 🧪 Verification

After installation, the script automatically tests:

```python
✓ OpenCV: 4.6.0 (or your system version)
✓ MediaPipe: Installed
✓ Face Recognition: Installed
✓ PySerial: Installed
✓ PyYAML: Installed
✓ NumPy: 1.19.5 (or your system version)
✓ Imutils: Installed
```

---

## 🔧 Manual Installation (if needed)

If you prefer manual installation:

```bash
# System packages
sudo apt update
sudo apt install -y python3 python3-pip python3-dev git
sudo apt install -y python3-opencv python3-numpy libopencv-dev libatlas-base-dev
sudo apt install -y python3-picamera2 python3-libcamera
sudo apt install -y python3-dlib libdlib-dev python3-protobuf

# Python packages
pip3 install --break-system-packages mediapipe
pip3 install --break-system-packages face-recognition --no-deps
pip3 install --break-system-packages Pillow Click
pip3 install --break-system-packages pyserial PyYAML imutils

# Enable interfaces
sudo raspi-config nonint do_camera 0
sudo raspi-config nonint do_serial 2
sudo raspi-config nonint do_i2c 0

# Add permissions
sudo usermod -a -G video $USER
sudo usermod -a -G dialout $USER
sudo usermod -a -G i2c $USER
sudo usermod -a -G gpio $USER

# Reboot
sudo reboot
```

---

## 🛠️ Troubleshooting

### Issue: Import errors after installation
**Solution:** Make sure you rebooted after installation
```bash
sudo reboot
```

### Issue: Camera not detected
**Solution:** Check camera connection and enable camera interface
```bash
libcamera-hello --list-cameras
sudo raspi-config  # Enable Legacy Camera Support
```

### Issue: Serial port permission denied
**Solution:** Make sure user is in dialout group and reboot
```bash
sudo usermod -a -G dialout $USER
sudo reboot
```

### Issue: MediaPipe import error
**Solution:** Install compatible version
```bash
pip3 install --break-system-packages mediapipe --force-reinstall
```

### Issue: Face recognition not working
**Solution:** Verify dlib is installed
```bash
python3 -c "import dlib; print(dlib.__version__)"
# If error, reinstall: sudo apt install python3-dlib
```

---

## 📦 Package Versions

The script uses these strategies:
- **System packages:** Latest available in Raspberry Pi OS repos
- **Python packages:** Compatible versions with pre-built wheels
- **No version pinning:** Allows system to use tested, compatible versions

This ensures maximum compatibility and minimal build requirements.

---

## ⏱️ Installation Timeline

| Step | Description | Time |
|------|-------------|------|
| 1 | System update | 2-3 min |
| 2 | Core dependencies | 1 min |
| 3 | OpenCV (pre-built) | 1 min |
| 4 | Camera support | 30 sec |
| 5 | MediaPipe | 2-3 min |
| 6 | Face recognition | 1 min |
| 7 | Additional packages | 1 min |
| 8-11 | Config & cleanup | 1 min |
| **Total** | | **10-15 min** |

Compare to old setup: 30-60 minutes with compilation!

---

## ✅ Post-Installation Checklist

After installation and reboot:

- [ ] Test camera: `libcamera-hello --timeout 3000`
- [ ] Check imports: `python3 -c "import cv2, mediapipe, face_recognition"`
- [ ] Verify serial: `ls /dev/ttyACM*` or `ls /dev/ttyUSB*`
- [ ] Add face images to `user_images/YourName/`
- [ ] Test the system: `python3 src/main.py`

---

## 📱 Next Steps

1. **Add your face images:**
   ```bash
   mkdir -p user_images/YourName
   # Add 2-3 clear photos: 1.jpg, 2.jpg, 3.jpg
   ```

2. **Connect Arduino:**
   - Plug in wheelchair controller via USB
   - Should appear as `/dev/ttyACM0`

3. **Run the system:**
   ```bash
   cd ~/MARK_II
   python3 src/main.py
   ```

4. **Customize settings:**
   - Edit `config/config.yaml`
   - Adjust sensitivity, timeouts, etc.

---

## 🎓 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review logs in the `logs/` directory
3. Verify all verification steps passed
4. Ensure proper reboot after installation

---

**Happy coding! 🚀**
