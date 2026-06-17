"""
================================================================================
NEURODRIVE — NODE 1 | OFFLINE / SITL PIPELINE
================================================================================
Purpose : Simulate the live 250 SPS EEG -> DSP pipeline using real human EEG
          data (BCI Competition IV-2a, Subject 1) without any hardware.

Paradigm (4-class motor imagery -> wheelchair commands):
    Left Hand  imagery  ->  'L'  (Steer Left)
    Right Hand imagery  ->  'R'  (Steer Right)
    Feet       imagery  ->  'F'  (Drive Forward)
    Tongue     imagery  ->  'S'  (Stop / Rest)

Architecture:
    [MOABB DataLoader] ──raw array──► [StreamThread]
                                            │ perf_counter busy-wait (4ms)
                                            │ FilterChain.process(sample)
                                            ▼
                                      [SharedState]  ← rolling deque (250)
                                            │
                                      [DSPThread]    ← wakes every 0.5s
                                            │ compute variance (power proxy)
                                            ▼
                                      Terminal print + log file (TeeLogger)

HARDWARE SWAP POINTS (marked with *** SWAP ***):
    - StreamThread: replace stream_generator() with spidev read loop
    - DSPThread:    replace variance block with TFLite Edge TPU inference

Dependencies (install once):
    pip install moabb mne numpy scipy

Run:
    python node1_sitl_pipeline.py

Press Ctrl+C to stop early.
================================================================================
"""

import time
import threading
import collections
import copy
import sys
import os
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.signal import iirnotch, butter, sosfilt, sosfilt_zi, tf2sos

# Suppress verbose MNE/MOABB console spam before importing them
import mne
mne.set_log_level("WARNING")

try:
    import moabb
    moabb.set_log_level("WARNING")
except Exception:
    pass  # older MOABB versions don't have this

from moabb.datasets import BNCI2014_001


# ==============================================================================
# TEE LOGGER  — mirrors all print() output to terminal AND a .txt file
# ==============================================================================

# Folder where run logs are saved (created automatically if missing)
LOG_DIR = Path(__file__).parent / "logs"


class TeeLogger:
    """
    Replaces sys.stdout so every print() call writes to both:
        - The original terminal (so you still see output live)
        - A timestamped .txt log file on disk

    Usage:
        logger = TeeLogger()        # starts capturing
        ...                         # all print() calls are mirrored
        logger.close()              # flushes and closes the file

    The log file is named:
        logs/sitl_run_YYYYMMDD_HHMMSS.txt

    Thread-safe: uses a Lock so concurrent print() calls from StreamThread
    and DSPThread don't interleave partial lines in the file.
    """

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path  = LOG_DIR / f"sitl_run_{timestamp}.txt"
        self._terminal = sys.stdout                    # keep original stdout
        self._file     = open(self.log_path, "w", encoding="utf-8", buffering=1)
        self._lock     = threading.Lock()
        sys.stdout     = self                          # redirect all print()
        # Write a header so the log file is self-describing
        self._file.write(f"NEURODRIVE — NODE 1 SITL RUN\n")
        self._file.write(f"Started : {datetime.now().isoformat()}\n")
        self._file.write("=" * 70 + "\n\n")
        self._terminal.write(f"[LOG] Saving output to: {self.log_path}\n")

    def write(self, message):
        with self._lock:
            self._terminal.write(message)   # echo to terminal
            self._file.write(message)       # mirror to file

    def flush(self):
        self._terminal.flush()
        self._file.flush()

    def close(self):
        sys.stdout = self._terminal         # restore original stdout
        self._file.write(f"\n\nEnded : {datetime.now().isoformat()}\n")
        self._file.close()
        self._terminal.write(f"[LOG] Log saved -> {self.log_path}\n")


# ==============================================================================
# CONFIGURATION CONSTANTS
# ==============================================================================

FS              = 250          # Target sample rate (Hz) — matches ADS1299 config
BUFFER_SECONDS  = 1            # Rolling buffer duration (seconds)
BUFFER_SIZE     = FS * BUFFER_SECONDS   # 250 samples = 1 second window
CHANNELS        = ["FC3", "FC4", "C3", "Cz", "C4", "CP3", "CP4", "FCz"]  # 8ch ADS1299
N_CH            = len(CHANNELS)
DSP_INTERVAL_S  = 0.5          # DSP thread fires every 500ms (overlapping windows)
SAMPLE_INTERVAL = 1.0 / FS     # 0.004 s = 4 ms per sample
TRIAL_SECONDS   = 4.0          # BCI-IV-2a imagery window duration (seconds)
TRIAL_SAMPLES   = int(TRIAL_SECONDS * FS)  # 1000 samples per trial

