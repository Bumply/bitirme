# NeuroDrive — Technical Goals

**Project**: EEG-Controlled Wheelchair (Brain-Computer Interface)
**Timeline**: 1 month from current state to final presentation
**Status legend**: ✅ Done · ⏳ In progress · 📋 Planned

This document defines the concrete, measurable engineering goals for the NeuroDrive project. Each goal has explicit acceptance criteria so progress and final delivery can be evaluated objectively.

---

## 1. Mechanical & Power Integration

### G1.1 — Functional electric wheelchair platform
**Goal**: Assemble a self-propelled wheelchair with a 48V hub motor for propulsion and a 24V geared DC motor (run at 12V) for steering, mounted on a chassis.
**Acceptance**: The chassis moves under its own power, can be steered left/right, and can carry an adult user safely on flat ground.
**Status**: ✅ Hub motor working, steering motor + gearbox mounted

### G1.2 — Single-source power architecture
**Goal**: All electronics powered from one 48V battery via appropriate DC-DC conversion.
**Acceptance**: 48V → hub motor controller (direct), 48V → 12V buck → steering H-bridge + Arduino, 12V → 5V regulator → Coral + Pi 5. One master power switch isolates everything.
**Status**: ⏳ Hub motor power confirmed; buck converter for steering ready, not yet wired to system

### G1.3 — Mechanical steering limits
**Goal**: Steering motor must not over-rotate beyond mechanical safe range.
**Acceptance**: Two lever microswitches (full-left, full-right) cut the motor in their respective directions; firmware reads them and ignores further commands once triggered.
**Status**: 📋 Hardware ordered, firmware logic to be added once switches arrive

---

## 2. Embedded Hardware

### G2.1 — Three-node distributed system
**Goal**: Coral Dev Board Mini (BCI inference) ↔ Raspberry Pi 5 (dashboard + safety) ↔ Arduino Mega 2560 (motor control).
**Acceptance**: All three boards boot from cold, exchange messages, and run a continuous 30-minute session with no node-level resets.
**Status**: ⏳ Coral and Pi 5 confirmed; Arduino tested standalone with motor

### G2.2 — ADS1299 8-channel EEG acquisition
**Goal**: Capture 8 channels of 24-bit EEG at 250 SPS via SPI on the Coral.
**Acceptance**: Continuous SPI streaming with no missed samples for 5 minutes; lead-off detection bits parsed correctly; raw signal viewable in the dashboard.
**Status**: 📋 Driver code written, hardware not yet wired

### G2.3 — Edge TPU model deployment
**Goal**: Run the personalized EEGNet model on the Coral Edge TPU (not CPU).
**Acceptance**: Quantized int8 TFLite model compiled with `edgetpu_compiler`, deployed to Coral, returning predictions in ≤ 10 ms per inference on the Edge TPU delegate.
**Status**: ⏳ int8 model exists, edgetpu_compiler step not yet done

---

## 3. Signal Processing & Machine Learning

### G3.1 — Real-time DSP chain
**Goal**: Per-channel 50 Hz notch (Q=30) + 8-30 Hz Butterworth bandpass (order 4) on each EEG window.
**Acceptance**: Filter chain processes a 250-sample × 8-channel window in < 1 ms on the Coral CPU; passband response matches design within ±1 dB.
**Status**: ✅ Implemented and validated in SITL

### G3.2 — Pre-trained EEGNet on BCI-IV-2a
**Goal**: Train EEGNet (1,684 parameters) on motor imagery dataset, 8 subjects.
**Acceptance**: Cross-subject validation accuracy > 40 % on held-out windows (chance = 25 % for 4 classes); model exported to ONNX and TFLite.
**Status**: ✅ Trained, ~43 % cross-subject achieved

### G3.3 — Personal calibration protocol
**Goal**: Guided 100-trial calibration session that fine-tunes the model on individual user EEG.
**Acceptance**: After calibration, subject-specific accuracy > 55 % (4-class) on the same user's held-out trials. Block 1 + 2 frozen, BatchNorm in eval mode during fine-tune.
**Status**: ⏳ Software complete, awaiting first human subject session

### G3.4 — Online adaptation
**Goal**: Continuous adaptation during use to track session-to-session drift.
**Acceptance**: Predictions above 80 % confidence accumulated as pseudo-labels; micro fine-tune (5 epochs, LR 5e-5) triggers every 50 high-confidence windows; accuracy does not degrade by more than 5 percentage points over a 30-minute session.
**Status**: ⏳ Implemented in code, not yet measured on real subject

---

## 4. Real-Time Pipeline

### G4.1 — End-to-end latency budget
**Goal**: Time from EEG sample acquisition to motor PWM update.
**Acceptance**: < 50 ms p95 latency, measured on real hardware (not SITL) using either timestamps in log files or a logic analyzer probing the SPI clock and PWM output.
**Status**: 📋 SITL measurement < 10 ms; not measured on real hardware

