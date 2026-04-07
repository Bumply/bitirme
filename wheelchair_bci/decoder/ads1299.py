"""
Wheelchair BCI — ADS1299 SPI Donanım Okuyucu
Google Coral Dev Board Mini üzerinde SPI bus ile ADS1299 EEG çipinden
8 kanallı 24-bit veri okur. Sadece Coral donanımında çalışır.
"""

import time
import numpy as np

from wheelchair_bci.config import SPI_BUS, SPI_DEVICE, SPI_SPEED, FS


# ══════════════════════════════════════════════════
# CORAL DONANIM TESPİTİ
# ══════════════════════════════════════════════════

def is_coral() -> bool:
    """Kodun Google Coral Dev Board üzerinde çalışıp çalışmadığını kontrol eder."""
    try:
        with open("/sys/firmware/devicetree/base/model", "r") as f:
            return "Coral" in f.read()
    except FileNotFoundError:
        return False


RUNNING_ON_CORAL = is_coral()


# ══════════════════════════════════════════════════
# ADS1299 SPI OKUYUCU
# ══════════════════════════════════════════════════

class ADS1299Reader:
    """
    ADS1299 EEG çipinden SPI üzerinden 8 kanallı 24-bit veri okur.

    Portiloop PCB, ADS1299'u Coral'ın SPI bus 0'ına bağlar.
    Her okuma 8 kanaldan 24-bit signed veri döndürür ve volta çevrilir.
    ADS1299'un DRDY pini 250Hz'de yeni veri hazır sinyali verir.
    """

    def __init__(self, bus: int = SPI_BUS, device: int = SPI_DEVICE,
                 speed: int = SPI_SPEED):
        """
        SPI bağlantısını açar ve ADS1299 registerlarını yapılandırır.

        Parametreler:
            bus:    SPI veri yolu numarası (varsayılan 0)
            device: SPI cihaz numarası / chip select (varsayılan 0)
            speed:  SPI saat hızı Hz cinsinden (varsayılan 2MHz)
        """
        if not RUNNING_ON_CORAL:
            raise RuntimeError(
                "ADS1299Reader sadece Coral donanımında çalışır (spidev gerekli).\n"
                "Laptop/PC'de test için simülasyon modunu kullanın."
            )

        # ── SPI başlat ──
        import spidev
        from periphery import GPIO

        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = speed
        self.spi.mode = 0b01                # CPOL=0, CPHA=1 (ADS1299 SPI modu)

        # ── DRDY (Data Ready) pini ──
        # ADS1299 yeni veri hazır olduğunda bu pini LOW'a çeker
        self.drdy = GPIO("/dev/gpiochip0", 27, "in")

        # ── Volt dönüşüm katsayısı ──
        # LSB = (2 * VREF) / (2^24 * GAIN)
        # VREF = 4.5V (ADS1299 dahili referansı)
        # GAIN = 24  (EEG için tipik kazanç ayarı)
        self.lsb_to_volts = (2 * 4.5) / (2**24 * 24)

        # ── ADS1299 registerlarını yapılandır ──
        self._configure_registers()

        print(f"[ADS1299] SPI bus={bus} dev={device} speed={speed // 1000}kHz")

    def _configure_registers(self):
        """
        ADS1299'u 250 SPS, 8 kanal, normal çalışma moduna ayarlar.

        Register yazma formatı: [WREG | adres, sayı-1, değer]
        WREG komutu = 0x40 + register adresi
        """
        # SDATAC — sürekli okuma modunu durdur (register yazabilmek için)
        self.spi.xfer2([0x11])
        time.sleep(0.01)

        # CONFIG1 (0x01): 250 SPS örnekleme hızı
        self.spi.xfer2([0x41, 0x00, 0x96])

        # CONFIG2 (0x02): dahili test sinyali kapalı
        self.spi.xfer2([0x42, 0x00, 0xC0])

        # CONFIG3 (0x03): dahili referans + bias aktif
        self.spi.xfer2([0x43, 0x00, 0xEC])

        # CHnSET (0x05-0x0C): 8 kanalı gain=24, normal giriş olarak ayarla
        for ch in range(8):
            self.spi.xfer2([0x41 + 0x04 + ch, 0x00, 0x60])

        # LOFF (0x04): Lead-off algılama ayarları
        # DC lead-off, 6nA akım, eşik %95
        self.spi.xfer2([0x44, 0x00, 0x13])

        # LOFF_SENSP (0x0F): Tüm kanalların P (pozitif) lead-off'unu aç
        self.spi.xfer2([0x4F, 0x00, 0xFF])

        # LOFF_SENSN (0x10): Tüm kanalların N (negatif) lead-off'unu aç
        self.spi.xfer2([0x50, 0x00, 0xFF])

        # RDATAC — sürekli okuma modunu başlat
        self.spi.xfer2([0x10])
        time.sleep(0.01)

    def read_sample(self) -> np.ndarray:
        """
        ADS1299'dan tek bir 8 kanallı örnek okur.

        DRDY pini LOW olana kadar bekler (yeni veri hazır sinyali),
        sonra SPI üzerinden 27 byte okur:
          - 3 byte durum (status)
          - 8 kanal × 3 byte = 24 byte veri

        Döndürür:
            sample: np.ndarray, shape (8,), dtype float64 — volt cinsinden
        """
        # DRDY düşene kadar bekle (active low)
        while self.drdy.read():
            pass

        # 27 byte oku: 3 durum + 8×3 veri
        raw = self.spi.xfer2([0x00] * 27)

        # Her kanalı 24-bit two's complement → signed int → volt'a çevir
        sample = np.empty(8, dtype=np.float64)
        for ch in range(8):
            offset = 3 + ch * 3               # İlk 3 byte durum, sonra her kanal 3 byte
            val = (raw[offset] << 16) | (raw[offset + 1] << 8) | raw[offset + 2]

            # 24-bit two's complement: en yüksek bit 1 ise negatif sayı
            if val >= 0x800000:
                val -= 0x1000000

            sample[ch] = val * self.lsb_to_volts

        return sample

    def read_lead_off_status(self, raw_status: bytes = None) -> tuple[int, int]:
        """
        ADS1299 status byte'larından lead-off flaglerini okur.

        ADS1299 'da her veri paketinin ilk 3 byte'ı status word'dür:
          Bit 23-20: 1100 (sabit)
          Bit 19-12: GPIO durumu
          Bit 7-0:   LOFF_STATP (en son okunan değer)

        Gerçek implementasyon için LOFF_STATP (0x12) ve
        LOFF_STATN (0x13) register'ları doğrudan okunur.

        Döndürür:
            (status_p, status_n) — her biri 8-bit, bit=1 → kanal kopuk
        """
        # SDATAC modundan çık (register okumak için)
        self.spi.xfer2([0x11])
        time.sleep(0.002)

        # RREG LOFF_STATP (0x12), 1 register oku
        resp_p = self.spi.xfer2([0x32, 0x00, 0x00])
        status_p = resp_p[2]

        # RREG LOFF_STATN (0x13), 1 register oku
        resp_n = self.spi.xfer2([0x33, 0x00, 0x00])
        status_n = resp_n[2]

        # RDATAC moduna geri dön
        self.spi.xfer2([0x10])
        time.sleep(0.002)

        return status_p, status_n

    def close(self):
        """SPI bağlantısını kapatır."""
        self.spi.close()
        print("[ADS1299] SPI bağlantısı kapatıldı.")
