"""
================================================================================
NEURODRIVE — NODE 1 | REAL-TIME INFERENCE
================================================================================
Runs the full pipeline: EEG stream → DSP filtering → EEGNet → wheelchair command.

Modes:
    SITL    : Replays BCI-IV-2a data at 250 SPS (for testing without hardware)
    HARDWARE: Reads live ADS1299 via spidev (swap stream_generator)

Architecture:
    [StreamThread] ─── 250 SPS filtered samples ──► [SharedState buffer]
                                                           │
    [InferenceThread] ── wakes every 0.5s ─────────────────┘
            │ grabs 1-second window (250 samples, 8 channels)
            │ reshapes to (1, 1, 8, 250)
            │ runs EEGNet forward pass
            │ argmax → command (L / R / F / S)
            │ sends command to Node 2 via WiFi (future)
            ▼
        Terminal display + log file

Usage:
    python node1_inference.py

================================================================================
"""

import time
import threading
import collections
import sys
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import torch
import torch.nn.functional as F

# Reuse components from the SITL pipeline and training script
sys.path.insert(0, str(Path(__file__).parent))
from node1_sitl_pipeline import (
    TeeLogger, FilterChain, SharedState,
    design_notch_filter, design_bandpass_filter,
    load_bci_data, stream_generator, run_stream_thread,
    FS, BUFFER_SIZE, CHANNELS, N_CH, DSP_INTERVAL_S,
    LABEL_DISPLAY, CLASS_MAP, LOG_DIR,
)
from node1_training import EEGNet, CLASS_NAMES, N_CLASSES, MODELS_DIR


# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Which model to use for inference
# Use pre-trained model (43% cross-subject). Once calibration is fixed,
# swap to the personal model for higher accuracy.
MODEL_PATH = MODELS_DIR / "EEGNet_pretrain_20260312_004816.pt"

# Confidence threshold — below this, output IDLE (no command sent)
# Prevents the wheelchair from acting on uncertain predictions
CONFIDENCE_THRESHOLD = 0.40

# Smoothing: majority vote over last N predictions
# Prevents single-window noise from jerking the wheelchair
VOTE_WINDOW = 3

# SITL mode settings
MAX_SECONDS = 60
SITL_SUBJECT = 1

# Command output — will be sent to Node 2 over WiFi (placeholder for now)
# Format: {"cmd": "L", "conf": 0.85, "ts": 1234567890.123}
SEND_TO_NODE2 = False   # set True when WiFi link to Pi is ready


# ==============================================================================
# INFERENCE ENGINE
# ==============================================================================

class InferenceEngine:
    """
    Wraps the EEGNet model for real-time inference.

    On the Coral (hardware), this will be replaced with TFLite Edge TPU:
        interpreter = tflite.Interpreter(model_path, experimental_delegates=[...])
        interpreter.allocate_tensors()
        interpreter.set_tensor(input_idx, window)
        interpreter.invoke()
        output = interpreter.get_tensor(output_idx)

    For now, runs PyTorch on CPU/GPU. On a laptop with RTX 3060,
    inference takes <1ms per window — well within the 500ms budget.
    """

    def __init__(self, model_path, device=None):
        if device is None:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.device = device

        print(f"[MODEL] Loading: {model_path.name}")
        self.model = EEGNet()
        self.model.load_state_dict(
            torch.load(str(model_path), weights_only=True, map_location=device)
        )
        self.model.to(device)
        self.model.eval()

        total = sum(p.numel() for p in self.model.parameters())
        print(f"[MODEL] EEGNet loaded ({total:,} params) on {device}")

    @torch.no_grad()
    def predict(self, window):
        """
        Run inference on a single 1-second EEG window.

        Parameters
        ----------
        window : np.ndarray, shape (250, 8) — time × channels

        Returns
        -------
        command    : str — 'L', 'R', 'F', or 'S'
        confidence : float — softmax probability of the predicted class
        probs      : np.ndarray, shape (4,) — full probability distribution
        """
        # Reshape: (250, 8) -> (1, 1, 8, 250) — batch, image_ch, eeg_ch, time
        # Scale V -> uV: MNE raw returns volts (~1e-5), but MOABB training data
        # is in uV (~1-10 range). Must match training scale or BN kills the signal.
        x = window.T[np.newaxis, np.newaxis, :, :].astype(np.float32) * 1e6
        x_tensor = torch.from_numpy(x).to(self.device)

        logits = self.model(x_tensor)                    # (1, 4)
        probs  = F.softmax(logits, dim=1).cpu().numpy()[0]  # (4,)

        pred_idx   = int(np.argmax(probs))
        command    = CLASS_NAMES[pred_idx]
        confidence = float(probs[pred_idx])

        return command, confidence, probs


