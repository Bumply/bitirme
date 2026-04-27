# NeuroDrive — Technical Capabilities

A 3-node Brain-Computer Interface that reads motor imagery EEG, classifies it with a CNN running on a Coral Edge TPU, and drives a wheelchair.

---

## Signal Acquisition

| Capability | Specification |
|---|---|
| Channels | 8 simultaneous |
| ADC | ADS1299 (24-bit sigma-delta) |
| Sampling rate | 250 SPS per channel |
| Reference voltage | 2.64 V |
| Input resolution | ~0.31 µV/LSB at gain 24 |
| Interface | SPI @ 1 MHz |
| Lead-off detection | Per-channel, parsed from ADS1299 status bytes |
| Channel layout | FC3, FC4, C3, Cz, C4, CP3, CP4, FCz (10-20 system) |

## Signal Processing

| Capability | Specification |
|---|---|
| Power-line filter | 50 Hz IIR notch, Q = 30 |
| Bandpass filter | 8-30 Hz Butterworth, order 4 |
| Window length | 1 second (250 samples) |
| Window stride | 0.5 second (50 % overlap) |
| DSP latency | < 1 ms per window (Coral CPU) |
| Filter rejection | -40 dB at 50 Hz, sharp roll-off outside 8-30 Hz |

## Machine Learning

| Capability | Specification |
|---|---|
| Model | EEGNet (Lawhern et al. 2018) |
| Architecture | Temporal Conv → Depthwise Spatial Conv → Separable Conv → Dense |
| Parameters | 1,684 |
| Hyperparameters | F1 = 8, D = 2, F2 = 16, kernel = 64, dropout = 0.5 |
| Input shape | (1, 8, 250) — 1 second of 8-channel EEG |
| Output | 4-class softmax (Forward, Left, Right, Stop) |
| Quantization | int8 TFLite (Edge TPU compatible) |
| Training set | BCI-IV-2a (8 subjects, motor imagery) |
| Cross-subject accuracy | 43 % (4-class, chance = 25 %) |
| Personal calibration accuracy | 56 % (SITL) — target 75 - 85 % with real personal EEG |
| Personal fine-tuning strategy | Block 1 + 2 frozen, BatchNorm in eval mode, only Block 3 + classifier trained |

## Real-Time Performance

| Capability | Specification |
|---|---|
| Inference engine | Coral Edge TPU |
| Inference latency | ~ 4 ms per window |
| End-to-end latency (SPI → PWM) | < 10 ms (SITL measurement) |
| Inference rate | 2 Hz (one prediction every 0.5 s window) |
| Time budget headroom | 98.4 % (uses ~ 8 ms of the 500 ms budget) |
| Confidence gate | 40 % minimum confidence to issue a command |
| Vote smoothing | Majority vote over 3 consecutive predictions |

## Calibration & Adaptation

| Capability | Specification |
|---|---|
| Calibration session length | ~ 13 minutes (100 trials) |
| Trial structure | 2 s fixation + 4 s imagery + 2 s rest |
| Trials per class | 25 |
| Auto fine-tuning | Triggered automatically after recording completes |
| Fine-tune strategy | Frozen Block 1+2, BatchNorm locked, train Block 3 + head |
| Online adaptation | Active during normal use |
| Adaptation trigger | Every 50 high-confidence (> 80 %) predictions |
| Adaptation training | 5 micro epochs, learning rate 5e-5 |
| Result reporting | Before/after accuracy displayed on dashboard |

## Control & Motor Output

| Capability | Specification |
|---|---|
| Drive motor | 48 V brushless hub motor (max 18 A) |
| Drive controller | GD010-S5-703 intelligent BLDC controller |
| Throttle interface | MCP4725 12-bit I²C DAC, 0 - 3.5 V |
| Speed levels | 3 (low ~ 1.3 V, mid ~ 2.0 V, full 3.5 V) |
| Steering motor | 24 V geared DC, run at 12 V (50ZY series, 5000 RPM bare) |
| Steering driver | BTS7960 / IBT-2 H-bridge (43 A capable) |
| Steering control | PWM speed + direction, dual limit switches |
| Drive commands | Forward, Stop |
| Steering commands | Left, Right, Stop |
| Self-locking | Worm gearbox holds steering position when motor is off |

