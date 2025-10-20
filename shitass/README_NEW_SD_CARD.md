# 📦 What's in Your SD Card Setup Package

This folder contains everything you need to set up your Raspberry Pi from scratch after the SD card issue.

## 🎯 Quick Start (3 Steps!)

### 1️⃣ Flash Your SD Card
- Use Raspberry Pi Imager
- Choose: **Raspberry Pi OS (Legacy, 32-bit)** 
- Flash to your new SD card
- Enable SSH in settings (⚙️ icon)

### 2️⃣ Transfer Project to Pi
- Boot your Raspberry Pi
- Find its IP address: `hostname -I`
- Run on Windows: **`transfer_to_pi.bat`**
- Or use USB drive to copy files

### 3️⃣ Run Setup Script
```bash
cd ~/face-pose-main
bash setup.sh
```

Wait 1-2 hours, reboot, done! ✅

---

## 📄 Files Explanation

### **For Windows PC:**

| File | Purpose | When to Use |
|------|---------|-------------|
| `transfer_to_pi.bat` | Transfers project to Pi via network | After Pi boots up |
| `SETUP_INSTRUCTIONS.md` | Detailed setup guide | Read if automated setup fails |
| `README_NEW_SD_CARD.md` | This file! Quick reference | Read first |

### **For Raspberry Pi:**

| File | Purpose | When to Use |
|------|---------|-------------|
| `setup.sh` | **Main setup script** - installs everything | Run once on new Pi |
| `run_wheelchair.sh` | Start the wheelchair system | After setup complete |
| `test_camera.sh` | Test if camera works | After setup to verify |
| `test_serial.sh` | Test Arduino connection | After setup to verify |
| `diagnose.sh` | Check system health | When having issues |
| `QUICK_START.txt` | Quick reference for daily use | Keep for reference |

---

## 🚀 Step-by-Step Process

### On Windows PC:

1. **Flash SD Card** using Raspberry Pi Imager
   - Download from: https://www.raspberrypi.com/software/
   - Select: "Raspberry Pi OS (Legacy, 32-bit)"
   - Enable SSH in advanced settings

2. **Transfer Files** to Pi
   - Option A: Run `transfer_to_pi.bat` (needs PuTTY installed)
   - Option B: Copy to USB drive, then to Pi
   - Option C: Use SCP/WinSCP manually

### On Raspberry Pi:

1. **Boot Up** with new SD card
   ```bash
   # Check you're on the Pi
   uname -a
   ```

2. **Navigate to Project**
   ```bash
   cd ~/face-pose-main
   ls -la  # Should see all files
   ```

3. **Make Scripts Executable**
   ```bash
   chmod +x setup.sh run_wheelchair.sh test_camera.sh test_serial.sh diagnose.sh
   ```

4. **Run Setup** (This is the big one!)
   ```bash
   bash setup.sh
   ```
   
   What it does:
   - ☕ Updates system (5-10 min)
   - 📦 Installs dependencies (10-15 min)
   - 🐍 Installs Python packages (45-90 min)
   - 📷 Configures camera
   - 🔌 Configures serial port
   - ✅ Tests everything
   - 🎯 Creates helper scripts

5. **Reboot** (Required!)
   ```bash
   sudo reboot
   ```

6. **Test Setup**
   ```bash
   cd ~/face-pose-main
   
   # Test camera
   ./test_camera.sh
   
   # Test Arduino
   ./test_serial.sh
   
   # Check system
   ./diagnose.sh
   ```

7. **Run System**
   ```bash
   ./run_wheelchair.sh
   ```

---

## ⏱️ Time Expectations

- **Flash SD Card:** 10-15 minutes
- **First Boot:** 2-3 minutes
- **Transfer Files:** 1-5 minutes (depends on method)
- **Run setup.sh:** 60-120 minutes ⏰
  - Most time spent compiling `dlib` (30-60 min)
  - Good time for a meal break! 🍕
- **Testing:** 5 minutes
- **Total:** ~2-3 hours from scratch to running

---

## 🔧 What Gets Installed

### System Packages:
- Python 3 development tools
- OpenCV libraries
- Camera drivers
- Serial port tools
- Build tools (gcc, cmake, etc.)