# Limit simulation to this many seconds (set to None for full dataset ~14 min)
MAX_SECONDS     = 60           # Run for 60 seconds then stop

# BCI-IV-2a class -> wheelchair command mapping.
# Handles all ID formats MOABB/MNE might produce (int, string, numeric-string).
CLASS_MAP = {
    # MOABB internal integer IDs
    1: "L",  2: "R",  3: "F",  4: "S",
    # MNE annotation descriptions (MOABB >= 0.4 style)
    "left_hand": "L",  "right_hand": "R",  "feet": "F",  "tongue": "S",
    # Raw GDF event codes (older MOABB / direct MNE GDF reader)
    "769": "L",  "770": "R",  "771": "F",  "772": "S",
    # Fallback: numeric string versions of internal IDs
    "1": "L",  "2": "R",  "3": "F",  "4": "S",
}

LABEL_DISPLAY = {
    "L": "LEFT     (← Steer Left)",
    "R": "RIGHT    (-> Steer Right)",
    "F": "FORWARD  (↑ Drive Fwd)",
    "S": "STOP     (■ Rest/Stop)",
    None: "IDLE     (· Between trials)",
}


# ==============================================================================
# SECTION 1 — DATA LOADER
# ==============================================================================

def load_bci_data():
    """
    Download (first run only) and load Subject 1 from BCI Competition IV-2a
    using MOABB. Concatenates all training runs into one continuous array.

    Returns
    -------
    raw_array   : np.ndarray, shape (n_samples, 8), dtype float64
                  Columns correspond to the 8 channels in CHANNELS, in order.
                  Units: volts (as returned by MNE from the GDF file).
    events_list : list of (int, str) tuples — (sample_idx, label_char)
                  Each tuple marks the ONSET of a 4-second imagery trial.
    fs          : float — actual sample rate after optional resampling
    """
    print("[DATA] Loading BCI Competition IV-2a | Subject 1 via MOABB...")
    print("[DATA] (First run will download ~5MB — subsequent runs use cache)")

    dataset = BNCI2014_001()
    subject_data = dataset.get_data(subjects=[1])

    # MOABB structure: subject_data[subject_id][session_key][run_key] = mne.Raw
    session_key = list(subject_data[1].keys())[0]
    session     = subject_data[1][session_key]
    print(f"[DATA] Session key: '{session_key}' | Runs: {sorted(session.keys())}")

    # Concatenate all runs from this session into one continuous MNE Raw object
    runs = [session[k] for k in sorted(session.keys())]
    raw  = mne.concatenate_raws(runs)
    print(f"[DATA] Concatenated {len(runs)} runs -> {raw.n_times} total samples "
          f"@ {raw.info['sfreq']} Hz")

    # Verify our target channels exist in this dataset
    missing = [ch for ch in CHANNELS if ch not in raw.ch_names]
    if missing:
        raise RuntimeError(
            f"Channels {missing} not found. Available: {raw.ch_names}"
        )
    raw.pick_channels(CHANNELS)   # keep only the 8 motor-cortex channels

    # Resample only if the dataset SR differs from our target (it shouldn't for IV-2a)
    actual_fs = raw.info["sfreq"]
    if actual_fs != FS:
        print(f"[DATA] Resampling {actual_fs:.1f} Hz -> {FS} Hz ...")
        raw.resample(FS)

    # Extract the raw numpy array: MNE gives (n_channels, n_samples) -> transpose
    raw_array = raw.get_data().T       # shape: (n_samples, 8)

    # ---- Build events list from MNE annotations ----
    try:
        events, event_id_map = mne.events_from_annotations(raw)
        # event_id_map: {"annotation_str": numeric_id, ...}
        # Invert it so we can look up by numeric_id -> annotation_str
        id_to_ann = {v: k for k, v in event_id_map.items()}
        print(f"[DATA] Annotation map: {event_id_map}")
    except Exception as exc:
        print(f"[DATA] Warning: mne.events_from_annotations failed ({exc})")
        events       = np.empty((0, 3), dtype=int)
        id_to_ann    = {}

    # Map every event to one of our wheelchair labels
    events_list = []
    unknown_ids = set()
    for sample_idx, _, ev_id in events:
        ann_str = id_to_ann.get(ev_id, str(ev_id))
        # Try annotation string first, then raw integer, then numeric string
        label = (CLASS_MAP.get(ann_str)
                 or CLASS_MAP.get(ev_id)
                 or CLASS_MAP.get(str(ev_id)))
        if label is not None:
            events_list.append((int(sample_idx), label))
        else:
            unknown_ids.add(ann_str)

    if unknown_ids:
        print(f"[DATA] Ignored unknown event types: {unknown_ids}")

    dist = {lbl: sum(1 for _, l in events_list if l == lbl) for lbl in "LRFS"}
    print(f"[DATA] Loaded {len(raw_array):,} samples | {len(events_list)} events | "
          f"Distribution: {dist}")

    return raw_array, events_list, float(FS)


