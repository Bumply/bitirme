"""
================================================================================
NEURODRIVE — DOCS FIGURE GENERATOR
================================================================================
Regenerates the GitHub Pages figures in docs/assets/ that depend on the
*current* 4-channel build. Two kinds of figures:

  A. SCHEMATIC (no training) — drawn directly:
       channel_map.png          8-site 10-20 design, 4 wired sites highlighted
       eegnet_architecture.png  EEGNet block diagram with (1,4,250) input
       dashboard_wireframe.png  PyQt5 Drive tab (MANUAL/EEG, hold-to-drive)

  B. PERFORMANCE (real GPU run) — reuses node1_training.py verbatim:
       training_curves.png      loss/acc from the real pre-training run
       confusion_matrix.png     held-out subject 9, real predictions
       per_subject_accuracy.png leave-one-subject-out sweep (9 real trainings)
       finetuning_curves.png    within-subject personal calibration (real)
       calibration_impact.png   per-class before/after calibration (real)

Real numbers are written to figure_metrics.json so they are never lost again
(node1_training.py only prints them). Run inside the training venv:

    .venv-train/bin/python generate_figures.py            # everything
    .venv-train/bin/python generate_figures.py --schematic # A only (fast)
================================================================================
"""
import os
import sys
import json
import copy
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Wedge

HERE      = Path(__file__).parent
ASSETS    = HERE / "docs" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)
METRICS   = HERE / "figure_metrics.json"

# ── Site theme (matches docs/index.html dark palette) ─────────────────────────
BG     = "#0d1117"
PANEL  = "#161b22"
BORDER = "#30363d"
GRID   = "#21262d"
TEXT   = "#c9d1d9"
MUTED  = "#8b949e"
TITLE  = "#f0f6fc"
BLUE   = "#58a6ff"
GREEN  = "#3fb950"
ORANGE = "#f0883e"
RED    = "#e94560"
PURPLE = "#bc8cff"

# Per-command colours, reused everywhere a class appears
CLASS_COLOR = {"F": GREEN, "L": BLUE, "R": ORANGE, "S": RED}
CLASS_FULL  = {"F": "Forward", "L": "Left", "R": "Right", "S": "Stop"}

def apply_theme():
    # Re-apply explicitly: importing mne/moabb (in node1_training) resets rcParams,
    # which would otherwise leave the performance plots with a white axes background.
    plt.rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": PANEL,
        "savefig.facecolor": BG, "savefig.edgecolor": BG,
        "text.color": TEXT, "axes.labelcolor": TEXT,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": BORDER, "grid.color": GRID,
        "font.family": "DejaVu Sans", "font.size": 11,
        "axes.titlecolor": TITLE,
    })


apply_theme()

WIRED = ["C3", "Cz", "C4", "CPz"]   # current ADS1299-4 build


