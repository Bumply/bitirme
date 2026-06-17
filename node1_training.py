"""
================================================================================
NEURODRIVE — NODE 1 | EEGNET TRAINING SCRIPT  (PyTorch + CUDA)
================================================================================
Purpose : Train EEGNet on BCI Competition IV-2a (subjects 1-8), test on
          subject 9 (never seen), then export to ONNX + int8 TFLite for Edge TPU.

3-Phase strategy:
    PHASE 1 — Pre-train (this script)
        Train on 8 subjects from BCI-IV-2a.
        Produces a "generic human brain" model (~60-70% cross-subject accuracy).

    PHASE 2 — Personal calibration (finetune() function below)
        Record ~10 min of your own EEG, call finetune().
        Freezes early conv layers, updates only the last block + head.
        Target: ~75-85% personal accuracy.

    PHASE 3 — Online adaptation (runs on Coral during wheelchair use)
        High-confidence pseudo-labels accumulate in a buffer.
        Periodic micro fine-tune keeps the model tracking daily brain drift.
        (Implemented in node1_inference.py — built later.)

Export pipeline:
    PyTorch .pt  →  ONNX .onnx  →  float32 .tflite  →  int8 .tflite
    →  edgetpu_compiler  →  _edgetpu.tflite
    (last step requires edgetpu_compiler on Linux/Coral, not Python)

Dependencies:
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
    pip install moabb mne numpy scipy scikit-learn matplotlib onnx onnx2tf
    pip install tensorflow-cpu   (for TFLite conversion only — no GPU needed)

================================================================================
"""

import os
from pathlib import Path
from datetime import datetime
import copy

import numpy as np
from scipy.signal import iirnotch, filtfilt
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import confusion_matrix, classification_report

import mne
mne.set_log_level("WARNING")

try:
    import moabb
    moabb.set_log_level("WARNING")
except Exception:
    pass

from moabb.datasets import BNCI2014_001
from moabb.paradigms import MotorImagery

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import TensorDataset, DataLoader


# ==============================================================================
# GPU CONFIGURATION
# ==============================================================================

def configure_gpu():
    """
    Detect and configure the best available device (CUDA GPU or CPU).

    PyTorch CUDA works natively on Windows — unlike TensorFlow 2.11+ which
    dropped Windows GPU support entirely. The RTX 3060 Laptop GPU has:
      - 3840 CUDA cores
      - 30 RT cores, 120 Tensor Cores (Ampere)
      - 6 GB GDDR6 VRAM

    Mixed precision (torch.amp) uses float16 on Tensor Cores for ~2x speedup
    with float32 master weights for numerical stability.

    Returns
    -------
    device : torch.device
    """
    if torch.cuda.is_available():
        device = torch.device("cuda")
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb  = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"[GPU] {gpu_name}  ({vram_gb:.1f} GB VRAM)")
        print(f"[GPU] CUDA {torch.version.cuda}  |  PyTorch {torch.__version__}")
        print(f"[GPU] Mixed precision (float16 Tensor Cores) enabled via torch.amp")
    else:
        device = torch.device("cpu")
        print("[GPU] No CUDA GPU found — training on CPU (this will be slow)")
    return device


# ==============================================================================
# CONFIGURATION
# ==============================================================================

MODELS_DIR = Path(__file__).parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

# ── Data ──
ALL_SUBJECTS   = list(range(1, 10))          # 9 subjects in BCI-IV-2a
TEST_SUBJECT   = 9                           # held out — never seen in training
TRAIN_SUBJECTS = [s for s in ALL_SUBJECTS if s != TEST_SUBJECT]
CHANNELS       = ["C3", "Cz", "C4", "CPz"]   # 4-ch ADS1299-4 hat (adjust to board wiring)
N_CH           = len(CHANNELS)   # 4 — matches ADS1299-4 hardware
FS             = 250                         # Hz — matches ADS1299 config
TMIN           = 0.5   # skip first 0.5s of each trial (visual evoked potential
                       # from cue arrow appears here — we don't want to learn it)
TMAX           = 4.0   # end of trial
WINDOW_SEC     = 1.0   # inference window length — must match SITL pipeline
WINDOW_SAMPLES = int(WINDOW_SEC * FS)        # 250 samples
WINDOW_STRIDE  = int(0.5 * FS)              # 50% overlap = 125 samples

