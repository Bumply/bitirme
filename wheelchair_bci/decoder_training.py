"""
Wheelchair BCI — EEGNet Model Tanımı ve Eğitim Pipeline'ı
MNE ile BCI Competition verisini okur, PyTorch ile EEGNet'i eğitir,
eğitilmiş modeli models/ klasörüne kaydeder.

Kullanım:
    python -m wheelchair_bci.decoder_training

Hakkında:
    EEGNet, V. Lawhern ve ark. (2018) tarafından EEG sinyallerine
    özel tasarlanmış hafif bir CNN mimarisidir.
    ~2000 parametre ile saniyeler içinde inference yapar.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import TensorDataset, DataLoader

from wheelchair_bci.config import (
    FS, N_CH, CHANNELS, CLASS_NAMES,
    BUFFER_SIZE, BANDPASS_LOW, BANDPASS_HIGH,
    MODELS_DIR, PROJECT_ROOT,
)


# ══════════════════════════════════════════════════
# 1. EEGNet MODEL MİMARİSİ
# ══════════════════════════════════════════════════

class EEGNet(nn.Module):
    """
    EEGNet — EEG sinyallerine özel hafif CNN.

    Mimari 3 bloktan oluşur:

    Block 1 — Temporal Convolution
        Bireysel frekans bileşenlerini yakalar (µ ritmi, beta vs.)
        Çıkış: F1 adet zaman filtresi

    Block 2 — Depthwise + Separable Convolution
        Her frekans filtresini uzamsal (kanal) boyutunda genişletir.
        Beynin farklı bölgeleri arasındaki bağlantıları öğrenir.
        DepthwiseConv: her filtre sadece kendi kanal grubuna bakar → verimli

    Block 3 — Separable Convolution
        Kişiye özel özellikler çıkarır.
        Online adaptasyonda SADECE bu katman güncellenir.

    Classifier — Fully Connected (Linear)
        Son özellikleri 4 sınıfa (F, L, R, S) eşler.

    Parametreler:
        n_channels:  EEG kanal sayısı (varsayılan 8)
        n_samples:   Zaman noktası sayısı (varsayılan 250 = 1 saniye)
        n_classes:   Sınıf sayısı (varsayılan 4: F, L, R, S)
        F1:          Block1 filtre sayısı (varsayılan 8)
        D:           Depthwise çarpanı (varsayılan 2 → F2 = F1*D = 16)
        dropout:     Dropout oranı (varsayılan 0.25)
    """

    def __init__(self, n_channels=N_CH, n_samples=BUFFER_SIZE,
                 n_classes=4, F1=8, D=2, dropout=0.25):
        super().__init__()

        F2 = F1 * D    # Block2 çıkış filtre sayısı = 16

        # ── Block 1: Temporal Convolution ──
        # Zaman boyutunda (250 nokta) 64 uzunluklu filtre uygular
        # padding="same" ile giriş/çıkış boyutu korunur
        self.conv1 = nn.Conv2d(1, F1, (1, 64), padding="same", bias=False)
        self.bn1 = nn.BatchNorm2d(F1)

        # ── Block 2: Depthwise Convolution ──
        # Her F1 filtresini D=2 kez uzamsal (kanal) boyutunda genişletir
        # groups=F1 → depthwise: her filtre sadece kendi kanalına bakar
        self.depthwise = nn.Conv2d(F1, F2, (n_channels, 1),
                                   groups=F1, bias=False)
        self.bn2 = nn.BatchNorm2d(F2)
        self.pool1 = nn.AvgPool2d((1, 4))       # Zaman boyutunu 4x küçült
        self.drop1 = nn.Dropout(dropout)

        # ── Block 3: Separable Convolution ──
        # Depthwise + Pointwise ile kişiye özel özellikler çıkarır
        # Online adaptasyonda BU KATMAN güncellenir
        self.sep_depthwise = nn.Conv2d(F2, F2, (1, 16),
                                       padding="same", groups=F2, bias=False)
        self.sep_pointwise = nn.Conv2d(F2, F2, (1, 1), bias=False)
        self.bn3 = nn.BatchNorm2d(F2)
        self.pool2 = nn.AvgPool2d((1, 8))        # Zaman boyutunu 8x daha küçült
        self.drop2 = nn.Dropout(dropout)

        # ── Classifier ──
        # Son özellik haritasını düzleştirip 4 sınıfa eşle
        # 250 / 4 / 8 = ~7 zaman noktası kaldı → F2 * 7 = 112 özellik
        n_flat = F2 * (n_samples // 32)
        self.classifier = nn.Linear(n_flat, n_classes)

        # Max-norm constraint (EEGNet orijinal makalesindeki regularizasyon)
        self._max_norm_val = 0.25

    def forward(self, x):
        """
        İleri geçiş.

        Girdi:  x shape (batch, 1, 8, 250) — EEG verisi (µV)
        Çıkış:  logits shape (batch, 4) — ham sınıf skorları
        """
        # Block 1
        x = self.conv1(x)
        x = self.bn1(x)

        # Block 2
        x = self.depthwise(x)
        x = self.bn2(x)
        x = F.elu(x)
        x = self.pool1(x)
        x = self.drop1(x)

        # Block 3
        x = self.sep_depthwise(x)
        x = self.sep_pointwise(x)
        x = self.bn3(x)
        x = F.elu(x)
        x = self.pool2(x)
        x = self.drop2(x)

        # Flatten + Classifier
        x = x.flatten(1)
        x = self.classifier(x)
        return x

    def apply_max_norm(self):
        """
        Max-norm constraint — ağırlıkları belirli bir büyüklüğün
        altında tutar. Aşırı öğrenmeyi (overfitting) önler.
        EEGNet orijinal makalesinde önerilen regularizasyon tekniği.
        """
        for name, param in self.named_parameters():
            if "weight" in name and param.dim() >= 2:
                with torch.no_grad():
                    norms = param.norm(2, dim=0, keepdim=True)
                    desired = torch.clamp(norms, max=self._max_norm_val)
                    param.mul_(desired / (norms + 1e-8))


# ══════════════════════════════════════════════════
# 2. VERİ YÜKLEME (MNE İLE)
# ══════════════════════════════════════════════════

def load_bci_data(gdf_path: str, subjects: list[str] = None):
    """
    BCI Competition IV 2a veri setini MNE ile yükler.

    Bu veri setinde 9 kişinin 4-sınıflı motor imagery (MI) deneyleri var:
      769 = Sol el    → L
      770 = Sağ el    → R
      771 = Her iki ayak → F (İleri)
      772 = Dil        → S (Dur)

    Parametreler:
        gdf_path:  GDF dosyalarının bulunduğu klasör yolu
        subjects:  ["A01", "A02", ...] — hangi deneklerin yükleneceği

    Döndürür:
        X: np.ndarray (n_epochs, 1, n_channels, n_samples) — float32, µV
        y: np.ndarray (n_epochs,) — int64, sınıf indeksleri [0,1,2,3]
    """
    import mne

    if subjects is None:
        subjects = ["A01"]

    all_X, all_y = [], []

    # Olay ID → sınıf indeksi eşlemesi
    event_mapping = {769: 0, 770: 1, 771: 2, 772: 3}
    # Sınıf isimleri: 0=F(ayak→ileri), 1=L(sol el), 2=R(sağ el), 3=S(dil→dur)
    # NOT: BCI Comp'ta sol el=769 ama biz onu "Forward" (ayak) olarak eşliyoruz
    # Eşleme config.py'deki CLASS_NAMES = ["F", "L", "R", "S"] sırasına uyar

    gdf_dir = Path(gdf_path)

    for subj in subjects:
        fname = gdf_dir / f"{subj}T.gdf"
        if not fname.exists():
            print(f"  [SKIP] {fname.name} bulunamadı")
            continue

        print(f"  [MNE] Yükleniyor: {fname.name}")

        # ── GDF'yi oku ──
        raw = mne.io.read_raw_gdf(str(fname), preload=True, verbose=False)

        # ── Sadece EEG kanallarını al ──
        # BCI Comp 2a'da ilk 22 kanal EEG, kalanı EOG
        eeg_ch_names = raw.ch_names[:22]
        raw.pick(eeg_ch_names)

        # ── Bizim 8 kanalımızla eşleştir ──
        # BCI Comp kanalları: Fz, FC3, FC1, FCz, FC2, FC4, C5, C3, C1, Cz, C2, C4, ...
        # Bizim kanallarımız config.py'de tanımlı
        our_channels = []
        for ch in CHANNELS:
            # Büyük/küçük harf farklarını tolere et
            matches = [c for c in raw.ch_names
                       if c.upper().replace("EEG-", "") == ch.upper()]
            if matches:
                our_channels.append(matches[0])

        if len(our_channels) < N_CH:
            # Yeterli kanal yoksa ilk N_CH kanalı al
            print(f"  [WARN] Sadece {len(our_channels)}/{N_CH} kanal eşleşti, "
                  f"ilk {N_CH} kanal kullanılıyor")
            our_channels = raw.ch_names[:N_CH]

        raw.pick(our_channels)

        # ── Bandpass filtre (MNE dahili) ──
        raw.filter(BANDPASS_LOW, BANDPASS_HIGH, verbose=False)

        # ── Olayları bul ve epoch'la ──
        events, event_dict = mne.events_from_annotations(raw, verbose=False)

        # Olay kodlarını integer'a çevir
        int_event_dict = {}
        for key, val in event_dict.items():
            try:
                int_key = int(float(key))
                if int_key in event_mapping:
                    int_event_dict[str(int_key)] = val
            except ValueError:
                continue

        if not int_event_dict:
            print(f"  [WARN] {fname.name} — MI olayları bulunamadı, atlıyorum")
            continue

        # Epoch: olay başlangıcından 0-1 saniye arası
        epochs = mne.Epochs(
            raw, events,
            event_id={k: v for k, v in event_dict.items() if k in int_event_dict},
            tmin=0.0, tmax=BUFFER_SIZE / FS - 1 / FS,  # 0 - 0.996s
            baseline=None,
            preload=True,
            verbose=False,
        )

        # Epoch verisini numpy'a çevir
        X_subj = epochs.get_data()    # (n_epochs, n_channels, n_samples)

        # Etiketleri ayarla
        y_subj_raw = epochs.events[:, 2]  # MNE olay kodları
        # MNE olay kodlarını bizim sınıf indekslerine çevir
        reverse_map = {v: event_mapping.get(int(float(k)), -1)
                       for k, v in event_dict.items()
                       if k in int_event_dict}
        y_subj = np.array([reverse_map.get(ev, -1) for ev in y_subj_raw])

        # Geçersiz etiketleri filtrele
        valid = y_subj >= 0
        X_subj = X_subj[valid]
        y_subj = y_subj[valid]

        print(f"  [MNE] {fname.name}: {len(X_subj)} epoch, "
              f"dağılım={[int(np.sum(y_subj == i)) for i in range(4)]}")

        all_X.append(X_subj)
        all_y.append(y_subj)

    # Tüm denekleri birleştir
    X = np.concatenate(all_X, axis=0)    # (n_total, 8, 250)
    y = np.concatenate(all_y, axis=0)    # (n_total,)

    # Volt → µV dönüşümü ve kanal boyutu ekleme
    # (n, 8, 250) → (n, 1, 8, 250)
    X = X[:, np.newaxis, :, :].astype(np.float32) * 1e6

    print(f"\n  Toplam: {len(X)} epoch, shape={X.shape}")
    return X, y


def load_bci_data_moabb(train_subjects: list[int] = None,
                        test_subject: int = 9):
    """
    MOABB ile BCI Competition IV-2a verisini otomatik indirir ve yükler.
    Cross-subject eğitim: birden fazla kişi verisiyle genel model eğitilir.

    MOABB avantajları:
      - Veriyi internetten otomatik indirir ve önbelleğe alır
      - Kanal seçimi, resampling, bandpass otomatik yapılır
      - 9 kişinin tamamı erişilebilir

    Parametreler:
        train_subjects: Eğitim için kullanılacak kişi numaraları [1-9]
                        Varsayılan: [1,2,3,4,5,6,7,8]
        test_subject:   Test için ayrılan kişi (varsayılan: 9)

    Döndürür:
        X_train, y_train, X_test, y_test
        Her biri (n, 1, n_ch, 250) shape'inde, µV cinsinden
    """
    import mne
    mne.set_log_level("WARNING")

    try:
        import moabb
        moabb.set_log_level("WARNING")
    except Exception:
        pass

    from moabb.datasets import BNCI2014_001
    from moabb.paradigms import MotorImagery

    if train_subjects is None:
        train_subjects = [s for s in range(1, 10) if s != test_subject]

    # MOABB olay eşlemesi
    EVENT_MAP = {
        "left_hand":  "L",
        "right_hand": "R",
        "feet":       "F",
        "tongue":     "S",
    }

    # Paradigma tanımı — MOABB kanal seçimi, resampling ve bandpass yapar
    paradigm = MotorImagery(
        events    = list(EVENT_MAP.keys()),
        n_classes = 4,
        fmin      = float(BANDPASS_LOW),
        fmax      = float(BANDPASS_HIGH),
        tmin      = 0.5,     # İlk 0.5s'yi atla (görsel evoked potansiyel)
        tmax      = 4.0,     # Trial sonu
        channels  = CHANNELS,
        resample  = float(FS),
    )

    dataset = BNCI2014_001()

    def _load_and_window(subjects, label):
        """Kişileri yükle, 1s pencerelerine böl, etiketle."""
        print(f"\n  [{label}] Kişiler yükleniyor: {subjects}")
        X_raw, y_raw, _ = paradigm.get_data(dataset=dataset, subjects=subjects)
        y_str = np.array([EVENT_MAP[lbl] for lbl in y_raw])

        # 1 saniyelik pencereler (50% overlap)
        window = BUFFER_SIZE             # 250 sample = 1s
        stride = BUFFER_SIZE // 2        # 125 sample = 0.5s overlap
        n_trials, n_ch_raw, n_tp = X_raw.shape

        xs, ys = [], []
        for i in range(n_trials):
            start = 0
            while start + window <= n_tp:
                xs.append(X_raw[i, :, start:start + window])
                ys.append(y_str[i])
                start += stride

        X_seg = np.array(xs, dtype=np.float32)   # (n_windows, n_ch, 250)
        y_seg = np.array(ys)

        # String etiketleri indekse çevir: F=0, L=1, R=2, S=3
        label_to_idx = {c: i for i, c in enumerate(CLASS_NAMES)}
        y_int = np.array([label_to_idx[c] for c in y_seg], dtype=np.int64)

        # (n, n_ch, 250) → (n, 1, n_ch, 250) + volt → µV
        X_4d = X_seg[:, np.newaxis, :, :] * 1e6

        dist = {CLASS_NAMES[i]: int(np.sum(y_int == i)) for i in range(4)}
        print(f"  [{label}] {len(X_4d)} pencere | Dağılım: {dist}")
        return X_4d, y_int

    X_train, y_train = _load_and_window(train_subjects, "EĞİTİM")
    X_test, y_test = _load_and_window([test_subject], "TEST")

    return X_train, y_train, X_test, y_test


# ══════════════════════════════════════════════════
# 3. EĞİTİM DÖNGÜSÜ
# ══════════════════════════════════════════════════

def train_model(X: np.ndarray, y: np.ndarray,
                epochs: int = 100, batch_size: int = 32,
                lr: float = 1e-3, patience: int = 15):
    """
    EEGNet'i verilen veriyle eğitir.

    Parametreler:
        X: np.ndarray (n, 1, 8, 250) — eğitim verisi (µV cinsinden)
        y: np.ndarray (n,) — sınıf etiketleri (0-3)
        epochs:     Maksimum eğitim döngüsü sayısı
        batch_size: Mini-batch boyutu
        lr:         Öğrenme oranı
        patience:   Early stopping sabrı — doğrulama iyileşmezse dur

    Döndürür:
        (model, history) çifti
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n[TRAIN] Cihaz: {device}")

    # ── Train / Validation split (%80 / %20) ──
    from sklearn.model_selection import StratifiedShuffleSplit

    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    tr_idx, vl_idx = next(sss.split(X, y))

    X_tr, y_tr = torch.from_numpy(X[tr_idx]).float(), torch.from_numpy(y[tr_idx]).long()
    X_vl, y_vl = torch.from_numpy(X[vl_idx]).float(), torch.from_numpy(y[vl_idx]).long()

    train_loader = DataLoader(
        TensorDataset(X_tr, y_tr),
        batch_size=batch_size, shuffle=True, drop_last=True,
    )
    val_loader = DataLoader(
        TensorDataset(X_vl, y_vl),
        batch_size=batch_size, shuffle=False,
    )

    print(f"[TRAIN] Eğitim: {len(X_tr)} | Doğrulama: {len(X_vl)}")

    # ── Model, optimizer, loss ──
    model = EEGNet().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=5,
    )
    criterion = nn.CrossEntropyLoss()

    total_params = sum(p.numel() for p in model.parameters())
    print(f"[TRAIN] Model parametresi: {total_params:,}")

    # ── Eğitim döngüsü ──
    best_val_loss = float("inf")
    best_state = None
    no_improve = 0
    history = {"train_loss": [], "val_loss": [], "val_acc": []}

    for epoch in range(1, epochs + 1):
        # — Eğitim fazı —
        model.train()
        train_losses = []

        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)

            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            model.apply_max_norm()

            train_losses.append(loss.item())

        # — Doğrulama fazı —
        model.eval()
        val_losses, val_correct, val_total = [], 0, 0

        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                logits = model(xb)
                loss = criterion(logits, yb)
                val_losses.append(loss.item())

                preds = logits.argmax(1)
                val_correct += (preds == yb).sum().item()
                val_total += len(yb)

        train_loss_avg = np.mean(train_losses)
        val_loss_avg = np.mean(val_losses)
        val_acc = val_correct / max(val_total, 1)

        history["train_loss"].append(train_loss_avg)
        history["val_loss"].append(val_loss_avg)
        history["val_acc"].append(val_acc)

        scheduler.step(val_loss_avg)

        # Her 10 epoch'ta veya son epoch'ta logla
        if epoch % 10 == 0 or epoch == 1:
            current_lr = optimizer.param_groups[0]["lr"]
            print(
                f"  Epoch {epoch:3d}/{epochs} | "
                f"train_loss={train_loss_avg:.4f} | "
                f"val_loss={val_loss_avg:.4f} | "
                f"val_acc={val_acc*100:.1f}% | "
                f"lr={current_lr:.1e}"
            )

        # — Early stopping —
        if val_loss_avg < best_val_loss:
            best_val_loss = val_loss_avg
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                print(f"\n  [EARLY STOP] {patience} epoch iyileşme yok, durduruluyor.")
                break

    # En iyi modeli geri yükle
    if best_state:
        model.load_state_dict(best_state)
        model.to(device)

    final_acc = max(history["val_acc"])
    print(f"\n[TRAIN] Bitti! En iyi doğrulama: {final_acc*100:.1f}%")

    return model, history