### G4.2 — Confidence gating + vote smoothing
**Goal**: Reject low-quality predictions and stabilize commands across windows.
**Acceptance**: Predictions below 40 % confidence are ignored; final command is majority vote over the last 3 high-confidence predictions.
**Status**: ✅ Implemented and tested in SITL

---

## 5. Software Architecture

### G5.1 — Modular Python package
**Goal**: Refactor monolithic prototype into a clean `neurodrive` package.
**Acceptance**: Each component (DSP, model, inference engine, network, safety, calibration, hardware) is a separate module with a single responsibility; node entry-point scripts are < 200 lines each.
**Status**: ⏳ ~70 % complete (Phase 1-2 done; entry points pending)

### G5.2 — Automated test suite
**Goal**: Pytest-based regression tests.
**Acceptance**: ≥ 10 unit/integration tests covering DSP correctness, model I/O shapes, smoother logic, safety state transitions, and network protocol; all passing.
**Status**: ⏳ 5 bench tests exist as bare-assert scripts, conversion to pytest pending

---

## 6. User Interface

### G6.1 — Web dashboard over WiFi
**Goal**: Coral runs as a WiFi access point hosting a NiceGUI dashboard.
**Acceptance**: User connects phone or laptop to "NeuroDrive" SSID, opens browser to the dashboard URL, sees live EEG, current command, and confidence in real time.
**Status**: ⏳ Dashboard code complete, not yet served from Coral

### G6.2 — Three functional tabs
**Goal**: Drive (real-time control), Calibrate (cue protocol), Settings (configuration).
**Acceptance**: All three tabs work end-to-end: Drive shows live commands and manual D-pad override; Calibrate runs the visual cue session and reports results; Settings persists configuration to disk.
**Status**: ⏳ Code complete, integration testing pending

---

## 7. Safety

### G7.1 — Hardware E-stop
**Goal**: A physical button electrically cuts power to the motor drivers, independent of all software.
**Acceptance**: Pressing the button stops both motors within 100 ms even if all three microcontrollers are frozen.
**Status**: 📋 To be wired

### G7.2 — Multi-layer software watchdogs
**Goal**: Each communication link has an independent timeout that triggers STOP.
**Acceptance**: Coral → Pi heartbeat (3 s timeout), Pi → Arduino serial (2 s timeout); each tested by deliberately killing the upstream node and confirming the wheelchair stops.
**Status**: ⏳ Implemented, not yet end-to-end tested

### G7.3 — Battery undervoltage cutoff
**Goal**: Auto-stop before battery damage.
**Acceptance**: Arduino reads battery rail via voltage divider on ADC; warning at threshold-1, motor cutoff at threshold-2; tested with a bench power supply by sweeping voltage.
**Status**: ⏳ Code in place, calibration with real divider pending

---

## 8. Demonstration

### G8.1 — BCI-controlled drive
**Goal**: Live demo where the user controls the wheelchair using motor imagery alone.
**Acceptance**: After a single calibration session, the user navigates a basic course (forward, then turn, then stop) using BCI commands only, with manual override available but not used during the run.
**Status**: 📋 Final integration demo

### G8.2 — Manual override
**Goal**: D-pad on dashboard always preempts BCI commands.
**Acceptance**: While in EEG mode, pressing a D-pad button overrides the next BCI command and holds until released.
**Status**: ✅ Logic implemented; needs full-stack test

---

## 9. Documentation

### G9.1 — GitHub Pages site
**Goal**: Public-facing site documenting architecture, signal pipeline, ML model, calibration protocol, safety system, and these technical goals.
**Acceptance**: All sections complete with figures and metrics; goals page reflects current status.
**Status**: ⏳ Most sections present; goals page being added

### G9.2 — Reproducible setup
**Goal**: A fresh git clone + `pip install` should be runnable on Windows, Linux, and Coral.
**Acceptance**: README's quick-start commands succeed on a clean environment without manual fixes.
**Status**: ⏳ Working on dev machine, not yet validated on a clean environment

---

## Summary

| Category | Goals | ✅ Done | ⏳ In Progress | 📋 Planned |
|---|---|---|---|---|
| Mechanical & Power | 3 | 0 | 1 | 2 |
| Embedded Hardware | 3 | 0 | 1 | 2 |
| ML & DSP | 4 | 2 | 2 | 0 |
| Real-Time Pipeline | 2 | 1 | 0 | 1 |
| Software Architecture | 2 | 0 | 2 | 0 |
| User Interface | 2 | 0 | 2 | 0 |
| Safety | 3 | 0 | 2 | 1 |
| Demonstration | 2 | 1 | 0 | 1 |
| Documentation | 2 | 0 | 2 | 0 |
| **Total** | **23** | **4** | **12** | **7** |

Last updated: 2026-04-27
