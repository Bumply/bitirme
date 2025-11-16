# MediaPipe Installation Troubleshooting

## Issue: "No matching distribution found for mediapipe"

This error occurs when MediaPipe doesn't have a pre-built wheel for your specific Python version on ARM architecture.

---

## Quick Fix Options

### Option 1: Try Specific Compatible Versions

```bash
# For Python 3.11
pip3 install --break-system-packages mediapipe==0.10.9

# For Python 3.10
pip3 install --break-system-packages mediapipe==0.10.3

# For Python 3.9
pip3 install --break-system-packages mediapipe==0.10.0

# Fallback (older but stable)
pip3 install --break-system-packages mediapipe==0.8.11
```

### Option 2: Check Your Python Version

```bash
python3 --version
```

MediaPipe ARM wheels are available for:
- ✅ Python 3.9
- ✅ Python 3.10
- ✅ Python 3.11
- ❌ Python 3.12 (limited support)

If you have Python 3.12, consider downgrading to 3.11.

### Option 3: Install from System Repos (if available)

```bash
# Check if available in your Raspberry Pi OS repos
apt search python3-mediapipe

# If found, install it
sudo apt install python3-mediapipe
```

---

## Alternative: Use Older MediaPipe

If the latest doesn't work, use the older stable version:

```bash
pip3 install --break-system-packages mediapipe==0.8.11 --no-cache-dir
```

**Note:** Version 0.8.11 is older but more widely compatible with ARM.

---

## Check Installation

After installing, verify it works:

```bash
python3 -c "import mediapipe as mp; print('MediaPipe version:', mp.__version__)"
```

---

## System Requirements

MediaPipe requires:
- **64-bit OS** (not 32-bit)
- **Python 3.9-3.11** (best support)
- **ARM64 architecture** (for Raspberry Pi 4/5)

### Check Your System:

```bash
# Check OS architecture
uname -m
# Should show: aarch64 (64-bit) or armv7l (32-bit)

# Check Python version
python3 --version

# Check if pip can see MediaPipe
pip3 index versions mediapipe
```

---

## If Nothing Works: Skip MediaPipe

The system can work without MediaPipe for face mesh, using alternative methods:

### Edit the code to use alternative face detection:

In `src/FaceMesh.py`, you can comment out MediaPipe and use OpenCV's DNN face detection:

```python
# Comment out MediaPipe imports
# import mediapipe as mp

# Use OpenCV instead
import cv2

# Use OpenCV's face detector
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)
```

---

## Manual Build (Last Resort - Takes Long Time!)

If you absolutely need the latest MediaPipe and no wheels exist:

```bash
# Install build dependencies
sudo apt install -y cmake build-essential python3-dev

# Build from source (30-60 minutes!)
pip3 install --break-system-packages mediapipe --no-binary mediapipe
```

⚠️ **Warning:** This takes a VERY long time and may fail due to memory issues.

---

## Recommended Solution

**Best approach:** Use a specific compatible version:

```bash
# Most reliable for Raspberry Pi 4 with Python 3.9-3.11
pip3 install --break-system-packages mediapipe==0.10.0 --no-cache-dir
```

If that doesn't work:

```bash
# Older but very stable
pip3 install --break-system-packages mediapipe==0.8.11 --no-cache-dir
```

---

## Update Raspberry Pi OS

Sometimes updating helps:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt full-upgrade -y
sudo reboot
```

Then try installing MediaPipe again.

---

## Check for 32-bit vs 64-bit Issue

MediaPipe wheels are **only available for 64-bit ARM**:

```bash
# Check your architecture
uname -m

# If it shows "armv7l" - you're on 32-bit (MediaPipe won't work)
# If it shows "aarch64" - you're on 64-bit (MediaPipe should work)
```

**If you're on 32-bit Raspberry Pi OS:**
- Re-flash your SD card with **64-bit Raspberry Pi OS**
- Download from: https://www.raspberrypi.com/software/operating-systems/

---

## Version Compatibility Table

| Python Version | MediaPipe Version | Status |
|----------------|-------------------|--------|
| 3.9 | 0.10.0 | ✅ Recommended |
| 3.10 | 0.10.3 | ✅ Recommended |
| 3.11 | 0.10.9 | ✅ Recommended |
| 3.11 | 0.10.8 | ✅ Good |
| Any | 0.8.11 | ✅ Stable fallback |
| 3.12 | Latest | ⚠️ Limited support |
| 3.7-3.8 | 0.8.x | ⚠️ Old but works |

---

## Still Having Issues?

1. **Share your system info:**
   ```bash
   python3 --version
   uname -m
   cat /etc/os-release
   ```

2. **Try the stable fallback:**
   ```bash
   pip3 install --break-system-packages mediapipe==0.8.11
   ```

3. **Check pip logs:**
   ```bash
   pip3 install --break-system-packages mediapipe --verbose
   ```

4. **Verify internet connection:**
   ```bash
   ping -c 3 pypi.org
   ```

---

## Summary

**Quick fix for most cases:**

```bash
# Try in this order:
pip3 install --break-system-packages mediapipe==0.10.0
# OR
pip3 install --break-system-packages mediapipe==0.10.3
# OR
pip3 install --break-system-packages mediapipe==0.8.11
```

**System will work even if MediaPipe fails** - Face recognition and basic features will still function!

---

**Last Updated:** November 2024  
**Tested On:** Raspberry Pi 4B (4GB), Raspberry Pi OS Bookworm (64-bit)