# Label mapping — identical to SITL pipeline
CLASS_NAMES = ["F", "L", "R", "S"]          # sorted alphabetically for LabelEncoder
# LOCK: must stay alphabetical — LabelEncoder maps indices in sorted order, and
# node1_coral.py relies on this exact order to decode model outputs into commands.
assert CLASS_NAMES == sorted(CLASS_NAMES), "CLASS_NAMES must stay alphabetical (F,L,R,S)"
EVENT_MAP   = {
    "left_hand":  "L",
    "right_hand": "R",
    "feet":       "F",
    "tongue":     "S",
}
N_CLASSES = len(CLASS_NAMES)

# ── EEGNet architecture ──
F1        = 8    # temporal filters (learned frequency banks)
D         = 2    # depth multiplier for depthwise (spatial filters per F1)
F2        = 16   # separable conv output filters
DROPOUT   = 0.5  # higher dropout → better generalization across subjects
KERN_TEMP = 64   # temporal kernel size (~256ms at 250Hz — covers mu/beta cycles)

# ── Training ──
BATCH_SIZE = 64   # smaller batches → better generalization on small EEG datasets
EPOCHS     = 200
LR         = 0.001
PATIENCE   = 25   # early stopping patience (epochs without val_acc improvement)


# ==============================================================================
# SECTION 1 — DATA LOADING
# ==============================================================================

def load_and_epoch(subjects):
    """
    Load BCI Competition IV-2a via MOABB for specified subjects.
    MOABB handles: download, caching, MNE parsing, channel selection,
    resampling to 250 Hz, and bandpass filtering (8-30 Hz).

    Returns
    -------
    X : np.ndarray, shape (n_trials, n_channels, n_timepoints)
        n_timepoints = (TMAX - TMIN) * FS = 3.5 * 250 = 875 samples
    y : np.ndarray of str, shape (n_trials,)
        Labels in ['L', 'R', 'F', 'S']
    """
    print(f"[DATA] Loading subjects: {subjects} ...")

    dataset  = BNCI2014_001()
    paradigm = MotorImagery(
        events    = list(EVENT_MAP.keys()),
        n_classes = N_CLASSES,
        fmin      = 8.0,    # bandpass lower edge (mu band start)
        fmax      = 30.0,   # bandpass upper edge (beta band end)
        tmin      = TMIN,
        tmax      = TMAX,
        channels  = CHANNELS,
        resample  = float(FS),
    )

    X, y_raw, metadata = paradigm.get_data(
        dataset  = dataset,
        subjects = subjects,
    )
    # y_raw contains the string event names from the dataset
    y = np.array([EVENT_MAP[lbl] for lbl in y_raw])

    dist = {c: int((y == c).sum()) for c in CLASS_NAMES}
    print(f"[DATA] Shape: {X.shape} | Labels: {dist}")
    return X, y


# ==============================================================================
# SECTION 2 — PREPROCESSING
# ==============================================================================

def apply_notch(X, freq=50.0, Q=30.0, fs=250.0):
    """
    Apply 50 Hz notch filter to remove European mains interference.
    Uses filtfilt (zero-phase, forward+backward) since we have the full
    epoch offline — this gives cleaner edges than causal sosfilt.

    X shape: (n_trials, n_channels, n_timepoints)
    """
    b, a  = iirnotch(freq, Q, fs)
    return filtfilt(b, a, X, axis=-1)


def segment(X, y, window=WINDOW_SAMPLES, stride=WINDOW_STRIDE):
    """
    Slice each trial into overlapping 1-second windows.

    Each window inherits the label of its parent trial (label is constant
    for the entire 4-second imagery period).

    Returns
    -------
    X_seg : (n_windows, n_channels, window_samples)
    y_seg : (n_windows,) — same label as parent trial
    """
    n_trials, n_ch, n_tp = X.shape
    xs, ys = [], []

    for i in range(n_trials):
        start = 0
        while start + window <= n_tp:
            xs.append(X[i, :, start : start + window])
            ys.append(y[i])
            start += stride

    return np.array(xs, dtype=np.float32), np.array(ys)