# ==============================================================================
# COMMAND SMOOTHER  (majority vote over recent predictions)
# ==============================================================================

class CommandSmoother:
    """
    Prevents single-window noise from jerking the wheelchair.

    Keeps a sliding window of the last N predictions and outputs
    the majority vote. If there's a tie, holds the previous command.

    Example with VOTE_WINDOW=3:
        predictions: [L, L, R] → output: L (2 vs 1)
        predictions: [L, R, R] → output: R (2 vs 1)
        predictions: [L, R, F] → output: hold previous (3-way tie)
    """

    def __init__(self, window_size=VOTE_WINDOW):
        self.window_size = window_size
        self.history = collections.deque(maxlen=window_size)
        self.last_command = "S"   # default to STOP until confident

    def update(self, command, confidence):
        """
        Add a new prediction. Returns the smoothed command.

        If confidence is below threshold, the prediction is ignored
        (treated as "no input" — wheelchair holds current state).
        """
        if confidence < CONFIDENCE_THRESHOLD:
            return self.last_command, "LOW_CONF"

        self.history.append(command)

        if len(self.history) < self.window_size:
            return self.last_command, "FILLING"

        # Count votes
        counts = {}
        for cmd in self.history:
            counts[cmd] = counts.get(cmd, 0) + 1

        # Find the winner
        max_count = max(counts.values())
        winners = [cmd for cmd, cnt in counts.items() if cnt == max_count]

        if len(winners) == 1:
            self.last_command = winners[0]
            return self.last_command, "VOTE"
        else:
            # Tie — hold previous command
            return self.last_command, "TIE"


# ==============================================================================
# INFERENCE THREAD
# ==============================================================================

