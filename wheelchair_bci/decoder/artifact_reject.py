"""
Wheelchair BCI — Artifact Rejection (Gürültü Penceresi Reddi)

Göz kırpma (EOG) ve kas hareketi (EMG) gibi biyolojik artefaktları tespit
ederek kirlenmiş EEG pencerelerini inference'a göndermeden reddeder.

Neden gerekli?
  - Göz kırpma: ~150-300 µV voltaj patlaması üretir (normal EEG ~5-25 µV)
  - Kas hareketi (çene, ense): ~50-200 µV yüksek frekanslı gürültü üretir
  - Bu patlamalar yapay zekayı yanıltır → tehlikeli yanlış komut

Nasıl çalışır?
  1. Tepe voltaj kontrolü: Herhangi bir kanalda anlık değer ±100 µV aşarsa → RED
  2. Varyans kontrolü: Pencerenin ortalama gücü anormal yüksekse → RED
  3. Her iki kontrol de temizse → veri inference'a gider
"""

import numpy as np

from wheelchair_bci.config import ARTIFACT_PEAK_UV, ARTIFACT_VARIANCE_UV2


class ArtifactRejector:
    """
    EEG pencerelerini göz kırpma ve kas hareketi artefaktlarına karşı kontrol eder.

    Kullanım:
        rejector = ArtifactRejector()
        is_clean, reason = rejector.check(window)
        if is_clean:
            # inference yap
        else:
            # bu pencereyi atla, "S" gönder
    """

    def __init__(self, peak_uv: float = ARTIFACT_PEAK_UV,
                 var_uv2: float = ARTIFACT_VARIANCE_UV2):
        """
        Parametreler:
            peak_uv:  µV cinsinden tepe voltaj eşiği (varsayılan 100 µV)
            var_uv2:  µV² cinsinden varyans eşiği (varsayılan 5000 µV²)
        """
        self.peak_threshold = peak_uv
        self.var_threshold = var_uv2

        # İstatistik sayaçları (debug ve dashboard için)
        self.total_windows = 0
        self.rejected_windows = 0
        self.reject_reasons = {"peak": 0, "variance": 0}

    def check(self, window: np.ndarray) -> tuple[bool, str]:
        """
        Bir EEG penceresinin temiz olup olmadığını kontrol eder.

        Parametreler:
            window: np.ndarray, shape (250, 8) — filtrelenmiş EEG (volt cinsinden)

        Döndürür:
            (is_clean, reason) çifti:
            - is_clean: True ise pencere temiz, inference yapılabilir
            - reason: "OK", "PEAK_ARTIFACT", veya "HIGH_VARIANCE"
        """
        self.total_windows += 1

        # Volt → µV dönüşümü (inference motoru da aynısını yapar)
        window_uv = window * 1e6

        # ── Kontrol 1: Tepe voltaj ──
        # Herhangi bir kanalda herhangi bir anda mutlak değer eşiği aşarsa
        # → göz kırpma veya hareket artefaktı var
        peak_val = np.max(np.abs(window_uv))
        if peak_val > self.peak_threshold:
            self.rejected_windows += 1
            self.reject_reasons["peak"] += 1
            return False, f"PEAK_ARTIFACT ({peak_val:.0f}µV)"

        # ── Kontrol 2: Ortalama varyans ──
        # Tüm kanalların varyansının ortalaması anormal yüksekse
        # → sürekli kas gerginliği veya elektrot teması bozuk
        mean_var = np.mean(np.var(window_uv, axis=0))
        if mean_var > self.var_threshold:
            self.rejected_windows += 1
            self.reject_reasons["variance"] += 1
            return False, f"HIGH_VARIANCE ({mean_var:.0f}µV²)"

        # ── Temiz ──
        return True, "OK"

    @property
    def rejection_rate(self) -> float:
        """Reddedilen pencere yüzdesi (0-100)."""
        if self.total_windows == 0:
            return 0.0
        return (self.rejected_windows / self.total_windows) * 100.0

    def get_stats(self) -> dict:
        """Dashboard için istatistik sözlüğü döndürür."""
        return {
            "total": self.total_windows,
            "rejected": self.rejected_windows,
            "rate": round(self.rejection_rate, 1),
            "reasons": dict(self.reject_reasons),
        }