def encode_labels(y, le=None):
    """
    Convert char labels ['L','R','F','S'] → integer indices.

    Returns
    -------
    y_int : np.ndarray of int, shape (n_samples,)
    le    : fitted LabelEncoder (save and reuse for test set + inference)
    """
    if le is None:
        le = LabelEncoder()
        le.fit(CLASS_NAMES)          # fixed order: F=0, L=1, R=2, S=3
    y_int = le.transform(y)
    return y_int, le


def prepare_input(X):
    """
    Add the singleton 'image channel' dimension EEGNet expects:
        (n_samples, n_ch, n_tp)  →  (n_samples, 1, n_ch, n_tp)
    """
    return X[:, np.newaxis, :, :]


# ==============================================================================
# SECTION 3 — EEGNET ARCHITECTURE  (PyTorch)
# ==============================================================================

class EEGNet(nn.Module):
    """
    EEGNet — Lawhern et al. (2018).  https://arxiv.org/abs/1611.08024

    Designed specifically for EEG: compact, generalizes across subjects.
    All ops are standard conv/BN/pool — fully exportable to ONNX and TFLite.

    Input shape:  (batch, 1, n_ch, n_tp)  =  (batch, 1, 8, 250)

    Block 1 — Temporal Conv (1 × kern_temp):
        Learns frequency-selective filters across time.
        kern_temp=64 → 256ms receptive field, covers full mu/beta oscillation.

    Block 2 — Depthwise Spatial Conv (n_ch × 1):
        Learns D spatial weightings per temporal filter.
        Equivalent to computing a weighted sum across electrodes.

    Block 3 — Separable Conv (1 × 16):
        Combines the D×F1 feature maps into F2 compact representations.

    Head — Dense(n_classes) + softmax (softmax applied externally via loss fn)
    """

    def __init__(self, n_classes=N_CLASSES, n_ch=N_CH, n_tp=WINDOW_SAMPLES,
                 F1=F1, D=D, F2=F2, dropout=DROPOUT, kern_temp=KERN_TEMP):
        super().__init__()

        # ── Block 1: Temporal convolution ─────────────────────────────────
        self.temporal_conv = nn.Conv2d(1, F1, (1, kern_temp),
                                       padding="same", bias=False)
        self.bn1 = nn.BatchNorm2d(F1)

        # ── Block 2: Depthwise spatial convolution ────────────────────────
        # groups=F1 makes it depthwise: each of the F1 input channels gets
        # D independent spatial filters, producing F1*D output channels
        self.spatial_depthwise = nn.Conv2d(F1, F1 * D, (n_ch, 1),
                                           groups=F1, bias=False)
        self.bn2 = nn.BatchNorm2d(F1 * D)
        self.pool1 = nn.AvgPool2d((1, 4))   # 250 → 62 timepoints
        self.drop1 = nn.Dropout(dropout)

        # ── Block 3: Separable convolution ────────────────────────────────
        # Separable = depthwise + pointwise
        self.sep_depthwise = nn.Conv2d(F1 * D, F1 * D, (1, 16),
                                        padding="same", groups=F1 * D, bias=False)
        self.sep_pointwise = nn.Conv2d(F1 * D, F2, (1, 1), bias=False)
        self.bn3 = nn.BatchNorm2d(F2)
        self.pool2 = nn.AvgPool2d((1, 8))   # 62 → 7 timepoints
        self.drop2 = nn.Dropout(dropout)

        # ── Classification head ───────────────────────────────────────────
        # Compute flattened size: after pool1 → (1, n_tp//4), pool2 → (1, n_tp//32)
        # Spatial dim after depthwise: n_ch → 1
        flat_size = F2 * (n_tp // 32)
        self.classifier = nn.Linear(flat_size, n_classes)

        # Apply max_norm constraints (matching Keras version)
        self._apply_weight_constraints()

    def _apply_weight_constraints(self):
        """Apply max_norm constraints matching the Keras version."""
        # Will be called after each optimizer step via a hook
        pass

    def forward(self, x):
        # Block 1: temporal
        x = self.temporal_conv(x)
        x = self.bn1(x)

        # Block 2: spatial depthwise
        x = self.spatial_depthwise(x)
        x = self.bn2(x)
        x = F.elu(x)
        x = self.pool1(x)
        x = self.drop1(x)

        # Block 3: separable
        x = self.sep_depthwise(x)
        x = self.sep_pointwise(x)
        x = self.bn3(x)
        x = F.elu(x)
        x = self.pool2(x)
        x = self.drop2(x)

        # Head
        x = x.flatten(1)
        x = self.classifier(x)
        return x   # raw logits — CrossEntropyLoss applies softmax internally

    def apply_max_norm(self):
        """Call after each optimizer.step() to enforce weight constraints."""
        with torch.no_grad():
            # Depthwise spatial: max_norm(1.0)
            w = self.spatial_depthwise.weight
            # Flatten all dims except 0 (out_channels) to compute per-filter norm
            norms = w.view(w.size(0), -1).norm(dim=1, keepdim=True).clamp(min=1e-8)
            scale = torch.clamp(1.0 / norms, max=1.0)
            w.copy_(w * scale.view(-1, 1, 1, 1))
            # Classifier: max_norm(0.25)
            w = self.classifier.weight
            norms = w.norm(dim=1, keepdim=True).clamp(min=1e-8)
            w.copy_(w * torch.clamp(0.25 / norms, max=1.0))


def count_params(model):
    total     = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return total, trainable


# ==============================================================================
# SECTION 4 — TRAINING
# ==============================================================================

def train(model, X_tr, y_tr, X_val, y_val, run_name, device):
    """
    Train with Adam, cross-entropy, early stopping, LR reduction on plateau,
    and mixed precision (float16 on Tensor Cores).
    """
    ckpt_path = MODELS_DIR / f"EEGNet_{run_name}_best.pt"

    # Convert numpy → torch tensors and move to GPU
    train_ds = TensorDataset(
        torch.from_numpy(X_tr).float(),
        torch.from_numpy(y_tr).long()
    )
    val_ds = TensorDataset(
        torch.from_numpy(X_val).float(),
        torch.from_numpy(y_val).long()
    )
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              pin_memory=True, num_workers=0)
    val_loader   = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                              pin_memory=True, num_workers=0)

    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=10, min_lr=1e-5
    )
    scaler = torch.amp.GradScaler(enabled=(device.type == "cuda"))

    total_p, train_p = count_params(model)
    print(f"\n[TRAIN] Run: {run_name}")
    print(f"[TRAIN] Train: {len(X_tr):,}  Val: {len(X_val):,}  "
          f"Batch: {BATCH_SIZE}  Max epochs: {EPOCHS}")
    print(f"[TRAIN] Parameters: {total_p:,} total, {train_p:,} trainable")
    print(f"[TRAIN] Device: {device}")

    best_val_acc  = 0.0
    patience_left = PATIENCE
    best_state    = None
    history       = {"train_loss": [], "val_loss": [], "train_acc": [], "val_acc": []}

    for epoch in range(1, EPOCHS + 1):
        # ── Train ─────────────────────────────────────────────────────────
        model.train()
        running_loss, running_correct, running_total = 0.0, 0, 0

        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            # Gaussian noise augmentation — 10% of each batch's own std
            # so it scales automatically regardless of data units (V or µV)
            xb = xb + 0.1 * xb.std() * torch.randn_like(xb)
            optimizer.zero_grad()

            with torch.amp.autocast(device_type=device.type, enabled=(device.type == "cuda")):
                logits = model(xb)
                loss = criterion(logits, yb)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            model.apply_max_norm()

            running_loss    += loss.item() * len(xb)
            running_correct += (logits.argmax(1) == yb).sum().item()
            running_total   += len(xb)

        train_loss = running_loss / running_total
        train_acc  = running_correct / running_total

        # ── Validate ──────────────────────────────────────────────────────
        model.eval()
        val_loss_sum, val_correct, val_total = 0.0, 0, 0

        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                with torch.amp.autocast(device_type=device.type, enabled=(device.type == "cuda")):
                    logits = model(xb)
                    loss = criterion(logits, yb)
                val_loss_sum += loss.item() * len(xb)
                val_correct  += (logits.argmax(1) == yb).sum().item()
                val_total    += len(xb)

        val_loss = val_loss_sum / val_total
        val_acc  = val_correct / val_total

        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["train_acc"].append(train_acc)
        history["val_acc"].append(val_acc)

        scheduler.step(val_loss)

        # ── Early stopping ────────────────────────────────────────────────
        if val_acc > best_val_acc:
            best_val_acc  = val_acc
            patience_left = PATIENCE
            best_state    = copy.deepcopy(model.state_dict())
            torch.save(best_state, ckpt_path)
        else:
            patience_left -= 1

        current_lr = optimizer.param_groups[0]["lr"]
        print(f"  Epoch {epoch:3d}/{EPOCHS} — "
              f"loss: {train_loss:.4f}  acc: {train_acc:.4f}  "
              f"val_loss: {val_loss:.4f}  val_acc: {val_acc:.4f}  "
              f"lr: {current_lr:.1e}  patience: {patience_left}")

        if patience_left <= 0:
            print(f"\n[TRAIN] Early stopping at epoch {epoch} "
                  f"(best val_acc: {best_val_acc:.4f})")
            break

    # Restore best weights
    if best_state is not None:
        model.load_state_dict(best_state)
    print(f"[TRAIN] Best val accuracy: {best_val_acc*100:.2f}%")

    return history