# ==============================================================================
# SECTION 2 — DSP FILTER DESIGN  (hardware-agnostic SOS coefficients)
# ==============================================================================

def design_notch_filter(freq=50.0, Q=30.0, fs=250.0):
    """
    Design a second-order IIR notch filter.
    Removes the 50 Hz power-line interference from European mains supply.
    Q=30 gives a narrow notch (~1.7 Hz bandwidth) — minimal signal distortion.

    Returns SOS (second-order sections) format for numerical stability.
    """
    b, a  = iirnotch(freq, Q, fs)
    sos   = tf2sos(b, a)           # convert (b, a) -> SOS for stable filtering
    return sos


def design_bandpass_filter(low=8.0, high=30.0, order=4, fs=250.0):
    """
    Design a Butterworth bandpass filter: 8–30 Hz.
    This is the mu/beta band — the frequency range that shows Event-Related
    Desynchronization (ERD) during motor imagery.

    Order 4 gives -80 dB/decade roll-off while remaining stable for real-time
    single-sample processing (important for the hardware port).

    Returns SOS format.
    """
    sos = butter(order, [low, high], btype="bandpass", fs=fs, output="sos")
    return sos


# ==============================================================================
# SECTION 3 — FILTER CHAIN  (stateful, multi-channel, sample-by-sample)
# ==============================================================================

class FilterChain:
    """
    Stateful multi-channel DSP filter chain.

    Processes one sample at a time through:  Notch (50 Hz) -> Bandpass (8-30 Hz)

    Maintains filter state (zi) between calls so the filter memory is
    preserved across samples — exactly what the real hardware loop does.

    *** SWAP NOTE ***
    This class is the boundary between data acquisition and signal processing.
    On Node 1 (Coral), the stream_generator() is replaced by spidev reads,
    but FilterChain.process() is called identically.
    """

    def __init__(self, notch_sos, bp_sos, n_channels):
        self.notch_sos = notch_sos
        self.bp_sos    = bp_sos
        self.n_ch      = n_channels

        # sosfilt_zi() computes the steady-state initial conditions for a
        # step input, giving us a "warm" filter from sample 1 (no startup ringing)
        notch_zi_base = sosfilt_zi(notch_sos)   # shape: (n_sections, 2)
        bp_zi_base    = sosfilt_zi(bp_sos)       # shape: (n_sections, 2)

        # Initialize filter state with zeros, NOT sosfilt_zi().
        #
        # sosfilt_zi() computes steady-state conditions for a unit-step (1.0 V)
        # input. EEG signals are ~25 µV = 2.5e-5 V — a 20,000x mismatch. Using
        # sosfilt_zi() causes a massive initial transient that corrupts the first
        # DSP window. Zero-initialization gives a cold-start with a brief ~0.2s
        # transient, which is fully settled before the first window fires (we wait
        # 1 second for the buffer to fill before any DSP runs).
        self.notch_zi = [np.zeros_like(notch_zi_base) for _ in range(n_channels)]
        self.bp_zi    = [np.zeros_like(bp_zi_base)    for _ in range(n_channels)]

    def process(self, sample):
        """
        Filter one sample through the full chain.

        Parameters
        ----------
        sample : np.ndarray, shape (n_channels,)
            Raw ADC values from one timestep (from MOABB or spidev — identical interface).

        Returns
        -------
        filtered : np.ndarray, shape (n_channels,)
            8-30 Hz bandpass filtered signal with 50 Hz notch applied.
        """
        filtered = np.empty(self.n_ch, dtype=np.float64)

        for i in range(self.n_ch):
            # sosfilt requires a 1D array, even for a single sample
            x = np.array([sample[i]], dtype=np.float64)

            # Stage 1: Notch — kills 50 Hz power line hum
            x, self.notch_zi[i] = sosfilt(self.notch_sos, x, zi=self.notch_zi[i])

            # Stage 2: Bandpass — isolates 8-30 Hz motor imagery band
            x, self.bp_zi[i]    = sosfilt(self.bp_sos,    x, zi=self.bp_zi[i])

            filtered[i] = x[0]

        return filtered


