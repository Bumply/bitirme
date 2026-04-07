"""
Wheelchair BCI — Dashboard Paylaşımlı Durum (Controller / Pi 5)
Komut döngüsü thread'i ile NiceGUI dashboard arayüzü arasında
veri taşıyan thread-safe paylaşımlı durum nesnesi.

Neden gerekli?
  - Komut döngüsü arka planda kendi thread'inde çalışır (hızlı, 10Hz)
  - Dashboard UI ayrı thread'de çalışır (yavaş, 5Hz güncelleme)
  - İkisi aynı veriye (son komut, güven, log vs.) erişir
  - Lock (kilit) ile aynı anda okuma/yazma çakışması önlenir
"""

import time
import threading
import collections

from wheelchair_bci.config import HISTORY_SIZE


class DashboardState:
    """
    Dashboard'un gösterdiği tüm bilgileri tutan merkezi depo.

    Komut döngüsü → update() ile yazar
    Dashboard UI  → snapshot() ile okur (kopyasını alır)

    snapshot() her çağrıda tüm durumun bir KOPYASINI verir.
    Bu sayede UI tarafı lock tutmadan güvenle çalışır.
    """

    def __init__(self):
        self.lock = threading.Lock()

        # ── Anlık durum ──
        self._cmd = "S"                 # Son aktif komut
        self._conf = 0.0                # Son güven skoru
        self._reason = "INIT"           # Son komut sebebi (OK, E-STOP, NO_HEARTBEAT vs.)

        # ── İstatistikler ──
        self._packets = 0               # Toplam alınan paket sayısı
        self._start_time = time.time()  # Sistem başlangıç zamanı (uptime hesabı)
        self._last_packet_time = 0.0    # Son paket zamanı (heartbeat göstergesi)
        self._latency = 0.0             # Son paketin gecikmesi (saniye)

        # ── Komut dağılımı (pasta grafik için) ──
        self._counts = {"F": 0, "L": 0, "R": 0, "S": 0}

        # ── Komut logu (son N kayıt) ──
        # maxlen ile eski kayıtlar otomatik düşer
        self._log = collections.deque(maxlen=HISTORY_SIZE)

        # ── Kalibrasyon durumu ──
        self._cal_running = False       # Kalibrasyon aktif mi?
        self._cal_phase = ""            # fixation / imagery / rest / training / done
        self._cal_cue = ""              # Hangi sınıf gösteriliyor (L, R, F, S)
        self._cal_trial = 0             # Şu anki deneme numarası
        self._cal_total = 0             # Toplam deneme sayısı
        self._cal_progress = 0.0        # İlerleme yüzdesi (0-1)
        self._cal_results = None        # Fine-tune sonuçları dict

        # ── Artifact rejection durumu ──
        self._artifact_rejected = False     # Son pencere reddedildi mi?
        self._artifact_reason = ""          # Son red sebebi
        self._artifact_rate = 0.0           # Toplam red oranı (%)

        # ── Lead-off (elektrot kopma) durumu ──
        self._lead_off_channels = []        # Kopuk kanal isimleri listesi
        self._lead_off_safe = True          # Güvenli mi?

    def update(self, command: str, confidence: float, reason: str, latency: float = 0.0):
        """
        Komut döngüsü her yeni komut işlediğinde çağırır.
        Tüm anlık değerleri günceller ve loga ekler.
        """
        with self.lock:
            self._cmd = command
            self._conf = confidence
            self._reason = reason
            self._packets += 1
            self._last_packet_time = time.time()
            self._latency = latency
            self._counts[command] = self._counts.get(command, 0) + 1

            # Loga zaman damgalı kayıt ekle
            self._log.appendleft({
                "time": time.strftime("%H:%M:%S"),
                "cmd": command,
                "conf": confidence,
                "reason": reason,
                "latency": round(latency * 1000)  # ms cinsinden
            })

    def update_artifact(self, rejected: bool, reason: str = "", rate: float = 0.0):
        """Artifact rejection durumunu günceller."""
        with self.lock:
            self._artifact_rejected = rejected
            self._artifact_reason = reason
            self._artifact_rate = rate

    def update_lead_off(self, off_channels: list, is_safe: bool):
        """Lead-off elektrot durumunu günceller."""
        with self.lock:
            self._lead_off_channels = list(off_channels)
            self._lead_off_safe = is_safe

    def update_calibration(self, **kwargs):
        """
        Kalibrasyon durumunu günceller.
        Keyword argümanlarla sadece değişen alanları güncelle.
        Örnek: state.update_calibration(phase="imagery", cue="L", trial=5)
        """
        with self.lock:
            for key, value in kwargs.items():
                attr = f"_cal_{key}"
                if hasattr(self, attr):
                    setattr(self, attr, value)

    def snapshot(self) -> dict:
        """
        Tüm durumun anlık kopyasını döndürür.
        UI thread'i bunu çağırıp lock'sız güvenle kullanabilir.
        """
        with self.lock:
            return {
                # Anlık
                "cmd": self._cmd,
                "conf": self._conf,
                "reason": self._reason,
                # İstatistik
                "packets": self._packets,
                "uptime": time.time() - self._start_time,
                "last_pkt": self._last_packet_time,
                "latency": self._latency,
                "counts": dict(self._counts),
                # Log
                "log": list(self._log),
                # Kalibrasyon
                "cal_running": self._cal_running,
                "cal_phase": self._cal_phase,
                "cal_cue": self._cal_cue,
                "cal_trial": self._cal_trial,
                "cal_total": self._cal_total,
                "cal_progress": self._cal_progress,
                "cal_results": self._cal_results,
                # Artifact
                "artifact_rejected": self._artifact_rejected,
                "artifact_reason": self._artifact_reason,
                "artifact_rate": self._artifact_rate,
                # Lead-off
                "lead_off_channels": list(self._lead_off_channels),
                "lead_off_safe": self._lead_off_safe,
            }