# ==============================================================================
# SECTION 5 — EVALUATION
# ==============================================================================

def evaluate(model, X_test, y_test, le, device):
    """
    Print confusion matrix and per-class accuracy.
    """
    model.eval()
    model = model.to(device)

    X_t = torch.from_numpy(X_test).float().to(device)
    with torch.no_grad():
        logits = model(X_t)
        y_pred_idx = logits.argmax(1).cpu().numpy()

    y_true_idx  = y_test  # already integer indices
    y_pred_lbl  = le.inverse_transform(y_pred_idx)
    y_true_lbl  = le.inverse_transform(y_true_idx)

    print("\n" + "=" * 62)
    print("  EVALUATION  (rows = true, cols = predicted)")
    print("=" * 62)
    print(classification_report(y_true_lbl, y_pred_lbl,
                                 target_names=CLASS_NAMES, digits=3))

    cm = confusion_matrix(y_true_lbl, y_pred_lbl, labels=CLASS_NAMES)
    header = "        " + "  ".join(f"{c:>5}" for c in CLASS_NAMES)
    print("Confusion matrix:")
    print(header)
    for i, row in enumerate(cm):
        print(f"  {CLASS_NAMES[i]:>4}  " + "  ".join(f"{v:>5}" for v in row))

    acc = float(np.mean(y_pred_idx == y_true_idx))
    print(f"\n  Overall accuracy : {acc*100:.2f}%")
    print("=" * 62)
    return acc, cm


