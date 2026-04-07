"""
Wheelchair BCI — Kalibrasyon Protokol Motoru (Controller / Pi 5)
Dashboard'dan başlatılan kalibrasyon sürecini yönetir.
Kullanıcıya görsel cue'lar gösterirken, Decoder'a (Coral) hangi fazda
ne kaydedileceğini UDP üzerinden bildirir.

Protokol akışı (her deneme için):
  1. FIXATION (2s):  "+"  → kullanıcı ekrana odaklanır
  2. IMAGERY  (4s):  "←"  → kullanıcı motor hayal yapar, Decoder EEG kaydeder
  3. REST     (2s):  "~"  → dinlenme, artefakt önleme

Toplam: 25 deneme × 4 sınıf = 100 deneme ≈ 13 dakika
"""

import json
import time
import random
import socket
import threading

from wheelchair_bci.config import (
    CLASS_NAMES,
    DECODER_IP, UDP_CAL_PORT,
    CAL_FIXATION_S, CAL_IMAGERY_S, CAL_REST_S,
    CAL_TRIALS_PER_CLASS,
)


class CalibrationEngine:
    """
    Kalibrasyon cue protokolünü yöneten motor.

    Dashboard UI "Başlat" butonuna basınca → start()
    Kendi thread'inde tüm denemeleri sırayla çalıştırır.
    Her faz değişiminde:
      1. DashboardState'i günceller (UI cue gösterir)
      2. Decoder'a UDP ile bildirir (EEG kaydını kontrol eder)
    """

    def __init__(self, state):
        """
        Parametreler:
            state: DashboardState nesnesi — UI güncellemeleri için
        """
        self.state = state
        self.running = False
        self.thread = None

        # Decoder'a kontrol paketi göndermek için UDP soketi
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.decoder_addr = (DECODER_IP, UDP_CAL_PORT)

    def start(self):
        """Kalibrasyon protokolünü arka plan thread'inde başlatır."""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_protocol, daemon=True)
        self.thread.start()
        print("[CAL-ENGINE] Kalibrasyon başlatıldı")

    def stop(self):
        """Kalibrasyon protokolünü iptal eder."""
        self.running = False

        # Decoder'a iptal bildirimi
        self._send_to_decoder({"type": "cal_stop"})

        self.state.update_calibration(
            running=False, phase="cancelled",
        )
        print("[CAL-ENGINE] Kalibrasyon iptal edildi")

    def _run_protocol(self):
        """
        Ana kalibrasyon döngüsü — kendi thread'inde çalışır.

        Adımlar:
        1. Deneme listesini oluştur (sınıfları karıştır)
        2. Decoder'a "başla" komutu gönder
        3. Her deneme için: fixation → imagery → rest
        4. Bitince Decoder'a "eğit" komutu gönder
        """
        # ── 1. Deneme listesi oluştur ──
        # Her sınıftan 25 deneme, rastgele sırayla karıştırılmış
        trials = []
        for cls in CLASS_NAMES:
            trials.extend([cls] * CAL_TRIALS_PER_CLASS)
        random.shuffle(trials)

        total = len(trials)

        # ── 2. Decoder'a "başla" komutu ──
        self._send_to_decoder({"type": "cal_start", "n_trials": total})

        self.state.update_calibration(
            running=True, phase="fixation", cue="",
            trial=0, total=total, progress=0.0,
        )

        # ── 3. Her deneme için döngü ──
        for i, cls in enumerate(trials):
            if not self.running:
                break

            trial_num = i + 1
            progress = trial_num / total

            # ── FIXATION (dikkat toplama) ──
            self._set_phase("fixation", cls, trial_num, total, progress)
            if not self._wait(CAL_FIXATION_S):
                break

            # ── IMAGERY (motor hayal — VERİ KAYDI) ──
            self._set_phase("imagery", cls, trial_num, total, progress)
            if not self._wait(CAL_IMAGERY_S):
                break

            # ── REST (dinlenme) ──
            self._set_phase("rest", cls, trial_num, total, progress)
            if not self._wait(CAL_REST_S):
                break

        # ── 4. Bitirme ──
        if self.running:
            # Decoder'a "eğitim başlat" komutu
            self.state.update_calibration(phase="training", progress=1.0)
            self._send_to_decoder({"type": "cal_train"})

            # Sonuç bekle (Decoder fine-tune bitince cal_result gönderir)
            # Timeout: max 120 saniye (fine-tune uzun sürebilir)
            print("[CAL-ENGINE] Fine-tune bekleniyor...")

        self.running = False

    def _set_phase(self, phase: str, cls: str, trial: int, total: int,
                   progress: float):
        """Hem dashboard state'i hem Decoder'ı günceller."""
        # Dashboard UI'ı güncelle
        self.state.update_calibration(
            phase=phase, cue=cls, trial=trial,
            total=total, progress=progress,
        )

        # Decoder'a bildir
        self._send_to_decoder({
            "type": "cal_phase",
            "phase": phase,
            "class": cls,
            "trial": trial,
        })

    def _wait(self, seconds: float) -> bool:
        """
        Belirtilen süre boyunca bekler (100ms dilimlerinde).
        self.running False olursa erken döner (iptal desteği).
        """
        end_time = time.time() + seconds
        while time.time() < end_time:
            if not self.running:
                return False
            time.sleep(0.1)
        return True

    def _send_to_decoder(self, msg: dict):
        """Decoder'a JSON formatında UDP kontrol paketi gönderir."""
        try:
            packet = json.dumps(msg).encode()
            self.sock.sendto(packet, self.decoder_addr)
        except OSError:
            pass

    def handle_result(self, result: dict):
        """
        Decoder'dan gelen fine-tune sonucunu işler.
        (UDPListener tarafından çağrılır)
        """
        self.state.update_calibration(
            running=False,
            phase="done",
            results=result,
        )
        base = result.get("base_accuracy", 0)
        after = result.get("accuracy", 0)
        print(f"[CAL-ENGINE] Sonuç: baz={base}% → kişisel={after}%")