# ==============================================================================
# SECTION 4 — BASELINE ESTIMATOR  (per-channel ERD normalization)
# ==============================================================================

# Minimum rest windows required before ERD output is trusted.
# BCI-IV-2a trials start at ~2s, leaving only ~4 true IDLE windows in a
# 60s run. Set to 3 so baseline fires reliably without waiting for data
# that doesn't exist in this time window.
BASELINE_MIN_WINDOWS = 3

# EMA smoothing factor for baseline updates (0 < alpha < 1).
# Lower = slower to update (more stable baseline).
# 0.15 means each new rest window contributes ~15% to the running average.
BASELINE_ALPHA = 0.15

# %ERD threshold to call a channel "suppressed" — avoids noise triggering the heuristic
ERD_SUPPRESSION_THRESHOLD = 10.0   # percent


class BaselineEstimator:
    """
    Tracks each channel's resting-state mu/beta power and converts
    absolute power into Event-Related Desynchronization (ERD) percentage.

    ERD formula (standard in BCI literature):
        %ERD = (P_baseline - P_active) / P_baseline × 100

    Interpretation:
        Positive %ERD  ->  power DROPPED vs baseline  ->  motor cortex active (imagery)
        Negative %ERD  ->  power ROSE vs baseline     ->  no imagery / ERS event
        ~0%            ->  same as rest               ->  idle

    The baseline is a per-channel Exponential Moving Average (EMA) updated
    ONLY during rest/idle windows. This lets it track slow drift (electrode
    impedance change, fatigue) without being corrupted by imagery windows.
    """

    def __init__(self, n_channels, alpha=BASELINE_ALPHA,
                 min_windows=BASELINE_MIN_WINDOWS):
        self.n_ch        = n_channels
        self.alpha       = alpha
        self.min_windows = min_windows

        self._baseline   = np.zeros(n_channels)   # EMA baseline in µV²
        self._n_rest     = 0                       # rest windows fed so far
        self.is_ready    = False                   # True once min_windows reached

    def update(self, power_uV2):
        """
        Feed a rest/idle window's power into the EMA baseline.
        Call this ONLY during IDLE or STOP labeled windows.

        Parameters
        ----------
        power_uV2 : np.ndarray, shape (n_channels,)
        """
        if self._n_rest == 0:
            # Cold start: initialise directly from first rest window
            self._baseline = power_uV2.copy()
        else:
            # EMA update: new_baseline = alpha * new + (1-alpha) * old
            self._baseline = (self.alpha * power_uV2
                              + (1.0 - self.alpha) * self._baseline)
        self._n_rest += 1
        if not self.is_ready and self._n_rest >= self.min_windows:
            self.is_ready = True
            print(f"[DSP]    Baseline established after {self._n_rest} rest windows.")

    def erd(self, power_uV2):
        """
        Compute %ERD for each channel relative to the current baseline.

        Returns
        -------
        erd_pct : np.ndarray, shape (n_channels,)
            Positive = suppression vs baseline (motor imagery active).
        """
        # Protect against divide-by-zero if baseline hasn't warmed up
        safe_baseline = np.where(self._baseline > 0, self._baseline, 1e-30)
        return (safe_baseline - power_uV2) / safe_baseline * 100.0

    @property
    def baseline(self):
        return self._baseline.copy()

    @property
    def windows_collected(self):
        return self._n_rest


# ==============================================================================
# SECTION 6 — SHARED STATE  (thread-safe rolling buffer)
# ==============================================================================

