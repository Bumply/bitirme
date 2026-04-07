"""
Wheelchair BCI — Lead-Off (Elektrot Kopma) Algılama

ADS1299'un dahili lead-off algılama mekanizmasını kullanarak
elektrotların kafadan koptuğunu tespit eder.

ADS1299 Lead-Off Fizik:
  - Çip, her kanala küçük bir DC akım enjekte eder (~6nA)
  - Elektrot bağlıysa → empedans düşük → voltaj düşük → flag=0
  - Elektrot koptuysa → empedans ∞ → voltaj raylara yapışır → flag=1
  - Bu flagler LOFF_STATP (0x12) ve LOFF_STATN (0x13) registerlarında okunur

Güvenlik:
  - Ardışık N kopma → otomatik DUR komutu
  - Dashboard'a kopan kanal listesi raporlanır
  - Simülasyon modunda (Coral yokken) test edilebilir
"""

import numpy as np

from wheelchair_bci.config import (
    CHANNELS, N_CH, LEAD_OFF_ENABLED, LEAD_OFF_THRESHOLD,
)


class LeadOffDetector:
    """
    EEG elektrotlarının kafayla temasını izler.

    Gerçek donanımda → ADS1299 status byte'larından okur
    Simülasyonda → yazılımsal voltaj analizi ile taklit eder

    Kullanım:
        detector = LeadOffDetector()
        
        # Donanım modu (ADS1299 status byte'ları)
        off_channels = detector.check_hardware(status_p=0b00000100, status_n=0x00)
        # → ["C3"] (3. kanal kopmuş)
        
        # Simülasyon modu (voltaj tabanlı)
        off_channels = detector.check_simulated(window)
        # → ["FC4", "C4"] (çok düşük varyans = muhtemelen kopuk)
        
        is_safe, msg = detector.is_safe()
        # → (False, "LEAD_OFF: C3 kopuk (3/3)")
    """

    def __init__(self, threshold: int = LEAD_OFF_THRESHOLD,
                 enabled: bool = LEAD_OFF_ENABLED):
        """
        Parametreler:
            threshold: Ardışık kaç kopma okunursa güvenli moda geçilsin
            enabled:   False ise tüm kontroller bypass edilir
        """
        self.threshold = threshold
        self.enabled = enabled

        # Her kanal için ardışık kopma sayacı
        self._consecutive = np.zeros(N_CH, dtype=int)
        
        # Son bilinen kopuk kanal listesi
        self._off_channels: list[str] = []

    def check_hardware(self, status_p: int, status_n: int) -> list[str]:
        """
        ADS1299 lead-off status registerlarından kopuk kanalları tespit eder.

        Parametreler:
            status_p: LOFF_STATP register değeri (8 bit, her bit bir kanal)
            status_n: LOFF_STATN register değeri (8 bit)

        Döndürür:
            Kopuk kanal isimlerinin listesi (ör: ["C3", "CP4"])
        """
        if not self.enabled:
            return []

        off_list = []
        combined = status_p | status_n  # P veya N kopuksa → kopuk say

        for ch in range(N_CH):
            if combined & (1 << ch):
                # Bu kanal kopuk
                self._consecutive[ch] += 1
                off_list.append(CHANNELS[ch])
            else:
                # Bu kanal tamam
                self._consecutive[ch] = 0

        self._off_channels = off_list
        return off_list

    def check_simulated(self, window: np.ndarray) -> list[str]:
        """
        Simülasyon modunda (Coral yokken) voltaj tabanlı kopma tahmini.

        Mantık: Kopuk bir elektrot çok düşük varyans (<0.1 µV²) üretir
        çünkü empedans sonsuz → sinyal raylara yapışır → düz çizgi.

        Parametreler:
            window: np.ndarray, shape (250, 8) — filtrelenmiş EEG verisi

        Döndürür:
            Kopuk (şüpheli) kanal isimlerinin listesi
        """
        if not self.enabled:
            return []

        off_list = []
        var_uv2 = np.var(window * 1e6, axis=0)  # Her kanalın varyansı (µV²)

        for ch in range(N_CH):
            if var_uv2[ch] < 0.1:  # 0.1 µV² → düz çizgi → muhtemelen kopuk
                self._consecutive[ch] += 1
                off_list.append(CHANNELS[ch])
            else:
                self._consecutive[ch] = 0

        self._off_channels = off_list
        return off_list

    def is_safe(self) -> tuple[bool, str]:
        """
        Herhangi bir kanalın ardışık kopma eşiğini aşıp aşmadığını kontrol eder.

        Döndürür:
            (is_safe, reason) çifti:
            - True, "OK": Tüm elektrotlar bağlı
            - False, "LEAD_OFF: C3 kopuk (3/3)": Güvenli moda geç
        """
        if not self.enabled:
            return True, "OK"

        for ch in range(N_CH):
            if self._consecutive[ch] >= self.threshold:
                return False, (
                    f"LEAD_OFF: {CHANNELS[ch]} kopuk "
                    f"({self._consecutive[ch]}/{self.threshold})"
                )

        return True, "OK"

    def get_status(self) -> dict:
        """Dashboard için durum sözlüğü döndürür."""
        return {
            "enabled": self.enabled,
            "off_channels": list(self._off_channels),
            "consecutive": self._consecutive.tolist(),
            "is_safe": self.is_safe()[0],
        }

    def reset(self):
        """Tüm sayaçları sıfırlar (ör: elektrotlar yeniden takıldığında)."""
        self._consecutive[:] = 0
        self._off_channels = []