## Communication

| Capability | Specification |
|---|---|
| Coral → Pi 5 | UDP packets over WiFi, port 5000 |
| Pi 5 → Coral (calibration) | UDP packets over WiFi, port 5001 |
| Pi 5 → Arduino | USB Serial @ 115200 baud |
| Packet format | JSON `{"cmd": "F", "conf": 0.87, "ts": ...}` |
| WiFi mode | Coral hosts AP (SSID "NeuroDrive", IP 192.168.4.1) |
| Dashboard URL | `http://192.168.4.1:8081` |
| Dashboard port (legacy Jupyter) | 8080 |

## Safety

| Capability | Specification |
|---|---|
| Layer 1 — Software (Coral, Pi) | Confidence gate (40 %), majority vote (window 3), heartbeat timeout 3 s, speed limiter |
| Layer 2 — Firmware (Arduino) | Serial watchdog 2 s, battery cutoff, PWM ramp limiter, state machine validation |
| Layer 3 — Hardware | Physical E-stop wired to motor driver enable line; cuts power independent of all software |
| Hardware E-stop response | < 100 ms (electrical, mechanical button) |
| Software stop response | ~ 500 ms (next inference window) |
| Battery monitoring | Voltage divider on Arduino A0 |
| Battery warning | Configurable threshold (e.g., 11 V on a 12 V rail) |
| Battery cutoff | Configurable threshold (e.g., 10.5 V on a 12 V rail) |

## User Interface

| Capability | Specification |
|---|---|
| Dashboard | NiceGUI (Python) web app |
| Theme | Dark, custom CSS |
| Tabs | Drive, Calibrate, Settings |
| Drive tab | Live command display, confidence bar, manual D-pad, software E-stop, scrolling command log, packet stats |
| Calibrate tab | Visual cue area, trial progress, phase indicator, before/after accuracy |
| Settings tab | Network config, safety thresholds, serial port, calibration timing, model selection, adaptation toggle |
| Manual override | Dashboard D-pad always preempts BCI commands while held |
| Live data | Updated at ~ 2 Hz (matching inference rate) |

## Hardware Inventory

| Component | Role | Specs |
|---|---|---|
| Coral Dev Board Mini | Node 1 — BCI inference | ARM CPU + Edge TPU, 2 GB RAM, Mendel Linux |
| Raspberry Pi 5 | Node 2 — Dashboard + Safety | 4 GB RAM, WiFi, USB |
| Arduino Mega 2560 | Node 3 — Motor control | ATmega2560, 16 MHz |
| ADS1299 | EEG front-end | 8-ch, 24-bit, 250 SPS |
| MCP4725 | Throttle DAC | 12-bit, I²C, 0 - 3.5 V output |
| BTS7960 / IBT-2 | Steering H-bridge | 24 V / 43 A capable |
| GD010-S5-703 | Hub motor controller | 48 V, 18 A, brushless |
| 48 V Battery | Main power | Drives hub motor + buck converters |
| 48 V → 12 V Buck | Steering + Arduino rail | 12 V regulated output |

## Operating Conditions

| Capability | Specification |
|---|---|
| Battery | 48 V (drive), 12 V rail (logic + steering) |
| Continuous operating time | Determined by battery capacity |
| Indoor / outdoor | Indoor flat surfaces (no IP rating) |
| User input | Motor imagery (4-class) or manual dashboard override |
| Number of users | Single user, personalized via calibration |
| Setup time | ~ 13 min calibration + electrode placement |

---

*All SITL-measured values verified on a development PC with NVIDIA RTX 3060. End-to-end latency on the deployed Coral hardware is expected to remain < 50 ms based on Edge TPU inference benchmarks. Personal calibration accuracy improves significantly when using clean dry electrodes and a quiet recording environment.*
