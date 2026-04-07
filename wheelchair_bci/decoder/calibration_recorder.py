"""
Wheelchair BCI — Kalibrasyon Veri Kaydedici (Node1 / Coral)
Node2 dashboard'undan gelen cue komutlarını dinleyerek,
imagery fazında EEG verisi kaydeder ve sonra fine-tune çalıştırır.
Kendi thread'inde çalışır, ana inference döngüsünü bloklamaz.
"""

import sys
import json
import time
import socket
from pathlib import Path
from datetime import datetime

import numpy as np

from wheelchair_bci.config import (
    CLASS_NAMES, CHANNELS, FS,
    UDP_CAL_PORT, UDP_CMD_PORT,
    BUFFER_SIZE, DSP_INTERVAL,
    MODELS_DIR, CAL_DATA_DIR,
)


class CalibrationRecorder:
    """
    Node2 dashboard'undan kalibrasyon komutları alır ve EEG kaydeder.

    Protokol akışı (Node2 → Node1 yönünde UDP):
        1. {"type": "cal_start", "n_trials": 100}  → kaydı başlat
        2. {"type": "cal_phase", "phase": "fixation", "trial": 1, "class": "L"}
        3. {"type": "cal_phase", "phase": "imagery",  "trial": 1, "class": "L"}
           → BU FAZDA VERİ KAYDEDİLİR
        4. {"type": "cal_phase", "phase": "rest", ...}
        5. ... (tüm denemeler için tekrarla)
        6. {"type": "cal_train"}  → fine-tune başlat
        7. {"type": "cal_stop"}   → iptal

    Imagery fazında SharedState'ten 1 saniyelik pencereler alınıp
    sınıf etiketi ile birlikte kaydedilir.
    """

    def __init__(self, shared_state, stop_event):
        """
        Parametreler:
            shared_state: SharedState nesnesi — filtrelenmiş EEG buffer'ı
            stop_event:   threading.Event — ana program durdurulunca bunu set eder
        """
        self.shared_state = shared_state
        self.stop_event = stop_event

        # Kayıt durumu
        self.recording = False          # Kalibrasyon aktif mi?
        self.current_class = None       # Şu an hangi sınıf kaydediliyor ("L", "R", ...)
        self.current_phase = None       # Şu an hangi faz ("fixation", "imagery", "rest")

        # Kaydedilen veriler
        self.windows = []               # EEG pencereleri listesi — her biri (250, 8)
        self.labels = []                # Sınıf etiketleri — ["L", "R", "F", ...]

        # UDP dinleyici — Node2'den kalibrasyon komutları alır
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", UDP_CAL_PORT))
        self.sock.settimeout(0.2)       # 200ms timeout — stop_event kontrolü için

        # Kalibrasyon verisi kayıt klasörü
        CAL_DATA_DIR.mkdir(parents=True, exist_ok=True)

        print(f"[CAL] Kalibrasyon dinleyici port {UDP_CAL_PORT}'de aktif")

    def run(self):
        """
        Ana kalibrasyon döngüsü — kendi thread'inde çalışır.
        İki işi paralel yapar:
          1. UDP paketlerini dinle (komutlar)
          2. Imagery fazındaysa EEG penceresi kaydet
        """
        while not self.stop_event.is_set():

            # ── UDP paket kontrolü ──
            try:
                data, addr = self.sock.recvfrom(1024)
                msg = json.loads(data.decode())
                self._handle_message(msg, addr)
            except socket.timeout:
                pass
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

            # ── Imagery fazında EEG kaydet ──
            if (self.recording
                    and self.current_phase == "imagery"
                    and self.current_class):

                if self.shared_state.is_ready:
                    buf = self.shared_state.snapshot()
                    if len(buf) >= BUFFER_SIZE:
                        window = np.array(buf, dtype=np.float64)
                        self.windows.append(window)
                        self.labels.append(self.current_class)
                        # Çakışan pencereler olmasın diye kısa bekle
                        time.sleep(DSP_INTERVAL)
                else:
                    time.sleep(0.01)
            else:
                time.sleep(0.01)

        self.sock.close()

    def _handle_message(self, msg: dict, addr: tuple):
        """Gelen UDP mesajını türüne göre işler."""
        msg_type = msg.get("type", "")

        if msg_type == "cal_start":
            # Kalibrasyon başlat — tamponları temizle
            n_trials = msg.get("n_trials", 100)
            print(f"[CAL] Kalibrasyon başladı ({n_trials} deneme)")
            self.windows = []
            self.labels = []
            self.recording = True

        elif msg_type == "cal_phase":
            # Faz değişikliği — fixation / imagery / rest
            self.current_phase = msg.get("phase", "")
            self.current_class = msg.get("class", "")
            trial = msg.get("trial", 0)

            if self.current_phase == "imagery":
                print(f"[CAL] Deneme {trial} — KAYIT class={self.current_class}")
            elif self.current_phase == "fixation":
                print(f"[CAL] Deneme {trial} — fixation")

        elif msg_type == "cal_train":
            # Kayıt bitti → fine-tune başlat
            self.recording = False
            self.current_phase = None
            print(
                f"[CAL] Kayıt tamamlandı: {len(self.windows)} pencere, "
                f"{len(set(self.labels))} sınıf"
            )
            self._save_and_finetune(addr)

        elif msg_type == "cal_stop":
            # İptal
            self.recording = False
            self.current_phase = None
            self.windows = []
            self.labels = []
            print("[CAL] Kalibrasyon iptal edildi")

    def _save_and_finetune(self, dashboard_addr: tuple):
        """Kaydedilen veriyi diske yaz ve fine-tune çalıştır."""
        if len(self.windows) == 0:
            print("[CAL] Veri yok, fine-tune atlanıyor")
            return

        # ── Veriyi kaydet (.npz) ──
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = CAL_DATA_DIR / f"cal_data_{timestamp}.npz"

        X = np.array(self.windows)   # (n_windows, 250, 8)
        y = np.array(self.labels)    # (n_windows,) string etiketler

        np.savez(save_path, X=X, y=y, channels=CHANNELS, fs=FS)
        print(f"[CAL] Kaydedildi: {save_path.name} — {len(X)} pencere")

        # Sınıf dağılımını göster
        for cls in CLASS_NAMES:
            count = int(np.sum(y == cls))
            print(f"  {cls}: {count}", end="")
        print()

        # ── Fine-tune ──
        print("[CAL] Fine-tune başlıyor...")
        base_acc, new_acc = self._run_finetune(X, y)

        # ── Sonuçları dashboard'a gönder ──
        result = json.dumps({
            "type": "cal_result",
            "accuracy": round(new_acc * 100, 1),
            "base_accuracy": round(base_acc * 100, 1),
        }).encode()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(result, (dashboard_addr[0], UDP_CMD_PORT))
            sock.close()
            print(
                f"[CAL] Sonuç gönderildi: "
                f"baz={base_acc*100:.1f}% → kişisel={new_acc*100:.1f}%"
            )
        except Exception as e:
            print(f"[CAL] Sonuç gönderilemedi: {e}")

    def _run_finetune(self, X_windows: np.ndarray, y_labels: np.ndarray):
        """
        Kaydedilen kalibrasyon verisiyle Block3 + classifier fine-tune.

        Parametreler:
            X_windows: (n, 250, 8) — ham filtrelenmiş EEG pencereleri
            y_labels:  (n,) — string sınıf etiketleri ("L", "R", "F", "S")

        Döndürür:
            (base_accuracy, new_accuracy) — test split üzerinde
        """
        try:
            import torch
            from sklearn.model_selection import StratifiedShuffleSplit

            from wheelchair_bci.decoder_training import EEGNet

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            # ── Model bul ──
            pt_models = sorted(MODELS_DIR.glob("*.pt"), reverse=True)
            if not pt_models:
                print("[CAL] Fine-tune için .pt model bulunamadı")
                return 0.0, 0.0

            base_path = pt_models[0]
            print(f"[CAL] Baz model: {base_path.name}")

            # ── Etiketleri sayısala çevir ──
            label_to_idx = {c: i for i, c in enumerate(CLASS_NAMES)}
            y_int = np.array([label_to_idx[l] for l in y_labels])

            # ── Veriyi hazırla: (n,250,8) → (n,1,8,250), V→µV ──
            X_4d = X_windows.transpose(0, 2, 1)[:, np.newaxis, :, :].astype(np.float32) * 1e6

            # ── Train/Val/Test split: %70 / %15 / %15 ──
            sss1 = StratifiedShuffleSplit(n_splits=1, test_size=0.3, random_state=42)
            tr_idx, tmp_idx = next(sss1.split(X_4d, y_int))

            sss2 = StratifiedShuffleSplit(n_splits=1, test_size=0.5, random_state=42)
            vl_sub, te_sub = next(sss2.split(X_4d[tmp_idx], y_int[tmp_idx]))
            vl_idx = tmp_idx[vl_sub]
            te_idx = tmp_idx[te_sub]

            X_tr, y_tr = X_4d[tr_idx], y_int[tr_idx]
            X_val, y_val = X_4d[vl_idx], y_int[vl_idx]
            X_te, y_te = X_4d[te_idx], y_int[te_idx]

            print(f"[CAL] Train: {len(X_tr)} | Val: {len(X_val)} | Test: {len(X_te)}")

            # ── Baz model yükle ──
            model = EEGNet()
            model.load_state_dict(torch.load(str(base_path), weights_only=True))
            model.to(device).eval()

            # Baz doğruluk
            with torch.no_grad():
                logits = model(torch.from_numpy(X_te).float().to(device))
                base_preds = logits.argmax(1).cpu().numpy()
            base_acc = float(np.mean(base_preds == y_te))

            # ── Block3 + classifier aç, kalanı dondur ──
            for param in model.parameters():
                param.requires_grad = False
            for name, param in model.named_parameters():
                if any(k in name for k in ["sep_depthwise", "sep_pointwise",
                                            "bn3", "classifier"]):
                    param.requires_grad = True

            # ── Fine-tune ──
            from wheelchair_bci.decoder_calibrate import finetune_train
            model = finetune_train(model, X_tr, y_tr, X_val, y_val, device)

            # Yeni doğruluk
            model.eval()
            with torch.no_grad():
                logits = model(torch.from_numpy(X_te).float().to(device))
                new_preds = logits.argmax(1).cpu().numpy()
            new_acc = float(np.mean(new_preds == y_te))

            # ── Kişisel modeli kaydet ──
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_name = f"EEGNet_personal_{ts}.pt"
            torch.save(model.state_dict(), str(MODELS_DIR / save_name))
            print(f"[CAL] Kaydedildi: {save_name}")
            print(f"[CAL] Baz: {base_acc*100:.1f}% → Kişisel: {new_acc*100:.1f}%")

            return base_acc, new_acc

        except Exception as e:
            print(f"[CAL] Fine-tune hatası: {e}")
            import traceback
            traceback.print_exc()
            return 0.0, 0.0