class SharedState:
    """
    Thread-safe container shared between the StreamThread and DSPThread.

    Holds:
        _buffer        : deque of filtered samples, maxlen = BUFFER_SIZE (250)
        _current_label : the wheelchair command active at this moment ('L/R/F/S'/None)
    """

    def __init__(self, buffer_size):
        self._lock         = threading.Lock()
        self._buffer       = collections.deque(maxlen=buffer_size)
        self._current_label = None

    def push(self, filtered_sample, label):
        """Called by StreamThread: append one filtered sample to the deque."""
        with self._lock:
            self._buffer.append(filtered_sample.copy())
            if label is not None:
                self._current_label = label

    def snapshot(self):
        """
        Called by DSPThread: return a consistent (buffer_copy, label) pair.
        Makes a full copy inside the lock to avoid race conditions.
        """
        with self._lock:
            buf   = list(self._buffer)   # copy the deque
            label = self._current_label
        return buf, label

    @property
    def is_ready(self):
        """True once the buffer has been filled for the first time (1 second of data)."""
        with self._lock:
            return len(self._buffer) == self._buffer.maxlen


# ==============================================================================
# SECTION 5 — STREAM GENERATOR  (live hardware simulator)
# ==============================================================================

def stream_generator(raw_array, events_list, max_samples=None):
    """
    Generator that replays the EEG array at exactly 250 SPS.

    Uses perf_counter() busy-wait instead of time.sleep() because on Windows,
    time.sleep(0.004) actually sleeps for ~15.6 ms (OS timer resolution limit).
    perf_counter() is a hardware timestamp counter — it is accurate to ~100 ns.

    NOTE: The busy-wait uses a hybrid approach:
        - Sleep for (interval - 2ms) to yield the CPU to other threads
        - Busy-spin for the final 2ms for precise timing
    This keeps CPU usage at ~15-20% instead of 100% full-spin.

    *** SWAP NOTE ***
    On the Coral, REPLACE THIS ENTIRE FUNCTION with:

        while True:
            reading  = backend.read()          # spidev call
            sample   = np.array(reading.channels())[channel_indices]
            label    = None                    # no ground truth on live hardware
            yield sample, label

    Everything else (FilterChain, SharedState, DSPThread) stays IDENTICAL.

    Parameters
    ----------
    raw_array   : np.ndarray, shape (n_samples, n_channels)
    events_list : list of (sample_idx, label_char) tuples
    max_samples : int or None — stop after this many samples (None = full dataset)

    Yields
    ------
    (sample, label) : (np.ndarray shape (n_channels,), str or None)
    """
    # Build O(1) lookup: sample_index -> label
    event_lookup = dict(events_list)

    n_samples   = len(raw_array) if max_samples is None else min(len(raw_array), max_samples)
    cur_label   = None
    label_expiry = -1    # sample index when the current trial ends

    t_next = time.perf_counter()

    for i in range(n_samples):
        # ---- Hybrid busy-wait for 4 ms precision on Windows ----
        remaining = t_next - time.perf_counter()
        if remaining > 0.002:
            time.sleep(remaining - 0.002)   # yield CPU for most of the interval
        while time.perf_counter() < t_next:
            pass                            # spin for final ~2ms precision
        t_next += SAMPLE_INTERVAL

        # ---- Label tracking: carry label forward for the trial window ----
        if i in event_lookup:
            cur_label    = event_lookup[i]
            label_expiry = i + TRIAL_SAMPLES   # label active for 4 seconds
        elif i > label_expiry:
            cur_label = None                   # between trials -> idle

        yield raw_array[i], cur_label


# ==============================================================================
# SECTION 6 — STREAM THREAD  (hardware interface layer)
# ==============================================================================

def run_stream_thread(raw_array, events_list, filter_chain, shared_state,
                      stop_event, max_samples=None):
    """
    Runs the stream generator, applies filters sample-by-sample,
    and pushes results into the shared rolling buffer.

    This thread is the HARDWARE INTERFACE LAYER.
    On the Coral: replace stream_generator() with spidev reads; keep everything else.
    """
    print("[STREAM] Thread started — simulating 250 SPS stream...")

    sample_count = 0
    for sample, label in stream_generator(raw_array, events_list, max_samples):
        if stop_event.is_set():
            break

        # Apply DSP filters (stateful: state carries over between samples)
        filtered = filter_chain.process(sample)

        # Push the filtered sample and current trial label into the shared buffer
        shared_state.push(filtered, label)
        sample_count += 1

    elapsed_s = sample_count / FS
    print(f"[STREAM] Thread finished — {sample_count:,} samples ({elapsed_s:.1f}s simulated)")
    stop_event.set()   # signal DSP thread to exit


