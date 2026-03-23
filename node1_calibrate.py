"""
================================================================================
NEURODRIVE — NODE 1 | PERSONAL CALIBRATION  (Phase 2)
================================================================================
Fine-tunes the pre-trained EEGNet on personal EEG data.

SITL mode (now):   Uses BCI-IV-2a subject 9 as stand-in for personal data.
Hardware mode:     Swap data source to ADS1299 recording (built later).

Usage:
    python node1_calibrate.py

What it does:
    1. Loads the best pre-trained model (Phase 1 — 43% cross-subject)
    2. Loads "personal" data (subject 9 in SITL mode)
    3. Freezes early layers (temporal + spatial convolutions)
    4. Fine-tunes Block 3 + classifier on personal data
    5. Evaluates and exports the personalized model
================================================================================
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import copy

import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.preprocessing import LabelEncoder

# Import shared components from training script
sys.path.insert(0, str(Path(__file__).parent))
from node1_training import (
    EEGNet, configure_gpu, count_params, evaluate, export_models,
    load_and_epoch, apply_notch, segment, encode_labels, prepare_input,
    CLASS_NAMES, N_CLASSES, MODELS_DIR,
)

# ==============================================================================
# CALIBRATION CONFIG
# ==============================================================================

# Fine-tuning uses lower LR and smaller batch than pre-training
# to avoid overwriting the learned universal features
FT_BATCH_SIZE = 32
FT_LR         = 0.0001   # 10x lower than pre-training
FT_EPOCHS     = 100
FT_PATIENCE   = 15

# Which pre-trained model to start from
BASE_MODEL = MODELS_DIR / "EEGNet_pretrain_20260312_004816.pt"

# SITL: use subject 9 as stand-in for personal data
SITL_SUBJECT = 9


# ==============================================================================
# FINE-TUNE TRAINING LOOP
# ==============================================================================

def finetune_train(model, X_tr, y_tr, X_val, y_val, device):
    """
    Fine-tuning training loop — smaller LR, smaller batch, no noise augmentation.
    We want the model to learn YOUR patterns, not be robust to noise.
    """
    train_ds = TensorDataset(torch.from_numpy(X_tr).float(),
                              torch.from_numpy(y_tr).long())
    val_ds   = TensorDataset(torch.from_numpy(X_val).float(),
                              torch.from_numpy(y_val).long())
    train_loader = DataLoader(train_ds, batch_size=FT_BATCH_SIZE, shuffle=True,
                              pin_memory=True)
    val_loader   = DataLoader(val_ds, batch_size=FT_BATCH_SIZE, shuffle=False,
                              pin_memory=True)

    model = model.to(device)

    # Only optimize unfrozen parameters
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(trainable_params, lr=FT_LR)
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=5, min_lr=1e-6
    )
    scaler = torch.amp.GradScaler(enabled=(device.type == "cuda"))

    best_val_acc  = 0.0
    patience_left = FT_PATIENCE
    best_state    = None

    for epoch in range(1, FT_EPOCHS + 1):
        # ── Train ─────────────────────────────────────────────────────────
        # Use model.train() but keep frozen BN layers in eval mode so their
        # running stats (learned across 8 subjects) don't drift on 1 person's data
        model.train()
        for m in model.modules():
            if isinstance(m, nn.BatchNorm2d) and not m.weight.requires_grad:
                m.eval()
        running_loss, running_correct, running_total = 0.0, 0, 0

        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()

            with torch.amp.autocast(device_type=device.type,
                                     enabled=(device.type == "cuda")):
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
                with torch.amp.autocast(device_type=device.type,
                                         enabled=(device.type == "cuda")):
                    logits = model(xb)
                    loss = criterion(logits, yb)
                val_loss_sum += loss.item() * len(xb)
                val_correct  += (logits.argmax(1) == yb).sum().item()
                val_total    += len(xb)

        val_loss = val_loss_sum / val_total
        val_acc  = val_correct / val_total

        scheduler.step(val_loss)

        if val_acc > best_val_acc:
            best_val_acc  = val_acc
            patience_left = FT_PATIENCE
            best_state    = copy.deepcopy(model.state_dict())
        else:
            patience_left -= 1

        current_lr = optimizer.param_groups[0]["lr"]
        print(f"  Epoch {epoch:3d}/{FT_EPOCHS} — "
              f"loss: {train_loss:.4f}  acc: {train_acc:.4f}  "
              f"val_loss: {val_loss:.4f}  val_acc: {val_acc:.4f}  "
              f"lr: {current_lr:.1e}  patience: {patience_left}")

        if patience_left <= 0:
            print(f"\n[FINETUNE] Early stopping at epoch {epoch} "
                  f"(best val_acc: {best_val_acc:.4f})")
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    print(f"[FINETUNE] Best val accuracy: {best_val_acc*100:.2f}%")
    return model


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    device   = configure_gpu()
    run_name = datetime.now().strftime("personal_%Y%m%d_%H%M%S")

    print("=" * 65)
    print("  NEURODRIVE — NODE 1 | PERSONAL CALIBRATION  (Phase 2)")
    print(f"  Base model     : {BASE_MODEL.name}")
    print(f"  SITL subject   : {SITL_SUBJECT}  (stand-in for personal data)")
    print(f"  Run name       : {run_name}")
    print("=" * 65)

    # ── Step 1: Load personal data ────────────────────────────────────────
    print("\n[STEP 1/5] Loading personal data (SITL: subject 9)...")
    X_raw, y_raw = load_and_epoch([SITL_SUBJECT])

    # ── Step 2: Preprocess ────────────────────────────────────────────────
    print("\n[STEP 2/5] Preprocessing...")
    X_raw = apply_notch(X_raw)
    X_seg, y_seg = segment(X_raw, y_raw)
    y_int, le    = encode_labels(y_seg)
    X_4d         = prepare_input(X_seg)
    print(f"[STEP 2/5] {len(X_4d):,} windows, shape {X_4d.shape}")

    # ── Step 3: Load & freeze base model ──────────────────────────────────
    print(f"\n[STEP 3/5] Loading base model: {BASE_MODEL}")
    if not BASE_MODEL.exists():
        print(f"[ERROR] Base model not found: {BASE_MODEL}")
        print(f"[ERROR] Run node1_training.py first to create it.")
        return

    model = EEGNet()
    model.load_state_dict(torch.load(str(BASE_MODEL), weights_only=True))

    # Freeze everything
    for param in model.parameters():
        param.requires_grad = False

    # Unfreeze Block 3 (separable conv) + classifier head
    for name, param in model.named_parameters():
        if any(k in name for k in ["sep_depthwise", "sep_pointwise", "bn3",
                                     "classifier"]):
            param.requires_grad = True

    total_p, train_p = count_params(model)
    print(f"[STEP 3/5] Frozen: {total_p - train_p:,} params | "
          f"Trainable: {train_p:,} params ({100*train_p/total_p:.1f}%)")

    # ── Step 4: Split & fine-tune ─────────────────────────────────────────
    # 70% train / 15% val / 15% test
    print("\n[STEP 4/5] Fine-tuning...")
    sss1 = StratifiedShuffleSplit(n_splits=1, test_size=0.3, random_state=42)
    tr_idx, tmp_idx = next(sss1.split(X_4d, y_int))

    sss2 = StratifiedShuffleSplit(n_splits=1, test_size=0.5, random_state=42)
    vl_sub, te_sub = next(sss2.split(X_4d[tmp_idx], y_int[tmp_idx]))
    vl_idx = tmp_idx[vl_sub]
    te_idx = tmp_idx[te_sub]

    X_tr, y_tr   = X_4d[tr_idx], y_int[tr_idx]
    X_val, y_val = X_4d[vl_idx], y_int[vl_idx]
    X_te, y_te   = X_4d[te_idx], y_int[te_idx]

    print(f"  Train: {len(X_tr):,} | Val: {len(X_val):,} | Test: {len(X_te):,}")

    model = finetune_train(model, X_tr, y_tr, X_val, y_val, device)

    # ── Step 5: Evaluate on held-out personal test set ────────────────────
    print("\n[STEP 5/5] Evaluating on personal test set...")
    acc, cm = evaluate(model, X_te, y_te, le, device)

    # ── Export ────────────────────────────────────────────────────────────
    print("\n[EXPORT] Saving personalized model...")
    export_models(model, X_te[:200], run_name, device)

    print(f"\n{'='*65}")
    print(f"  DONE.  Personal test accuracy: {acc*100:.2f}%")
    print(f"  (Base model cross-subject was ~43% — this should be higher)")
    print(f"  Models saved to: {MODELS_DIR.resolve()}")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