def run_inference_thread(shared_state, stop_event, engine, smoother):
    """
    Wakes every 0.5 seconds, grabs the 1-second window from SharedState,
    runs EEGNet inference, and outputs the smoothed wheelchair command.
    """
    print("[INFER] Thread started — classifying every 0.5 seconds...")

    step   = 0
    t_next = time.perf_counter() + DSP_INTERVAL_S

    # Tracking stats
    total_correct  = 0
    total_inferred = 0
    cmd_counts     = {c: 0 for c in CLASS_NAMES}

    while not stop_event.is_set():
        remaining = t_next - time.perf_counter()
        if remaining > 0:
            time.sleep(min(remaining, 0.01))
            continue
        t_next += DSP_INTERVAL_S

        if not shared_state.is_ready:
            continue

        buf, true_label = shared_state.snapshot()
        if len(buf) < BUFFER_SIZE:
            continue

        # Convert buffer to numpy array: (250, 8)
        window = np.array(buf, dtype=np.float64)

        # ── EEGNet inference ──────────────────────────────────────────────
        t_start = time.perf_counter()
        raw_cmd, confidence, probs = engine.predict(window)
        t_infer = (time.perf_counter() - t_start) * 1000   # ms

        # ── Smoothing ─────────────────────────────────────────────────────
        smooth_cmd, vote_status = smoother.update(raw_cmd, confidence)
        cmd_counts[smooth_cmd] = cmd_counts.get(smooth_cmd, 0) + 1

        # ── Accuracy tracking (SITL only — has ground truth) ─────────────
        if true_label is not None:
            total_inferred += 1
            if smooth_cmd == true_label:
                total_correct += 1
        running_acc = (total_correct / total_inferred * 100
                       if total_inferred > 0 else 0.0)

        # ── Display ───────────────────────────────────────────────────────
        step += 1
        true_display = LABEL_DISPLAY.get(true_label, f"UNKNOWN ({true_label})")

        # Probability bars
        prob_bars = ""
        for i, cls in enumerate(CLASS_NAMES):
            bar_len = int(probs[i] * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            marker = " ◄" if cls == raw_cmd else "  "
            prob_bars += f"║  {cls}  {bar}  {probs[i]*100:5.1f}%{marker:<4s}          ║\n"

        # Command display with confidence indicator
        conf_bar = "●" * int(confidence * 10) + "○" * (10 - int(confidence * 10))
        conf_color = "HIGH" if confidence >= 0.6 else "MED " if confidence >= CONFIDENCE_THRESHOLD else "LOW "

        print()
        print(f"╔══════════════════════════════════════════════════════════════╗")
        print(f"║  INFERENCE #{step:04d}  │  {t_infer:.1f}ms  │  Acc: {running_acc:.1f}%  ({total_correct}/{total_inferred})    ║")
        print(f"╠══════════════════════════════════════════════════════════════╣")
        print(f"║  TRUE LABEL  : {true_display:<46s}║")
        print(f"╠══════════════════════════════════════════════════════════════╣")
        print(prob_bars, end="")
        print(f"╠══════════════════════════════════════════════════════════════╣")
        print(f"║  RAW PRED    : {raw_cmd}  ({confidence*100:.1f}%)  [{conf_color}] {conf_bar:<14s}    ║")
        print(f"║  SMOOTHED    : {smooth_cmd}  ({vote_status})                                     ║")
        print(f"╠══════════════════════════════════════════════════════════════╣")

        # Command → wheelchair action
        action_map = {
            "L": "◄◄  STEER LEFT",
            "R": "►►  STEER RIGHT",
            "F": "▲▲  DRIVE FORWARD",
            "S": "■■  STOP / IDLE",
        }
        action = action_map.get(smooth_cmd, "??  UNKNOWN")
        print(f"║  >>> WHEELCHAIR: {action:<42s}  ║")
        print(f"╚══════════════════════════════════════════════════════════════╝")

        # ── Send to Node 2 (placeholder) ──────────────────────────────────
        if SEND_TO_NODE2:
            packet = {
                "cmd":  smooth_cmd,
                "conf": round(confidence, 3),
                "ts":   time.time(),
            }
            # TODO: send packet to Raspberry Pi 5 over WiFi
            # socket.send(json.dumps(packet).encode())

    # ── Final stats ───────────────────────────────────────────────────────
    print(f"\n[INFER] Session complete.")
    print(f"[INFER] Total windows classified: {step}")
    print(f"[INFER] Running accuracy (on labeled windows): {running_acc:.1f}%")
    print(f"[INFER] Command distribution: {dict(cmd_counts)}")


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    logger = TeeLogger()
    # Rename log file to inference-specific name
    logger._file.write("MODE: REAL-TIME INFERENCE (SITL)\n\n")

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   NEURODRIVE — NODE 1 | REAL-TIME INFERENCE             ║")
    print("║   EEGNet + Smoothed Commands                                ║")
    print(f"║   Model: {MODEL_PATH.name:<51s}║")
    print(f"║   Confidence threshold: {CONFIDENCE_THRESHOLD*100:.0f}%  │  Vote window: {VOTE_WINDOW}             ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # ── 1. Load model ─────────────────────────────────────────────────────
    if not MODEL_PATH.exists():
        print(f"[ERROR] Model not found: {MODEL_PATH}")
        print(f"[ERROR] Run node1_training.py and node1_calibrate.py first.")
        logger.close()
        return

    engine   = InferenceEngine(MODEL_PATH)
    smoother = CommandSmoother(window_size=VOTE_WINDOW)

    # ── 2. Load EEG data (SITL) ──────────────────────────────────────────
    raw_array, events_list, fs = load_bci_data()
    max_samples = int(MAX_SECONDS * fs) if MAX_SECONDS else None
    if max_samples:
        print(f"[INIT] SITL mode: {MAX_SECONDS}s of subject {SITL_SUBJECT} data")

    # ── 3. Build DSP pipeline ─────────────────────────────────────────────
    print("[INIT] Building DSP filter chain...")
    notch_sos    = design_notch_filter(freq=50.0, Q=30.0, fs=fs)
    bp_sos       = design_bandpass_filter(low=8.0, high=30.0, order=4, fs=fs)
    filter_chain = FilterChain(notch_sos, bp_sos, N_CH)
    shared_state = SharedState(BUFFER_SIZE)
    stop_event   = threading.Event()

    print(f"[INIT] Channels: {CHANNELS}")
    print(f"[INIT] DSP: 50Hz notch → 8-30Hz bandpass → 1s window → EEGNet\n")

    # ── 4. Launch threads ─────────────────────────────────────────────────
    stream_thread = threading.Thread(
        target=run_stream_thread,
        args=(raw_array, events_list, filter_chain, shared_state,
              stop_event, max_samples),
        daemon=True,
        name="StreamThread",
    )

    infer_thread = threading.Thread(
        target=run_inference_thread,
        args=(shared_state, stop_event, engine, smoother),
        daemon=True,
        name="InferenceThread",
    )

    stream_thread.start()
    infer_thread.start()

    # ── 5. Wait for completion ────────────────────────────────────────────
    try:
        stream_thread.join()
    except KeyboardInterrupt:
        print("\n[MAIN] KeyboardInterrupt — shutting down...")
        stop_event.set()

    infer_thread.join(timeout=3.0)
    print("\n[MAIN] Inference pipeline complete.")
    logger.close()


if __name__ == "__main__":
    main()
