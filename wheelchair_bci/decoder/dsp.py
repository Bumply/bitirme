"""
Wheelchair BCI — Gerçek Zamanlı DSP Filtre Zinciri
Notch (50Hz şebeke gürültüsü) + Bandpass (8-30Hz mu/beta) IIR filtreleri.
Durum-korumalı (stateful): ardışık çağrılarda sinyal sürekliliği korunur.
"""

import numpy as np
from scipy.signal import iirnotch, butter, sosfilt, sosfilt_zi, tf2sos

from wheelchair_bci.config import FS, N_CH, NOTCH_FREQ, BANDPASS_LOW, BANDPASS_HIGH


class FilterChain:
    """
    Durum-korumalı (stateful) çok kanallı DSP filtre zinciri.

    Her kanal için bağımsız filtre durumu tutar. Bu sayede:
    - Ardışık çağrılarda sinyal sürekliliği korunur (state)
    - Hem tek-örneklik (sample) hem toplu (chunk) veri işlenebilir
    """

    def __init__(self, n_channels: int = N_CH):
        self.n_channels = n_channels

        # ── 1) Notch Filtre: 50Hz şebeke gürültüsünü keser ──
        # Q=30: dar bantlı — sadece tam 50Hz kesilir, komşu frekanslar etkilenmez
        b_notch, a_notch = iirnotch(NOTCH_FREQ, Q=30.0, fs=FS)
        # tf2sos: (b,a) → SOS formatına çevir (sayısal kararlılık için)
        self.notch_sos = tf2sos(b_notch, a_notch)

        # ── 2) Bandpass Filtre: 8-30Hz bant geçiren ──
        # Butterworth 4. derece: düz geçiş bandı, keskin kesim
        self.bp_sos = butter(
            N=4,
            Wn=[BANDPASS_LOW, BANDPASS_HIGH],
            btype="bandpass",
            fs=FS,
            output="sos",
        )

        # ── 3) Her kanal için bağımsız filtre durumu (state) ──
        # Sıfır ile başlatma → transient az, hızla oturur
        notch_zi_template = sosfilt_zi(self.notch_sos)
        bp_zi_template = sosfilt_zi(self.bp_sos)

        self.notch_zi = [np.zeros_like(notch_zi_template) for _ in range(n_channels)]
        self.bp_zi = [np.zeros_like(bp_zi_template) for _ in range(n_channels)]

    # ──────────────────────────────────────────────────────────────
    # Tek örnek filtreleme (ADS1299 donanım döngüsü için)
    # ──────────────────────────────────────────────────────────────

    def process_sample(self, sample: np.ndarray) -> np.ndarray:
        """
        Tek bir zaman noktasını filtreler (8 kanallık tek örnek).

        Parametreler:
            sample: np.ndarray, shape (n_channels,) — ham EEG örneği (volt)

        Döndürür:
            filtered: np.ndarray, shape (n_channels,) — filtrelenmiş örnek
        """
        filtered = np.empty(self.n_channels, dtype=np.float64)

        for i in range(self.n_channels):
            x = np.array([sample[i]], dtype=np.float64)

            # Önce notch, sonra bandpass — sıralı uygulama
            x, self.notch_zi[i] = sosfilt(self.notch_sos, x, zi=self.notch_zi[i])
            x, self.bp_zi[i] = sosfilt(self.bp_sos, x, zi=self.bp_zi[i])

            filtered[i] = x[0]

        return filtered

    # ──────────────────────────────────────────────────────────────
    # Toplu filtreleme (simülasyon / buffer işleme için)
    # ──────────────────────────────────────────────────────────────

    def process_chunk(self, chunk: np.ndarray) -> np.ndarray:
        """
        Birden fazla zaman noktasını toplu filtreler.

        Parametreler:
            chunk: np.ndarray, shape (n_channels, n_samples) — ham EEG parçası

        Döndürür:
            filtered: np.ndarray, shape (n_channels, n_samples) — filtrelenmiş
        """
        filtered = np.empty_like(chunk, dtype=np.float64)

        for i in range(self.n_channels):
            x = chunk[i].astype(np.float64)

            x, self.notch_zi[i] = sosfilt(self.notch_sos, x, zi=self.notch_zi[i])
            x, self.bp_zi[i] = sosfilt(self.bp_sos, x, zi=self.bp_zi[i])

            filtered[i] = x

        return filtered
