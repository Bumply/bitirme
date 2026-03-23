# NeuroDrive — EEG-Controlled Wheelchair

A 3-node Brain-Computer Interface system that translates motor imagery EEG signals into wheelchair movement commands.

## System Overview

```
┌─────────────────────┐     WiFi (JSON)     ┌──────────────────┐    Serial (UART)    ┌─────────────────────┐
│   NODE 1: Coral      │ ─────────────────> │  NODE 2: Pi 5     │ ────────────────> │  NODE 3: Arduino     │
│   Dev Board Mini     │                     │  Raspberry Pi 5   │                    │  Mega 2560           │
│                      │                     │                    │                    │                      │
│  ADS1299 (8ch EEG)   │                     │  Dashboard UI      │                    │  Motor drivers       │
│  DSP filtering       │                     │  Safety logic      │                    │  State machine       │
│  EEGNet (Edge TPU)   │                     │  Command relay     │                    │  E-stop              │
│  Command output      │                     │  Data logging      │                    │  PWM control         │
└─────────────────────┘                     └──────────────────┘                    └─────────────────────┘
     On wheelchair                               On wheelchair                          On wheelchair
     (wired to EEG cap)                          (WiFi AP)                              (wired to motors)
```

## Motor Imagery Commands

| Brain Task | Command | Wheelchair Action | EEG Signature |
|-----------|---------|------------------|---------------|
| Right hand imagery | `L` | Steer left | C4 ERD (right motor cortex) |
| Left hand imagery | `R` | Steer right | C3 ERD (left motor cortex) |
| Feet imagery | `F` | Drive forward | Cz ERD (medial motor cortex) |
| Tongue imagery | `S` | Stop | Distinct broad cortical pattern |

## Hardware Bill of Materials

### Node 1 — EEG Acquisition + ML Inference
- Google Coral Dev Board Mini (ARM + Edge TPU)
- Portiloop PCB (ADS1299 8-channel 24-bit EEG analog front-end)
- EEG electrode cap (8 channels: FC3, FC4, C3, Cz, C4, CP3, CP4, FCz)
- Conductive gel + reference/ground electrodes