# ==============================================================================
# SECTION 6 — EXPORT  (PyTorch → ONNX → TFLite)
# ==============================================================================

def export_models(model, X_representative, run_name, device):
    """
    Export trained model to multiple formats:

    1.  EEGNet_{run_name}.pt
        PyTorch state dict. Use for Phase 2 fine-tuning.

    2.  EEGNet_{run_name}.onnx
        ONNX format. Universal interchange, validates architecture.

    3.  EEGNet_{run_name}.tflite  (float32)
        Via ONNX → TFLite conversion. Works on any device.

    4.  EEGNet_{run_name}_int8.tflite
        Fully integer-quantized. Ready for edgetpu_compiler.
        NEXT STEP: on Coral (Linux):
            $ edgetpu_compiler EEGNet_{run_name}_int8.tflite

    Parameters
    ----------
    X_representative : np.ndarray, shape (n_cal, 1, 8, 250)
        ~200 samples for int8 calibration.
    """
    pt_path   = MODELS_DIR / f"EEGNet_{run_name}.pt"
    onnx_path = MODELS_DIR / f"EEGNet_{run_name}.onnx"
    f32_path  = MODELS_DIR / f"EEGNet_{run_name}.tflite"
    i8_path   = MODELS_DIR / f"EEGNet_{run_name}_int8.tflite"

    model.eval()
    model_cpu = model.to("cpu")

    # 1. PyTorch state dict
    torch.save(model_cpu.state_dict(), pt_path)
    print(f"[EXPORT] PyTorch    → {pt_path}")

    # 2. ONNX export
    try:
        dummy_input = torch.randn(1, 1, N_CH, WINDOW_SAMPLES)
        torch.onnx.export(
            model_cpu, dummy_input, str(onnx_path),
            input_names=["eeg_input"],
            output_names=["logits"],
            dynamic_axes={"eeg_input": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=13,
        )
        print(f"[EXPORT] ONNX       → {onnx_path}  ({onnx_path.stat().st_size/1024:.1f} KB)")
    except Exception as e:
        print(f"[EXPORT] ONNX export failed: {e}")
        onnx_path = None

    # 3 & 4. TFLite conversion via tensorflow-cpu
    if onnx_path is not None:
        try:
            import tensorflow as tf
            import onnx
            from onnx_tf.backend import prepare as onnx_tf_prepare

            # ONNX → TensorFlow SavedModel → TFLite
            onnx_model = onnx.load(str(onnx_path))
            tf_rep = onnx_tf_prepare(onnx_model)
            saved_model_dir = str(MODELS_DIR / f"_tmp_savedmodel_{run_name}")
            tf_rep.export_graph(saved_model_dir)

            # Float32 TFLite
            converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
            f32_bytes = converter.convert()
            f32_path.write_bytes(f32_bytes)
            print(f"[EXPORT] Float32    → {f32_path}  ({len(f32_bytes)/1024:.1f} KB)")

            # Int8 quantized TFLite
            def rep_data_gen():
                for i in range(min(200, len(X_representative))):
                    yield [X_representative[i:i+1].astype(np.float32)]

            converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
            converter.optimizations              = [tf.lite.Optimize.DEFAULT]
            converter.representative_dataset     = rep_data_gen
            converter.target_spec.supported_ops  = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
            converter.inference_input_type       = tf.int8
            converter.inference_output_type      = tf.int8
            i8_bytes = converter.convert()
            i8_path.write_bytes(i8_bytes)
            print(f"[EXPORT] Int8       → {i8_path}  ({len(i8_bytes)/1024:.1f} KB)")

            # Cleanup temp dir
            import shutil
            shutil.rmtree(saved_model_dir, ignore_errors=True)

            print(f"\n[EXPORT] *** NEXT STEP — on your Coral (Linux) ***")
            print(f"[EXPORT]   edgetpu_compiler {i8_path.name}")
            print(f"[EXPORT] → produces  {i8_path.stem}_edgetpu.tflite")

        except Exception as e:
            print(f"\n[EXPORT] TFLite conversion failed: {e}")
            print(f"[EXPORT] The ONNX file can be converted manually later.")

    # Move model back to original device
    model.to(device)


# ==============================================================================
# SECTION 7 — FINE-TUNING  (Phase 2 — personal calibration)
# ==============================================================================

def finetune(base_pt_path, X_personal, y_personal, device, run_name="personal"):
    """
    Phase 2: Fine-tune the pre-trained model on the user's own EEG data.

    Call this after recording a ~10-minute calibration session on the Coral:
        - ~25 trials per class  (100 total)
        - Screen shows arrows: ← → ↑ and tongue cue
        - Each trial is ~6 seconds (2s cue + 4s imagery)

    Parameters
    ----------
    base_pt_path : Path or str — path to pre-trained .pt state dict
    X_personal   : np.ndarray, shape (n_windows, 1, n_ch, n_tp)
    y_personal   : np.ndarray of int labels, shape (n_windows,)
    device       : torch.device
    run_name     : str — identifier for saved personal model files
    """
    print(f"\n[FINETUNE] Loading base model: {base_pt_path}")
    model = EEGNet()
    model.load_state_dict(torch.load(str(base_pt_path), weights_only=True))

    # Freeze everything
    for param in model.parameters():
        param.requires_grad = False

    # Unfreeze Block 3 + classifier
    for name, param in model.named_parameters():
        if any(k in name for k in ["sep_depthwise", "sep_pointwise", "bn3",
                                     "classifier"]):
            param.requires_grad = True

    total_p, train_p = count_params(model)
    print(f"[FINETUNE] Trainable params: {train_p:,} / {total_p:,} "
          f"({100*train_p/total_p:.1f}%)")

    # 80/20 split
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=0)
    tr_idx, vl_idx = next(sss.split(X_personal, y_personal))

    # Use smaller batch and learning rate for fine-tuning
    history = train(model, X_personal[tr_idx], y_personal[tr_idx],
                    X_personal[vl_idx], y_personal[vl_idx],
                    run_name, device)

    le = LabelEncoder()
    le.fit(CLASS_NAMES)
    acc, cm = evaluate(model, X_personal[vl_idx], y_personal[vl_idx], le, device)
    export_models(model, X_personal[tr_idx[:200]], run_name, device)
    return model, acc


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    device   = configure_gpu()
    run_name = datetime.now().strftime("pretrain_%Y%m%d_%H%M%S")

    print("=" * 65)
    print("  NEURODRIVE — NODE 1 | EEGNET PRE-TRAINING  (PyTorch + CUDA)")
    print(f"  Train subjects : {TRAIN_SUBJECTS}")
    print(f"  Test subject   : {TEST_SUBJECT}  (held out — never seen)")
    print(f"  Run name       : {run_name}")
    print("=" * 65)

    # ── Step 1: Load ──────────────────────────────────────────────────────
    print("\n[STEP 1/7] Loading & epoching data from MOABB...")
    X_train_raw, y_train = load_and_epoch(TRAIN_SUBJECTS)
    X_test_raw,  y_test  = load_and_epoch([TEST_SUBJECT])

    # ── Step 2: Notch filter ──────────────────────────────────────────────
    print("\n[STEP 2/7] Applying 50 Hz notch filter...")
    X_train_raw = apply_notch(X_train_raw)
    X_test_raw  = apply_notch(X_test_raw)

    # ── Step 3: Segment into 1-second windows ─────────────────────────────
    print("\n[STEP 3/7] Segmenting trials into 1s windows (50% overlap)...")
    X_tr_seg, y_tr_seg = segment(X_train_raw, y_train)
    X_te_seg, y_te_seg = segment(X_test_raw,  y_test)
    print(f"[STEP 3/7] Train: {len(X_tr_seg):,} windows | "
          f"Test: {len(X_te_seg):,} windows")

    # ── Step 4: Encode labels ─────────────────────────────────────────────
    print("\n[STEP 4/7] Encoding labels...")
    y_tr_int, le = encode_labels(y_tr_seg)
    y_te_int, _  = encode_labels(y_te_seg, le)

    # ── Step 5: Prepare tensors ───────────────────────────────────────────
    X_tr_4d = prepare_input(X_tr_seg)   # (n, 1, 8, 250)
    X_te_4d = prepare_input(X_te_seg)

    # 10% of training set as validation (stratified)
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.1, random_state=42)
    tr_idx, vl_idx = next(sss.split(X_tr_4d, y_tr_int))
    X_val, y_val = X_tr_4d[vl_idx], y_tr_int[vl_idx]
    X_tr,  y_tr  = X_tr_4d[tr_idx], y_tr_int[tr_idx]

    print(f"\n[STEP 5/7] Final split — "
          f"Train: {len(X_tr):,} | Val: {len(X_val):,} | Test: {len(X_te_4d):,}")

    # ── Step 6: Train ─────────────────────────────────────────────────────
    print("\n[STEP 6/7] Building & training EEGNet...")
    model   = EEGNet()
    history = train(model, X_tr, y_tr, X_val, y_val, run_name, device)

    # ── Step 7: Evaluate ──────────────────────────────────────────────────
    print("\n[STEP 7/7] Evaluating on held-out test subject...")
    acc, cm = evaluate(model, X_te_4d, y_te_int, le, device)

    # ── Export ────────────────────────────────────────────────────────────
    print("\n[EXPORT] Saving models...")
    cal_samples = []
    for cls_idx in range(N_CLASSES):
        mask = y_te_int == cls_idx
        cal_samples.append(X_te_4d[mask][:25])
    X_cal = np.concatenate(cal_samples, axis=0)
    export_models(model, X_cal, run_name, device)

    print(f"\n{'='*65}")
    print(f"  DONE.  Test accuracy: {acc*100:.2f}%")
    print(f"  Models saved to: {MODELS_DIR.resolve()}")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