# ==============================================================================
# SECTION 7 — DSP THREAD  (inference window processor)
# ==============================================================================

def run_dsp_thread(shared_state, stop_event):
    """
    Wakes every 0.5 seconds and processes the 1-second rolling window.

    Pipeline inside this function:
        1. Compute 8-30 Hz band power (variance) per channel  [µV²]
        2. Feed IDLE/STOP windows into the BaselineEstimator (EMA)
        3. Once baseline is ready: compute %ERD per channel
        4. Use %ERD to drive a baseline-normalised heuristic

    *** SWAP NOTE ***
    Replace the ERD block below with your TFLite inference:

        input_tensor = window.T.reshape(...)   # shape to match model input
        interpreter.set_tensor(input_idx, input_tensor)
        interpreter.invoke()
        prediction = interpreter.get_tensor(output_idx)
        command    = ['L', 'R', 'F', 'S'][np.argmax(prediction)]
    """
    print("[DSP]    Thread started — processing every 0.5 seconds...")

    baseline = BaselineEstimator(n_channels=N_CH)
    step     = 0
    t_next   = time.perf_counter() + DSP_INTERVAL_S

    while not stop_event.is_set():
        remaining = t_next - time.perf_counter()
        if remaining > 0:
            time.sleep(min(remaining, 0.01))
            continue
        t_next += DSP_INTERVAL_S

        if not shared_state.is_ready:
            print("[DSP]    Waiting for buffer to fill (need 1 second of data)...")
            continue

        buf, true_label = shared_state.snapshot()
        if len(buf) < BUFFER_SIZE:
            continue

        # Convert list of (n_channels,) arrays -> matrix (250, 3)
        window = np.array(buf, dtype=np.float64)

        # ==================================================================
        # *** SWAP *** — Replace everything below with TFLite inference
        # ==================================================================

        # --- Step 1: Raw power in µV² ---
        # Variance ≈ power because bandpass filter removes DC (mean ≈ 0)
        power_V2  = np.var(window, axis=0)    # (3,) in V²
        power_uV2 = power_V2 * 1e12           # (3,) in µV²

        # --- Step 2: Baseline update (true idle windows only) ---
        # Only update during IDLE (None = between trials).
        # "S" = Tongue imagery — still an active motor task, NOT rest.
        # Including it would corrupt the baseline with motor ERD patterns.
        is_rest = true_label is None
        if is_rest:
            baseline.update(power_uV2)

        # --- Step 3: ERD computation ---
        # Only compute ERD once baseline is established
        if baseline.is_ready:
            erd = baseline.erd(power_uV2)    # (3,) in %ERD, positive = suppressed
        else:
            erd = np.full(N_CH, np.nan)

        # --- Step 4: ERD-based heuristic ---
        # Find the channel with the highest ERD (most suppressed vs baseline).
        # Only call "suppressed" if it clears the noise threshold.
        if baseline.is_ready and np.nanmax(erd) >= ERD_SUPPRESSION_THRESHOLD:
            max_erd_idx = int(np.nanargmax(erd))
            erd_heuristic_map = {
                0: ("C3 ERD -> Right Hand?  (R)", "R"),
                1: ("Cz ERD -> Feet?        (F)", "F"),
                2: ("C4 ERD -> Left Hand?   (L)", "L"),
            }
            heuristic_text, heuristic_cmd = erd_heuristic_map[max_erd_idx]
        else:
            max_erd_idx     = -1
            heuristic_text  = "Below threshold  -> IDLE / STOP (S)"
            heuristic_cmd   = "S"

        # ==================================================================
        # END SWAP ZONE
        # ==================================================================

        step += 1
        true_display     = LABEL_DISPLAY.get(true_label, f"UNKNOWN ({true_label})")
        baseline_display = (f"{baseline.windows_collected} windows"
                            if baseline.is_ready
                            else f"collecting... ({baseline.windows_collected}/{BASELINE_MIN_WINDOWS})")

        def erd_bar(pct):
            """Render a compact ASCII bar for %ERD  (-100 to +100)."""
            if np.isnan(pct):
                return "  [  ---  ]  "
            filled = int(abs(pct) / 100 * 8)
            filled = min(filled, 8)
            bar    = ("█" * filled).ljust(8)
            sign   = "+" if pct >= 0 else "-"
            return f"  [{sign}{bar}]  "

        print()
        print(f"╔══════════════════════════════════════════════════════════════╗")
        print(f"║  DSP WINDOW #{step:04d}  │  Baseline: {baseline_display:<26s}║")
        print(f"╠══════════════════════════════════════════════════════════════╣")
        print(f"║  TRUE LABEL  : {true_display:<46s}║")
        print(f"╠══════════════════════════════════════════════════════════════╣")
        print(f"║  Channel      │  Power (µV²) │  %ERD vs baseline │  Bar      ║")
        print(f"║  ─────────────┼──────────────┼───────────────────┼────────── ║")

        ch_labels = ["C3 (L-hemi)", "Cz (foot) ", "C4 (R-hemi)"]
        for i, ch in enumerate(ch_labels):
            erd_val  = erd[i]
            erd_str  = f"{erd_val:>+7.1f}%" if not np.isnan(erd_val) else "  ---   "
            peak_mrk = " ◄ MAX ERD" if i == max_erd_idx else "          "
            bar      = erd_bar(erd_val)
            print(f"║  {ch} │ {power_uV2[i]:>10.2f}   │  {erd_str}          │{bar}{peak_mrk}║")

        print(f"╠══════════════════════════════════════════════════════════════╣")
        print(f"║  HEURISTIC   : {heuristic_text:<46s}║")
        print(f"╚══════════════════════════════════════════════════════════════╝")

    print("[DSP]    Thread stopped.")


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    # Start the tee logger FIRST — everything printed after this line
    # goes to both the terminal and logs/sitl_run_<timestamp>.txt
    logger = TeeLogger()

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   NEURODRIVE — NODE 1 SITL PIPELINE                     ║")
    print("║   Offline Mode | BCI-IV-2a Dataset | Subject 1              ║")
    print(f"║   Simulating {MAX_SECONDS}s of data at {FS} SPS                          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # ---- 1. Load EEG data from MOABB ----
    raw_array, events_list, fs = load_bci_data()

    max_samples = int(MAX_SECONDS * fs) if MAX_SECONDS is not None else None
    if max_samples is not None:
        print(f"\n[INIT] Limiting simulation to {MAX_SECONDS}s "
              f"({max_samples:,} samples)")

    # ---- 2. Design DSP filters ----
    print("\n[INIT] Designing DSP filter chain...")
    notch_sos = design_notch_filter(freq=50.0, Q=30.0, fs=fs)
    bp_sos    = design_bandpass_filter(low=8.0, high=30.0, order=4, fs=fs)
    print(f"[INIT]   Notch    : 50 Hz, Q=30   | {len(notch_sos)} SOS section(s)")
    print(f"[INIT]   Bandpass : 8–30 Hz, ord=4 | {len(bp_sos)} SOS section(s)")

    # ---- 3. Build pipeline components ----
    filter_chain = FilterChain(notch_sos, bp_sos, N_CH)
    shared_state = SharedState(BUFFER_SIZE)
    stop_event   = threading.Event()

    # ---- 4. Launch threads ----
    print("\n[INIT] Launching pipeline threads...\n")

    stream_thread = threading.Thread(
        target=run_stream_thread,
        args=(raw_array, events_list, filter_chain, shared_state,
              stop_event, max_samples),
        daemon=True,
        name="StreamThread",
    )

    dsp_thread = threading.Thread(
        target=run_dsp_thread,
        args=(shared_state, stop_event),
        daemon=True,
        name="DSPThread",
    )

    stream_thread.start()
    dsp_thread.start()

    # ---- 5. Block main thread until done or interrupted ----
    try:
        stream_thread.join()
    except KeyboardInterrupt:
        print("\n[MAIN] KeyboardInterrupt — shutting down...")
        stop_event.set()

    dsp_thread.join(timeout=3.0)
    print("\n[MAIN] SITL pipeline complete.")

    # Close the logger last — writes the end timestamp and restores stdout
    logger.close()


if __name__ == "__main__":
    main()