### Python Packages:
- **opencv-python** (4.5.3.56) - Computer vision
- **mediapipe** (0.8.10) - Face mesh tracking
- **face_recognition** - User identification
- **dlib** - Machine learning (takes longest to install!)
- **numpy** - Math operations
- **imutils** - Video utilities
- **pyserial** - Arduino communication

### Configurations:
- Camera interface enabled
- Serial port configured
- User added to `video` and `dialout` groups
- Swap space temporarily increased (during setup)

---

## 🚨 If Something Goes Wrong

### Setup script fails?
```bash
# Run diagnostics
./diagnose.sh

# Check what's missing
# Then follow manual setup in SETUP_INSTRUCTIONS.md
```

### Camera not working?
```bash
# Test camera
./test_camera.sh

# Or manually:
vcgencmd get_camera  # Should show: detected=1
raspistill -o test.jpg  # Takes a photo
```

### Arduino not connecting?
```bash
# Test Arduino
./test_serial.sh

# Check USB connection
ls /dev/ttyUSB* /dev/ttyACM*

# Check Arduino has correct code uploaded
```

### System too slow?
```bash
# Check temperature
vcgencmd measure_temp

# Should be < 80°C
# Add heatsink/fan if overheating
```

### Import errors?
```bash
# Test each package
python3 -c "import cv2; print('OpenCV OK')"
python3 -c "import mediapipe; print('MediaPipe OK')"
python3 -c "import face_recognition; print('face_recognition OK')"

# Reinstall if needed
pip3 install --upgrade <package-name>
```

---

## 📞 Help & Resources

### Documentation:
- **SETUP_INSTRUCTIONS.md** - Detailed setup guide
- **QUICK_START.txt** - Daily usage reference
- **README.md** - Original project documentation

### Scripts:
- **diagnose.sh** - System health check
- **test_camera.sh** - Camera test
- **test_serial.sh** - Arduino test

### Useful Commands:
```bash
# Check system info
uname -a
cat /etc/os-release

# Check IP address
hostname -I

# Check running processes
ps aux | grep python

# Check logs
journalctl -xe

# Restart system
sudo reboot

# Shutdown safely
sudo shutdown -h now
```

---

## 💡 Pro Tips

1. **Keep a backup!** After successful setup:
   - Image your SD card with Win32DiskImager
   - Backup user_images folder regularly

2. **Label your SD card** so you know it's configured

3. **Write down your Pi's IP address** for easy access

4. **Test with Arduino connected** before actual wheelchair

5. **Add users in good lighting** for better face recognition

6. **Calibrate each time** user changes for best accuracy

7. **Keep Pi cool** - use heatsink or fan for better performance

---

## ✅ Success Checklist

After setup, verify:

- [ ] SD card flashed with correct OS version
- [ ] Pi boots successfully
- [ ] Network/WiFi connected
- [ ] Project files transferred
- [ ] setup.sh completed without errors
- [ ] System rebooted
- [ ] test_camera.sh passes
- [ ] test_serial.sh passes (Arduino connected)
- [ ] Can run ./run_wheelchair.sh
- [ ] Can add new user
- [ ] Calibration works
- [ ] Face recognition works
- [ ] Arduino receives commands

---

## 🎓 Your Graduation Project is Ready!

Once everything checks out:
1. Add yourself as first user
2. Calibrate
3. Test controls in safe area
4. Demo to advisors
5. Graduate! 🎉

**Good luck! You've got this! 💪**

---

## 📝 Quick Command Reference

```bash
# Transfer (on Windows)
transfer_to_pi.bat

# Setup (on Pi - run once)
cd ~/face-pose-main
bash setup.sh
sudo reboot

# Test (after reboot)
./test_camera.sh
./test_serial.sh
./diagnose.sh

# Run (daily use)
./run_wheelchair.sh

# Troubleshoot
./diagnose.sh
cat SETUP_INSTRUCTIONS.md
cat QUICK_START.txt
```

---

**Last Updated:** October 8, 2025  
**For:** Wheelchair Control System Graduation Project  
**Hardware:** Raspberry Pi 4, USB Camera, Arduino