# ══════════════════════════════════════════════════
# 4. MODEL KAYDETME
# ══════════════════════════════════════════════════

def save_model(model: EEGNet, tag: str = "base"):
    """
    Eğitilmiş modeli models/ klasörüne kaydeder.

    Dosya adı formatı: EEGNet_{tag}_{tarih}.pt
    Örnek: EEGNet_base_20260322_1123.pt
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"EEGNet_{tag}_{timestamp}.pt"
    save_path = MODELS_DIR / filename

    torch.save(model.state_dict(), str(save_path))
    print(f"[SAVE] Model kaydedildi: {save_path}")

    return save_path


# ══════════════════════════════════════════════════
# 4b. ONNX ve TFLite EXPORT
# ══════════════════════════════════════════════════

def export_models(model: EEGNet, X_cal: np.ndarray, base_name: str = "base"):
    """
    Eğitilmiş modeli birden fazla formata export eder:

    1. ONNX  (.onnx)          — Evrensel format, doğrulama amaçlı
    2. TFLite Float32 (.tflite) — Herhangi bir cihazda çalışır
    3. TFLite Int8 (_int8.tflite) — Edge TPU için tam kuantize

    Edge TPU'da çalıştırmak için son adım (Coral üzerinde):
        $ edgetpu_compiler {base_name}_int8.tflite
        → {base_name}_int8_edgetpu.tflite üretir

    Parametreler:
        model:  Eğitilmiş EEGNet modeli
        X_cal:  np.ndarray (n, 1, 8, 250) — int8 kalibrasyon verisi
        base_name: "EEGNet_base_20260322_1123" gibi kök isim
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    onnx_path = MODELS_DIR / f"{base_name}.onnx"
    f32_path  = MODELS_DIR / f"{base_name}.tflite"
    i8_path   = MODELS_DIR / f"{base_name}_int8.tflite"

    model.eval()
    model_cpu = model.to("cpu")

    # ── Adım 1: ONNX Export ──
    print("\n[EXPORT] ONNX export başlıyor...")
    try:
        dummy_input = torch.randn(1, 1, N_CH, BUFFER_SIZE)
        torch.onnx.export(
            model_cpu, dummy_input, str(onnx_path),
            input_names=["eeg_input"],
            output_names=["logits"],
            dynamic_axes={"eeg_input": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=13,
        )
        onnx_size = onnx_path.stat().st_size / 1024
        print(f"[EXPORT] ✅ ONNX   → {onnx_path.name}  ({onnx_size:.1f} KB)")
    except Exception as e:
        print(f"[EXPORT] ❌ ONNX export başarısız: {e}")
        return

    # ── Adım 2 & 3: TFLite Float32 + Int8 ──
    print("[EXPORT] TFLite dönüşümü başlıyor...")
    try:
        import tensorflow as tf
        import onnx
        from onnx_tf.backend import prepare as onnx_tf_prepare

        # ONNX → TensorFlow SavedModel
        onnx_model = onnx.load(str(onnx_path))
        tf_rep = onnx_tf_prepare(onnx_model)
        saved_model_dir = str(MODELS_DIR / f"_tmp_savedmodel_{tag}")
        tf_rep.export_graph(saved_model_dir)

        # Float32 TFLite
        converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
        f32_bytes = converter.convert()
        f32_path.write_bytes(f32_bytes)
        print(f"[EXPORT] ✅ Float32 → {f32_path.name}  ({len(f32_bytes)/1024:.1f} KB)")

        # Int8 kuantize TFLite (Edge TPU için)
        def rep_data_gen():
            """Kuantizasyon kalibrasyonu için temsili veri üreteci."""
            for i in range(min(200, len(X_cal))):
                yield [X_cal[i:i+1].astype(np.float32)]

        converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.representative_dataset = rep_data_gen
        converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = tf.int8
        converter.inference_output_type = tf.int8
        i8_bytes = converter.convert()
        i8_path.write_bytes(i8_bytes)
        print(f"[EXPORT] ✅ Int8    → {i8_path.name}  ({len(i8_bytes)/1024:.1f} KB)")

        # Geçici SavedModel klasörünü temizle
        import shutil
        shutil.rmtree(saved_model_dir, ignore_errors=True)

        print(f"\n[EXPORT] *** SONRAKİ ADIM — Coral (Linux) üzerinde ***")
        print(f"[EXPORT]   edgetpu_compiler {i8_path.name}")
        print(f"[EXPORT] → üretir: {i8_path.stem}_edgetpu.tflite")

    except ImportError:
        print(f"\n[EXPORT] ⚠️  TFLite dönüşümü atlandı (tensorflow/onnx/onnx-tf yüklü değil)")
        print(f"[EXPORT] ONNX dosyası kaydedildi, daha sonra dönüştürülebilir.")
        print(f"[EXPORT] Gerekli paketler:")
        print(f"[EXPORT]   pip install tensorflow onnx onnx-tf")
    except Exception as e:
        print(f"\n[EXPORT] ❌ TFLite dönüşümü başarısız: {e}")
        print(f"[EXPORT] ONNX dosyası ({onnx_path.name}) ile manuel dönüştürme yapabilirsiniz.")


# ══════════════════════════════════════════════════
# 4c. DİNAMİK EŞİK & METRİKLER
# ══════════════════════════════════════════════════

def export_metrics(model: EEGNet, X_cal: np.ndarray, base_name: str):
    """
    Modelin kalibrasyon verisi üzerindeki ortalama güven skorlarını hesaplar
    ve dinamik güven eşiğini (mean - std) hesaplayarak JSON kaydeder.
    """
    import json
    
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = MODELS_DIR / f"{base_name}_metrics.json"

    model.eval()
    device = next(model.parameters()).device
    with torch.no_grad():
        x_t = torch.from_numpy(X_cal).float().to(device)
        
        # OOM önlemek için batch işleme
        probs_list = []
        for i in range(0, len(x_t), 128):
            batch = x_t[i:i+128]
            logits = model(batch)
            probs = torch.softmax(logits, dim=1).max(dim=1).values.cpu().numpy()
            probs_list.append(probs)
        all_probs = np.concatenate(probs_list)

    mean_conf = float(np.mean(all_probs))
    std_conf = float(np.std(all_probs))
    
    # Dinamik eşik: ortalamadan 1 standart sapma aşağısı
    dyn_thresh = mean_conf - std_conf
    dyn_thresh = max(0.40, min(0.90, dyn_thresh))  # Makul limitler

    stats = {
        "mean_confidence": round(mean_conf, 3),
        "std_confidence": round(std_conf, 3),
        "dynamic_threshold": round(dyn_thresh, 3),
        "samples": len(X_cal)
    }

    with open(json_path, "w") as f:
        json.dump(stats, f, indent=4)
        
    print(f"[EXPORT] ✅ Metrikler → {json_path.name}")
    print(f"[EXPORT]    Dinamik Güven Eşiği: {dyn_thresh:.3f}")


# ══════════════════════════════════════════════════
# 4c. DİNAMİK EŞİK & METRİKLER
# ══════════════════════════════════════════════════

def export_metrics(model: EEGNet, X_cal: np.ndarray, base_name: str):
    """
    Modelin kalibrasyon verisi üzerindeki ortalama güven skorlarını hesaplar
    ve dinamik güven eşiğini (mean - std) hesaplayarak JSON kaydeder.
    """
    import json
    
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = MODELS_DIR / f"{base_name}_metrics.json"

    model.eval()
    device = next(model.parameters()).device
    with torch.no_grad():
        x_t = torch.from_numpy(X_cal).float().to(device)
        
        # OOM önlemek için batch işleme
        probs_list = []
        for i in range(0, len(x_t), 128):
            batch = x_t[i:i+128]
            logits = model(batch)
            probs = torch.softmax(logits, dim=1).max(dim=1).values.cpu().numpy()
            probs_list.append(probs)
        all_probs = np.concatenate(probs_list)

    mean_conf = float(np.mean(all_probs))
    std_conf = float(np.std(all_probs))
    
    # Dinamik eşik: ortalamadan 1 standart sapma aşağısı
    dyn_thresh = mean_conf - std_conf
    dyn_thresh = max(0.40, min(0.90, dyn_thresh))  # Makul limitler

    stats = {
        "mean_confidence": round(mean_conf, 3),
        "std_confidence": round(std_conf, 3),
        "dynamic_threshold": round(dyn_thresh, 3),
        "samples": len(X_cal)
    }

    with open(json_path, "w") as f:
        json.dump(stats, f, indent=4)
        
    print(f"[EXPORT] ✅ Metrikler → {json_path.name}")
    print(f"[EXPORT]    Dinamik Güven Eşiği: {dyn_thresh:.3f}")


# ══════════════════════════════════════════════════
# 5. ANA ÇALIŞTIRMA
# ══════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="EEGNet Eğitim Pipeline")
    parser.add_argument("--personal", action="store_true",
                        help="calibration_data/ içindeki kişisel veriden eğit")
    parser.add_argument("--moabb", action="store_true",
                        help="MOABB ile 8 kişi cross-subject eğitim (otomatik indirir)")
    args = parser.parse_args()

    # Mod belirleme
    if args.personal:
        mode_str = "KİŞİSEL (--personal)"
    elif args.moabb:
        mode_str = "CROSS-SUBJECT (--moabb, 8 kişi eğitim, 1 kişi test)"
    else:
        mode_str = "GENEL (tek kişi GDF)"

    print("=" * 60)
    print("  WHEELCHAIR BCI — EEGNet EĞİTİM PIPELINE")
    print(f"  Mod: {mode_str}")
    print("=" * 60)

    if args.personal:
        # ── Kişisel veri ile eğitim ──
        from wheelchair_bci.config import CAL_DATA_DIR

        npz_files = sorted(CAL_DATA_DIR.glob("personal_*.npz"), reverse=True)
        if not npz_files:
            print(f"\n[ERROR] calibration_data/ içinde personal_*.npz bulunamadı!")
            print("Önce offline_logger.py ile veri toplayın:")
            print("  python -m wheelchair_bci.offline_logger")
            return

        latest = npz_files[0]
        print(f"\n[1/4] Kişisel veri yükleniyor: {latest.name}")

        data = np.load(str(latest))
        X = data["X"]
        y = data["y"]
        tag = "personal"

        dist = {CLASS_NAMES[i]: int(np.sum(y == i)) for i in range(4)}
        print(f"  Shape: {X.shape}")
        print(f"  Dağılım: {dist}")

    elif args.moabb:
        # ── MOABB cross-subject eğitim ──
        print(f"\n[1/4] MOABB ile veri indiriliyor (ilk çalıştırmada ~50MB)...")
        t0 = time.time()
        X_train, y_train, X_test, y_test = load_bci_data_moabb()
        print(f"  Süre: {time.time()-t0:.1f}s")

        # Cross-subject: eğit ve sonra test doğruluğunu rapor et
        tag = "pretrain"
        print(f"\n[2/4] EEGNet eğitiliyor ({tag}, {len(X_train)} pencere)...")
        t0 = time.time()
        model, history = train_model(X_train, y_train,
                                     epochs=200, batch_size=64, lr=1e-3,
                                     patience=25)
        print(f"  Süre: {time.time()-t0:.1f}s")

        # Test kişisi üzerinde doğruluk
        import torch
        model.eval()
        device = next(model.parameters()).device
        with torch.no_grad():
            x_te = torch.from_numpy(X_test).float().to(device)
            logits = model(x_te)
            preds = logits.argmax(1).cpu().numpy()
            test_acc = (preds == y_test).mean()
        print(f"\n  [TEST] Görülmemiş kişi doğruluğu: {test_acc*100:.1f}%")

        # Kaydet + Export
        print(f"\n[3/4] Model kaydediliyor ({tag})...")
        save_path = save_model(model, tag=tag)

        print(f"\n[4/4] Model export ediliyor (ONNX → TFLite)...")
        export_models(model, X_train, save_path.stem)

        print(f"\n[5/5] Dinamik Eşik hesaplanıyor...")
        export_metrics(model, X_train, save_path.stem)

        print("\n" + "=" * 60)
        print(f"  TAMAMLANDI! Model: {save_path.name}")
        print(f"  Test doğruluğu: {test_acc*100:.1f}%")
        print("  Şimdi Decoder'ı çalıştırabilirsiniz:")
        print("    python -m wheelchair_bci.decoder.main")
        print("=" * 60)
        return

    else:
        # ── BCI Competition GDF verisi ile eğitim ──
        data_dir = PROJECT_ROOT / "Data"
        if not data_dir.exists():
            print(f"\n[ERROR] Veri klasörü bulunamadı: {data_dir}")
            print("BCI Competition IV 2a veri setini Data/ klasörüne koyun.")
            print("  Alternatif: python -m wheelchair_bci.decoder_training --moabb")
            return

        print("\n[1/4] Veri yükleniyor...")
        t0 = time.time()
        X, y = load_bci_data(str(data_dir), subjects=["A01"])
        print(f"  Süre: {time.time()-t0:.1f}s")
        tag = "base"

    # ── Eğit ──
    print(f"\n[2/4] EEGNet eğitiliyor ({tag})...")
    t0 = time.time()
    model, history = train_model(X, y, epochs=100, batch_size=32, lr=1e-3)
    print(f"  Süre: {time.time()-t0:.1f}s")

    # ── Kaydet ──
    print(f"\n[3/5] Model kaydediliyor ({tag})...")
    save_path = save_model(model, tag=tag)
    base_name = save_path.stem

    # ── Export (ONNX + TFLite) ──
    print(f"\n[4/5] Model export ediliyor (ONNX → TFLite)...")
    export_models(model, X, base_name)

    # ── Dinamik Eşik (Metrics) ──
    print(f"\n[5/5] Dinamik eşik hesaplanıyor...")
    export_metrics(model, X, base_name)

    print("\n" + "=" * 60)
    print(f"  TAMAMLANDI! Model: {save_path.name}")
    print("  Şimdi Decoder'ı çalıştırabilirsiniz:")
    print("    python -m wheelchair_bci.decoder.main")
    print("=" * 60)


if __name__ == "__main__":
    main()

