"""
Wheelchair BCI — Arduino Serial Haberleşme (Controller / Pi 5)
Pi 5'ten USB seri port üzerinden Arduino'ya tek-byte motor komutları gönderir.
Arduino tarafında bu byte'lar motorları süren H-Bridge sürücüsüne aktarılır.

Komut protokolü (Pi → Arduino):
  "F"  →  İleri git
  "L"  →  Sola dön
  "R"  →  Sağa dön
  "S"  →  Dur
  "E"  →  Acil durdurma (E-Stop - tüm motorları kes)
"""

import time

from wheelchair_bci.config import SERIAL_PORT, SERIAL_BAUD, SERIAL_ENABLED


class SerialRelay:
    """
    Arduino'ya seri port üzerinden motor komutları gönderir.

    Neden ayrı bir modül?
    - Seri port bağlantısı kopabilir (kablo gevşer, Arduino resetlenir)
    - Her kopuşta otomatik yeniden bağlanma gerekir
    - SERIAL_ENABLED=False iken simülasyon modu: terminale yazdırır,
      gerçek bir seri port açmaz → donanımsız test yapabilirsin
    """

    def __init__(self, port: str = SERIAL_PORT, baud: int = SERIAL_BAUD,
                 enabled: bool = SERIAL_ENABLED):
        """
        Parametreler:
            port:    Seri port yolu (örn. "/dev/ttyACM0")
            baud:    Haberleşme hızı (115200 bps)
            enabled: True ise gerçek seri port, False ise simülasyon
        """
        self.port = port
        self.baud = baud
        self.enabled = enabled
        self.serial_conn = None         # pyserial bağlantı nesnesi
        self.last_command = None        # Son gönderilen komut (tekrar göndermeyi önler)

        if self.enabled:
            self._connect()
        else:
            print(f"[SERIAL] Simülasyon modu (SERIAL_ENABLED=False)")

    def _connect(self):
        """
        Seri port bağlantısını açar.
        Başarısız olursa hata yazdırır ama crash vermez.
        """
        try:
            import serial
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=1.0,            # Okuma timeout (kullanılmıyor ama güvenlik için)
            )
            # Arduino reset sonrası bootloader'ın bitmesini bekle
            time.sleep(2.0)
            print(f"[SERIAL] Bağlandı: {self.port} @ {self.baud} baud")
        except Exception as e:
            print(f"[SERIAL] Bağlantı hatası: {e}")
            self.serial_conn = None

    def send(self, command: str):
        """
        Arduino'ya tek-byte komut gönderir.

        Optimizasyon: Aynı komut art arda geliyorsa tekrar göndermez.
        Bu hem seri port trafiğini azaltır hem de Arduino tarafında
        gereksiz motor komut tekrarlarını önler.

        Parametreler:
            command: str — "F", "L", "R", "S" veya "E"
        """
        # Aynı komutu tekrar gönderme (flood önleme)
        if command == self.last_command and command != "E":
            # E-Stop her zaman gönderilir (güvenlik öncelikli)
            return

        self.last_command = command

        if not self.enabled or self.serial_conn is None:
            # Simülasyon: terminale yazdır
            icons = {"F": "⬆️", "L": "⬅️", "R": "➡️", "S": "⏹️", "E": "🚨"}
            icon = icons.get(command, "❓")
            print(f"[SERIAL-SIM] {icon}  {command}")
            return

        # Gerçek gönderim
        try:
            self.serial_conn.write(command.encode())
            self.serial_conn.flush()        # Tampondaki veriyi hemen gönder
        except Exception as e:
            print(f"[SERIAL] Gönderim hatası: {e}")
            self.serial_conn = None
            # Otomatik yeniden bağlanma dene
            self._connect()

    def close(self):
        """Seri port bağlantısını güvenle kapatır."""
        if self.serial_conn and self.serial_conn.is_open:
            # Kapatmadan önce DUR komutu gönder (güvenlik)
            try:
                self.serial_conn.write(b"S")
                self.serial_conn.flush()
            except Exception:
                pass
            self.serial_conn.close()
            print("[SERIAL] Bağlantı kapatıldı (DUR komutu gönderildi)")