def _save(fig, name):
    path = ASSETS / name
    fig.savefig(path, dpi=130, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print(f"[FIG] wrote {path.relative_to(HERE)}")


# ==============================================================================
# A — SCHEMATIC FIGURES
# ==============================================================================

def fig_channel_map():
    """8-site 10-20 design; the 4 wired sites (C3,Cz,C4,CPz) are highlighted."""
    # Approx 2D-projected 10-20 coordinates (x = right, y = front)
    pos = {
        "FCz": (0.00,  0.34), "FC3": (-0.34, 0.30), "FC4": (0.34, 0.30),
        "C3": (-0.42, 0.00),  "Cz": (0.00, 0.00),   "C4": (0.42, 0.00),
        "CP3": (-0.34, -0.30), "CP4": (0.34, -0.30), "CPz": (0.00, -0.34),
    }
    # which command each wired site primarily supports
    driver = {"C3": "R", "Cz": "F", "C4": "L", "CPz": "S"}

    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    ax.set_aspect("equal"); ax.axis("off")

    # head + nose + ears
    ax.add_patch(Circle((0, 0), 0.62, fill=False, ec=MUTED, lw=2))
    ax.add_patch(plt.Polygon([(-0.09, 0.60), (0.0, 0.72), (0.09, 0.60)],
                             closed=True, fill=False, ec=MUTED, lw=2))
    ax.add_patch(Wedge((-0.62, 0), 0.07, 90, 270, fill=False, ec=MUTED, lw=2))
    ax.add_patch(Wedge((0.62, 0), 0.07, 270, 90, fill=False, ec=MUTED, lw=2))

    for name, (x, y) in pos.items():
        wired = name in WIRED
        if wired:
            c = CLASS_COLOR[driver[name]]
            ax.add_patch(Circle((x, y), 0.085, fc=c, ec="white", lw=1.6, zorder=3))
            ax.text(x, y, name, ha="center", va="center", color="#0d1117",
                    fontsize=9, fontweight="bold", zorder=4)
        else:
            ax.add_patch(Circle((x, y), 0.075, fc=PANEL, ec=MUTED,
                                 lw=1.4, ls="--", zorder=2))
            ax.text(x, y, name, ha="center", va="center", color=MUTED,
                    fontsize=8.5, zorder=4)

    ax.set_xlim(-0.8, 0.8); ax.set_ylim(-0.85, 0.85)
    ax.set_title("Electrode Layout — 8-site design, 4 wired in current build",
                 fontsize=13, pad=14)

    # legend
    handles = [plt.Line2D([0], [0], marker="o", ls="", mfc=CLASS_COLOR[d],
                          mec="white", ms=11,
                          label=f"{s} → {CLASS_FULL[driver[s]]}")
               for s, d in driver.items()]
    handles.append(plt.Line2D([0], [0], marker="o", ls="", mfc=PANEL, mec=MUTED,
                              ms=11, label="8-ch design site (not wired yet)"))
    leg = ax.legend(handles=handles, loc="lower center", ncol=2,
                    bbox_to_anchor=(0.5, -0.16), frameon=False,
                    fontsize=9, labelcolor=TEXT)
    _save(fig, "channel_map.png")


def fig_eegnet_architecture():
    """EEGNet block diagram with the current (1,4,250) input shape."""
    fig, ax = plt.subplots(figsize=(11, 4.3))
    ax.set_xlim(0, 100); ax.set_ylim(0, 36); ax.axis("off")

    blocks = [
        ("Input\n(1, 4, 250)\n1 s × 4 ch", BLUE),
        ("Temporal Conv\n8 @ (1×64)\nBatchNorm", GREEN),
        ("Depthwise\nSpatial (4×1)\n→ 16 · ELU\nPool · Drop", ORANGE),
        ("Separable\n(1×16) → 16\nELU\nPool · Drop", PURPLE),
        ("Flatten\n16 × 7\n= 112", MUTED),
        ("Dense → 4\nF / L / R / S", RED),
    ]
    n = len(blocks); w = 14.6; gap = (100 - n * w) / (n - 1)
    y0, h = 8, 20
    for i, (label, col) in enumerate(blocks):
        x = i * (w + gap)
        ax.add_patch(FancyBboxPatch((x, y0), w, h, boxstyle="round,pad=0.3,rounding_size=1.2",
                                    fc=PANEL, ec=col, lw=2.2))
        ax.text(x + w / 2, y0 + h / 2, label, ha="center", va="center",
                color=TEXT, fontsize=8.8, linespacing=1.5)
        if i < n - 1:
            ax.add_patch(FancyArrowPatch((x + w, y0 + h / 2),
                                         (x + w + gap, y0 + h / 2),
                                         arrowstyle="-|>", mutation_scale=16,
                                         color=MUTED, lw=1.6))
    ax.text(50, 32, "EEGNet (Lawhern et al. 2018) — 1,684 parameters",
            ha="center", color=TITLE, fontsize=13, fontweight="bold")
    ax.text(50, 3.5, "Depthwise spatial conv collapses the 4 electrodes into "
            "learned spatial filters; fully ONNX/TFLite-exportable.",
            ha="center", color=MUTED, fontsize=9.5)
    _save(fig, "eegnet_architecture.png")


def fig_dashboard_wireframe():
    """PyQt5 Drive tab: MANUAL/EEG mode toggle + hold-to-drive."""
    fig, ax = plt.subplots(figsize=(8.4, 5.6))
    ax.set_xlim(0, 100); ax.set_ylim(0, 66); ax.axis("off")

    # outer screen
    ax.add_patch(FancyBboxPatch((2, 2), 96, 62, boxstyle="round,pad=0.4,rounding_size=1.5",
                                fc=PANEL, ec=BORDER, lw=2))
    # tab bar
    for i, (t, on) in enumerate([("DRIVE", True), ("DEBUG", False), ("CALIBRATE", False)]):
        x = 5 + i * 22
        ax.add_patch(FancyBboxPatch((x, 56.5, ), 20, 5,
                                    boxstyle="round,pad=0.2,rounding_size=0.8",
                                    fc=(BLUE if on else PANEL), ec=BORDER, lw=1.4))
        ax.text(x + 10, 59, t, ha="center", va="center",
                color=("#0d1117" if on else MUTED), fontsize=9, fontweight="bold")
    # mode toggle (top-right)
    ax.add_patch(FancyBboxPatch((73, 49, ), 22, 5, boxstyle="round,pad=0.2,rounding_size=0.8",
                                fc=PANEL, ec=BLUE, lw=1.6))
    ax.text(84, 51.5, "MODE: EEG  ⇄  MANUAL", ha="center", va="center",
            color=BLUE, fontsize=8.5, fontweight="bold")

    # big command display
    ax.add_patch(FancyBboxPatch((5, 30, ), 56, 18, boxstyle="round,pad=0.3,rounding_size=1.2",
                                fc="#10171f", ec=GREEN, lw=2))
    ax.text(33, 41, "FORWARD", ha="center", va="center", color=GREEN,
            fontsize=26, fontweight="bold")
    ax.text(33, 34, "command from Node 1 (EEG)", ha="center", color=MUTED, fontsize=8.5)
    # confidence bar
    ax.text(8, 27, "confidence", color=MUTED, fontsize=8)
    ax.add_patch(FancyBboxPatch((8, 23, ), 50, 3, boxstyle="round,pad=0.1,rounding_size=0.6",
                                fc=GRID, ec="none"))
    ax.add_patch(FancyBboxPatch((8, 23, ), 50 * 0.62, 3,
                                boxstyle="round,pad=0.1,rounding_size=0.6", fc=GREEN, ec="none"))
    ax.text(59, 24.5, "62 %", color=TEXT, fontsize=8, va="center")

    # manual control pad (right)
    ax.text(80, 45, "manual controls", color=MUTED, fontsize=8, ha="center")
    pad = {"HOLD\nFORWARD": (80, 39, GREEN), "LEFT": (70, 32, BLUE),
           "STOP": (80, 32, MUTED), "RIGHT": (90, 32, ORANGE)}
    for label, (x, y, col) in pad.items():
        ax.add_patch(FancyBboxPatch((x - 5, y - 2.5), 10, 5.6,
                                    boxstyle="round,pad=0.2,rounding_size=0.8",
                                    fc=PANEL, ec=col, lw=1.6))
        ax.text(x, y + 0.3, label, ha="center", va="center", color=col,
                fontsize=7.2, fontweight="bold")
    ax.add_patch(FancyBboxPatch((70, 23, ), 25, 4.5, boxstyle="round,pad=0.2,rounding_size=0.8",
                                fc="#2d0f17", ec=RED, lw=1.8))
    ax.text(82.5, 25.2, "E-STOP", ha="center", va="center", color=RED,
            fontsize=10, fontweight="bold")

    # command log
    ax.add_patch(FancyBboxPatch((5, 5, ), 90, 14, boxstyle="round,pad=0.3,rounding_size=1",
                                fc="#10171f", ec=BORDER, lw=1.4))
    ax.text(8, 16.5, "command log", color=MUTED, fontsize=8)
    for i, line in enumerate(["12:04:01  EEG   F  conf 0.62  → relay F",
                              "12:04:00  EEG   F  conf 0.58  → relay F",
                              "12:03:59  EEG   S  conf 0.71  → relay S"]):
        ax.text(8, 13 - i * 2.6, line, color=TEXT, fontsize=7.6,
                family="monospace")

    ax.text(50, 0.2, "Node 2 — native PyQt5 touchscreen app (Drive tab) · "
            "phone web mirror at :8000", ha="center", color=MUTED, fontsize=8.5)
    ax.set_ylim(-1, 66)
    _save(fig, "dashboard_wireframe.png")


# ==============================================================================
# B — PERFORMANCE FIGURES (real training)
# ==============================================================================

def _load_pipeline():
    """Import node1_training and pre-load every subject once (notch+segment)."""
    import node1_training as T
    # bound the per-run epoch budget so the LOSO sweep stays reasonable while
    # remaining a real, early-stopped training run
    T.EPOCHS   = int(os.environ.get("FIG_EPOCHS", "120"))
    T.PATIENCE = int(os.environ.get("FIG_PATIENCE", "18"))

    print(f"[FIG] loading all 9 subjects (cached MOABB) ...")
    le = None
    per_subj = {}
    for s in T.ALL_SUBJECTS:
        X, y = T.load_and_epoch([s])
        X = T.apply_notch(X)
        Xs, ys = T.segment(X, y)
        yi, le = T.encode_labels(ys, le)
        per_subj[s] = (T.prepare_input(Xs), yi)
        print(f"[FIG]   subject {s}: {len(yi):,} windows")
    return T, le, per_subj


def _concat(per_subj, subjects):
    Xs = np.concatenate([per_subj[s][0] for s in subjects], axis=0)
    ys = np.concatenate([per_subj[s][1] for s in subjects], axis=0)
    return Xs, ys


def fig_performance():
    import torch
    from sklearn.model_selection import StratifiedShuffleSplit
    np.random.seed(0); torch.manual_seed(0)

    T, le, per_subj = _load_pipeline()
    apply_theme()   # mne/moabb import above resets rcParams — restore dark theme
    device = T.configure_gpu()
    metrics = {}

    # ── Main pre-training run: train on 1-8, test on 9 ────────────────────────
    print("\n[FIG] === main pre-training run (subjects 1-8 → test 9) ===")
    X_trv, y_trv = _concat(per_subj, T.TRAIN_SUBJECTS)
    X_test, y_test = per_subj[T.TEST_SUBJECT]
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.1, random_state=42)
    tr, vl = next(sss.split(X_trv, y_trv))
    model = T.EEGNet()
    history = T.train(model, X_trv[tr], y_trv[tr], X_trv[vl], y_trv[vl],
                      "fig_pretrain", device)
    acc, cm = T.evaluate(model, X_test, y_test, le, device)
    metrics["cross_subject_acc"] = round(float(acc), 4)
    metrics["confusion_matrix"]  = cm.tolist()
    metrics["per_class_acc"]     = {c: round(float(cm[i, i] / cm[i].sum()), 4)
                                    for i, c in enumerate(T.CLASS_NAMES)}

    # training curves
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    ep = range(1, len(history["train_loss"]) + 1)
    a1.plot(ep, history["train_loss"], color=BLUE, label="train")
    a1.plot(ep, history["val_loss"], color=ORANGE, label="val")
    a1.set_title("Loss"); a1.set_xlabel("epoch"); a1.set_ylabel("cross-entropy")
    a2.plot(ep, [v * 100 for v in history["train_acc"]], color=BLUE, label="train")
    a2.plot(ep, [v * 100 for v in history["val_acc"]], color=ORANGE, label="val")
    a2.axhline(25, color=MUTED, ls="--", lw=1, label="chance (25%)")
    a2.set_title("Accuracy"); a2.set_xlabel("epoch"); a2.set_ylabel("%")
    for a in (a1, a2):
        a.grid(True, alpha=0.25); a.legend(frameon=False, labelcolor=TEXT)
    fig.suptitle("Pre-training — 4-channel EEGNet on BCI-IV-2a (subjects 1-8)",
                 color=TITLE, fontsize=13)
    _save(fig, "training_curves.png")

    # confusion matrix
    fig, ax = plt.subplots(figsize=(5.6, 5.2))
    cmn = cm / cm.sum(axis=1, keepdims=True)
    im = ax.imshow(cmn, cmap="cividis", vmin=0, vmax=1)
    ax.set_xticks(range(4)); ax.set_yticks(range(4))
    ax.set_xticklabels(T.CLASS_NAMES); ax.set_yticklabels(T.CLASS_NAMES)
    ax.set_xlabel("predicted"); ax.set_ylabel("true")
    for i in range(4):
        for j in range(4):
            ax.text(j, i, f"{cm[i, j]}\n{cmn[i, j]*100:.0f}%", ha="center",
                    va="center", fontsize=9,
                    color=("#0d1117" if cmn[i, j] > 0.5 else "white"))
    ax.set_title(f"Confusion — held-out subject 9\noverall {acc*100:.1f}% "
                 f"(chance 25%)", fontsize=12)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    _save(fig, "confusion_matrix.png")

    # ── Leave-one-subject-out sweep ───────────────────────────────────────────
    print("\n[FIG] === leave-one-subject-out sweep (9 runs) ===")
    subj_acc = {}
    for s in T.ALL_SUBJECTS:
        if s == T.TEST_SUBJECT:
            subj_acc[s] = acc  # reuse the main run
            continue
        others = [k for k in T.ALL_SUBJECTS if k != s]
        Xo, yo = _concat(per_subj, others)
        tr, vl = next(StratifiedShuffleSplit(1, test_size=0.1,
                                              random_state=42).split(Xo, yo))
        m = T.EEGNet()
        T.train(m, Xo[tr], yo[tr], Xo[vl], yo[vl], f"fig_loso_s{s}", device)
        a, _ = T.evaluate(m, per_subj[s][0], per_subj[s][1], le, device)
        subj_acc[s] = float(a)
        print(f"[FIG]   LOSO subject {s}: {a*100:.1f}%")
    metrics["per_subject_acc"] = {str(s): round(v, 4) for s, v in subj_acc.items()}
    mean_acc = float(np.mean(list(subj_acc.values())))
    metrics["loso_mean_acc"] = round(mean_acc, 4)

    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    xs = list(subj_acc.keys())
    ys = [subj_acc[s] * 100 for s in xs]
    bars = ax.bar([f"S{s}" for s in xs], ys, color=BLUE, ec=BORDER)
    bars[xs.index(T.TEST_SUBJECT)].set_color(ORANGE)
    ax.axhline(25, color=RED, ls="--", lw=1.2, label="chance (25%)")
    ax.axhline(mean_acc * 100, color=GREEN, ls="--", lw=1.2,
               label=f"mean ({mean_acc*100:.1f}%)")
    for b, v in zip(bars, ys):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}", ha="center",
                color=TEXT, fontsize=8.5)
    ax.set_ylabel("cross-subject accuracy (%)"); ax.set_ylim(0, max(ys) + 10)
    ax.set_title("Leave-one-subject-out — 4-channel EEGNet (subject 9 = held-out test)",
                 fontsize=12)
    ax.grid(True, axis="y", alpha=0.25); ax.legend(frameon=False, labelcolor=TEXT)
    _save(fig, "per_subject_accuracy.png")

    # ── Personal calibration (within-subject fine-tune on subject 9) ──────────
    print("\n[FIG] === personal calibration (within-subject 9 fine-tune) ===")
    X9, y9 = per_subj[T.TEST_SUBJECT]
    sss = StratifiedShuffleSplit(1, test_size=0.4, random_state=7)
    cal_idx, test_idx = next(sss.split(X9, y9))
    sss2 = StratifiedShuffleSplit(1, test_size=0.2, random_state=7)
    ct, cv = next(sss2.split(X9[cal_idx], y9[cal_idx]))
    Xct, yct = X9[cal_idx][ct], y9[cal_idx][ct]
    Xcv, ycv = X9[cal_idx][cv], y9[cal_idx][cv]
    Xte, yte = X9[test_idx], y9[test_idx]

    before_acc, before_cm = T.evaluate(model, Xte, yte, le, device)
    ft = copy.deepcopy(model)
    for p in ft.parameters():
        p.requires_grad = False
    for name, p in ft.named_parameters():
        if any(k in name for k in ["sep_depthwise", "sep_pointwise", "bn3", "classifier"]):
            p.requires_grad = True
    hist_ft = T.train(ft, Xct, yct, Xcv, ycv, "fig_calib", device)
    after_acc, after_cm = T.evaluate(ft, Xte, yte, le, device)
    metrics["calib_before_acc"] = round(float(before_acc), 4)
    metrics["calib_after_acc"]  = round(float(after_acc), 4)
    metrics["history_pretrain"] = {k: [round(float(v), 4) for v in vals]
                                   for k, vals in history.items()}
    metrics["history_calib"]    = {k: [round(float(v), 4) for v in vals]
                                   for k, vals in hist_ft.items()}

    # finetuning curves
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ep = range(1, len(hist_ft["val_acc"]) + 1)
    ax.plot(ep, [v * 100 for v in hist_ft["train_acc"]], color=BLUE, label="train")
    ax.plot(ep, [v * 100 for v in hist_ft["val_acc"]], color=ORANGE, label="val")
    ax.axhline(before_acc * 100, color=MUTED, ls="--", lw=1.2,
               label=f"pre-calibration ({before_acc*100:.0f}%)")
    ax.set_xlabel("epoch"); ax.set_ylabel("accuracy (%)")
    ax.set_title("Personal calibration — fine-tune Block 3 + head (subject 9)",
                 fontsize=12)
    ax.grid(True, alpha=0.25); ax.legend(frameon=False, labelcolor=TEXT)
    _save(fig, "finetuning_curves.png")

    # calibration impact (per-class before/after)
    bpc = [before_cm[i, i] / before_cm[i].sum() * 100 for i in range(4)]
    apc = [after_cm[i, i] / after_cm[i].sum() * 100 for i in range(4)]
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    x = np.arange(4); w = 0.36
    ax.bar(x - w/2, bpc, w, label="before", color=MUTED, ec=BORDER)
    ax.bar(x + w/2, apc, w, label="after",
           color=[CLASS_COLOR[c] for c in T.CLASS_NAMES], ec=BORDER)
    ax.set_xticks(x); ax.set_xticklabels([CLASS_FULL[c] for c in T.CLASS_NAMES])
    ax.set_ylabel("per-class accuracy (%)")
    ax.set_title(f"Calibration impact — overall {before_acc*100:.0f}% → "
                 f"{after_acc*100:.0f}% on subject 9", fontsize=12)
    ax.grid(True, axis="y", alpha=0.25); ax.legend(frameon=False, labelcolor=TEXT)
    _save(fig, "calibration_impact.png")

    METRICS.write_text(json.dumps(metrics, indent=2))
    print(f"\n[FIG] metrics → {METRICS.name}\n{json.dumps(metrics, indent=2)}")


# ==============================================================================
def main():
    schematic_only = "--schematic" in sys.argv
    print("[FIG] schematic figures ...")
    fig_channel_map()
    fig_eegnet_architecture()
    fig_dashboard_wireframe()
    if schematic_only:
        print("[FIG] --schematic: skipping performance figures."); return
    fig_performance()
    print("[FIG] done.")


if __name__ == "__main__":
    main()