### Node 2 — Dashboard + Relay
- Raspberry Pi 5 (4GB+ RAM)
- MicroSD card (32GB+)
- WiFi (built-in, connects to Coral's AP)

### Node 3 — Motor Control
- Arduino Mega 2560
- Motor driver board (L298N or BTS7960 for wheelchair motors)
- Emergency stop button (hardware kill switch, bypasses all software)
- Power relay for motor enable/disable
- 12V/24V battery (wheelchair power)

### Development Machine (for training only)
- Any PC with NVIDIA GPU (RTX 3060 or better)
- Not mounted on wheelchair — used once to train the model

---

## Complete Build Roadmap

### PHASE 1 — Node 1: EEG + ML Pipeline
*All software runs on development PC first (SITL), then ports to Coral*

#### Step 1: SITL Pipeline [DONE]
- `node1_sitl_pipeline.py` — Replay BCI-IV-2a data at 250 SPS
- DSP chain: 50 Hz IIR notch (Q=30) -> 8-30 Hz Butterworth bandpass (order 4)
- Stateful per-channel filtering (sosfilt with zero-initialized state)
- ERD baseline estimation (EMA, alpha=0.15, min 3 rest windows)
- Thread architecture: StreamThread (250 SPS) + DSPThread (0.5s windows)

#### Step 2: EEGNet Pre-Training [DONE]
- `node1_training.py` — Train on BCI-IV-2a subjects 1-8, test on subject 9
- PyTorch + CUDA (RTX 3060), mixed precision (float16 Tensor Cores)
- EEGNet architecture: F1=8, D=2, F2=16, dropout=0.5
- 8 channels: FC3, FC4, C3, Cz, C4, CP3, CP4, FCz
- Export: PyTorch .pt + ONNX .onnx (TFLite on Coral)
- Result: ~43% cross-subject accuracy (4-class, chance=25%)

#### Step 3: Personal Calibration [DONE]
- `node1_calibrate.py` — Fine-tune base model on one person's data
- Freeze Block 1+2 (temporal + spatial conv), train Block 3 + classifier
- BN layers in frozen blocks kept in eval() mode (prevents stat drift)
- SITL result: 56% on subject 9 (expected 75-85% with real personal data)

#### Step 4: Real-Time Inference [DONE]
- `node1_inference.py` — Full pipeline: stream -> DSP -> EEGNet -> command
- Confidence threshold (40%) — below threshold, hold current command
- Majority vote smoothing (window=3) — prevents single-window jitter
- V -> uV scaling (1e6) to match training data
- Inference latency: ~4ms per window on GPU
- SITL result: 42.1% real-time accuracy, diverse command distribution

#### Step 5: Port to Coral Hardware [DEFERRED — needs Linux + Coral hardware]
- `node1_coral.py` written (ADS1299 SPI, TFLite Edge TPU, WiFi AP sender, auto-detects Coral vs laptop)
- Remaining: convert ONNX to int8 TFLite via `edgetpu_compiler` (Linux only)
- Remaining: set up WiFi AP on Coral (shell config)
- Remaining: test with real EEG cap + conductive gel
- Expected inference: ~2-5ms on Edge TPU

#### Step 6: Personal Calibration Recording Script [DONE]
- Dashboard calibration tab (Node 2) shows visual cues for each imagery task
- Protocol: 2s fixation -> 4s imagery -> 2s rest, 25 trials x 4 classes (~13 min)
- `CalibrationRecorder` in `node1_coral.py` listens on UDP 5001 for cue commands
- Records labeled EEG windows during imagery phases, saves to `calibration_data/`
- Auto-runs fine-tuning (freeze Block 1+2, train Block 3 + classifier)
- Sends before/after accuracy back to dashboard for display

#### Step 7: Online Adaptation [DONE]
- `OnlineAdapter` in `node1_coral.py` — accumulates high-confidence (>80%) predictions as pseudo-labels
- Micro fine-tune every 50 confident predictions (5 epochs, LR=5e-5)
- Same freeze strategy: Block 1+2 frozen, Block 3 + classifier trained
- BN freeze fix applied during micro fine-tune (frozen BN stays in eval mode)
- Tracks brain drift from fatigue, electrode impedance changes
- Toggleable via `ADAPT_ENABLED` config flag
- Only works with PyTorch engine (TFLite models are frozen by design)

---

### PHASE 2 — Node 2: Raspberry Pi 5 Dashboard

#### Step 8: WiFi Communication Protocol [DONE]
- `CommandSender` (Node 1) sends JSON: `{"cmd": "L", "conf": 0.85, "ts": ...}` via UDP
- `UDPListener` (Node 2) receives on port 5000
- Heartbeat timeout: 3s no-packet -> auto STOP
- Calibration control: Node 2 sends cue commands to Node 1 on port 5001

#### Step 9: Dashboard UI [DONE]
- `node2_dashboard.py` — NiceGUI dark-theme web app on port 8080
- Drive tab: glowing command display, D-pad manual override, confidence bar, command log
- Calibrate tab: visual cue protocol, progress bar, before/after accuracy results
- Settings tab: network, safety, serial, calibration config display

#### Step 10: Safety Logic [DONE]
- `SafetyController` in Node 2: heartbeat timeout (3s), command timeout (5s)
- E-stop: software button + hardware bypass (Node 3)
- Speed limit: adjustable from dashboard slider
- Geofencing: TODO (future — ultrasonic/LiDAR)

#### Step 11: Serial Relay to Arduino [DONE]
- `SerialRelay` in Node 2: single-byte commands via USB Serial (115200 baud)
- Protocol: `L`, `R`, `F`, `S`, `E` (e-stop)
- Auto-detects serial connection, falls back to log-only mode

---

### PHASE 3 — Node 3: Arduino Motor Control

#### Step 12: Motor Driver Interface [DONE]
- `node3_motor_control/node3_motor_control.ino` — Arduino Mega 2560 + L298N
- PWM speed control for left and right motors (pins 2, 3)
- Direction via H-bridge pins (22-25)
- Motor mapping: F=both forward, L=right fast/left slow, R=left fast/right slow, S=brake

#### Step 13: State Machine [DONE]
- States: IDLE, FORWARD, TURNING_LEFT, TURNING_RIGHT, STOPPING, ESTOP
- Smooth ramp engine: PWM steps every 20ms (configurable RAMP_STEP)
- STOPPING state ramps to zero then transitions to IDLE
- ESTOP: immediate motor kill via ISR, requires manual reset (S command + button release)

#### Step 14: Hardware Safety [DONE]
- Hardware E-stop on pin 18 (interrupt-driven, kills motors in ISR)
- Battery voltage monitor on A0 (voltage divider): warn at 11V, auto-stop at 10.5V
- Serial watchdog: auto-stop if no command from Pi for 2 seconds
- Periodic state ack to Pi every 200ms (so dashboard knows Arduino is alive)
- Max speed configurable from Node 2 via 'V' command

---

### PHASE 4 — Integration & Testing

#### Step 15: Bench Test (no wheelchair) [DONE]
- `bench_test.py` — automated test suite for the full pipeline
- Test 1: Full pipeline (Node 1 SITL -> UDP -> verify packets + command diversity)
- Test 2: Failsafe (simulate Node 1 dropout, verify heartbeat timeout)
- Test 3: E-stop override (verify e-stop blocks commands, reset works)
- Test 4: Command smoother (majority vote, low confidence rejection)
- Test 5: Serial protocol (verify single-byte uppercase command format)
- Hardware bench test with real nodes: TODO (needs all 3 boards on a desk)

#### Step 16: Wheelchair Integration [TODO — hardware only]
- Mount Coral + Pi + Arduino on wheelchair frame
- Wire motor drivers to wheelchair motors
- Route EEG cable to headrest area
- Mount E-stop button on armrest
- Cable management and strain relief

#### Step 17: Personal Calibration Session [TODO — hardware only]
- Fit EEG cap with conductive gel
- Run calibration recording script (Step 6)
- Fine-tune model on personal data
- Compile for Edge TPU and deploy to Coral
- Test accuracy with live EEG (target: 75-85%)

#### Step 18: Controlled Environment Testing [TODO — hardware only]
- Flat, open indoor space (gym or large room)
- Low speed only (walking pace or slower)
- Spotter walking alongside at all times
- Test each command individually, then combinations
- Record all sessions for analysis

#### Step 19: Iteration & Optimization [TODO — hardware only]
- Analyze confusion matrix from real sessions
- Adjust confidence threshold and vote window
- Re-calibrate model if accuracy drifts
- Tune motor speeds and ramp rates
- Add obstacle detection if needed (ultrasonic sensors)

---

## Current Status

**SOFTWARE: COMPLETE** — all code written and tested on development PC (SITL mode).
**REMAINING: HARDWARE ONLY** — Steps 5 (Coral port), 16-19 need physical hardware.

| Component | Status | Notes |
|-----------|--------|-------|
| SITL Pipeline | DONE | 5 validated runs |
| EEGNet Pre-Training | DONE | 43% cross-subject (8 subjects) |
| Personal Calibration | DONE | 56% SITL, BN freeze fix applied |
| Real-Time Inference | DONE | 42% real-time, 4ms latency |
| Coral Hardware Port | DEFERRED | node1_coral.py written, needs Linux + Coral |
| Calibration Recording | DONE | Dashboard cues + Node 1 recorder + auto fine-tune |
| Online Adaptation | DONE | Pseudo-label accumulation + micro fine-tune |
| Node 2 (Pi Dashboard) | DONE | NiceGUI dark UI, drive/calibrate/settings tabs |
| Node 3 (Arduino Motors) | DONE | State machine + ramp + e-stop + watchdog |
| Bench Test Suite | DONE | 5/5 tests passing |
| Wheelchair Integration | TODO | Hardware only — mount + wire |
| Personal Calibration | TODO | Hardware only — EEG cap + gel |
| Environment Testing | TODO | Hardware only — gym + spotter |
| Iteration | TODO | Hardware only — tune from real sessions |

## File Structure

```
NeuroDrive/
  node1_sitl_pipeline.py       # Step 1: SITL EEG replay + DSP filtering
  node1_training.py            # Step 2: EEGNet pre-training (PyTorch + CUDA)
  node1_calibrate.py           # Step 3: Personal fine-tuning
  node1_inference.py           # Step 4: Real-time SITL inference
  node1_coral.py               # Step 5-7: Production Coral pipeline + calibration + online adaptation
  node2_dashboard.py           # Step 8-11: Pi 5 dashboard + safety + serial relay
  node3_motor_control/
    node3_motor_control.ino    # Step 12-14: Arduino motor control + state machine + safety
  bench_test.py                # Step 15: Automated test suite (5 tests)
  models/                      # Saved .pt, .onnx, .tflite model files
  calibration_data/            # Recorded calibration EEG segments (.npz)
  logs/                        # Timestamped run logs (gitignored)
  README.md                    # This file
```

## Development Setup

```bash
# Clone
git clone https://github.com/Bumply/bitirme.git NeuroDrive
cd NeuroDrive

# Install Python dependencies (development PC)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install moabb mne numpy scipy scikit-learn matplotlib onnx
pip install nicegui pyserial   # for Node 2 dashboard
pip install tensorflow-cpu     # for TFLite export only

# Run SITL pipeline (test DSP)
python node1_sitl_pipeline.py

# Train EEGNet (uses GPU)
python node1_training.py

# Fine-tune on personal data (SITL: uses subject 9)
python node1_calibrate.py

# Run real-time inference (SITL)
python node1_inference.py

# Run production pipeline (SITL fallback on laptop)
python node1_coral.py

# Run dashboard (open http://localhost:8080)
python node2_dashboard.py

# Run bench test suite
python bench_test.py

# Upload Arduino sketch (Arduino IDE or arduino-cli)
# File: node3_motor_control/node3_motor_control.ino
```

## Key Design Decisions

1. **PyTorch over TensorFlow** — TF 2.11+ dropped native Windows GPU support. PyTorch CUDA works natively. tensorflow-cpu kept for TFLite export.
2. **8 channels** — ADS1299 supports 8. Using FC3, FC4, C3, Cz, C4, CP3, CP4, FCz for full motor cortex coverage.
3. **EEGNet** — Compact architecture (1,684 params), all ops supported by Edge TPU int8 quantization.
4. **3-node separation** — Coral handles real-time ML (latency-critical), Pi handles UI/safety (compute-heavy), Arduino handles motors (reliability-critical).
5. **Confidence threshold + vote smoothing** — Prevents uncertain predictions from moving the wheelchair. Safety first.
6. **Hardware E-stop** — Physical button that bypasses all software. Non-negotiable for a mobility device.
7. **Online adaptation** — High-confidence pseudo-labels + micro fine-tune tracks brain drift without manual recalibration.
