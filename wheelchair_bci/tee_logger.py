"""
Wheelchair BCI — TeeLogger (Kalıcı Loglama)

Tüm print() çıktılarını hem terminale hem de zaman damgalı
bir .txt log dosyasına yazar.

Kullanım:
    from wheelchair_bci.tee_logger import TeeLogger
    logger = TeeLogger("decoder")   # logs/decoder_20260324_143000.txt
    ...
    logger.close()                  # dosyayı kapatır, stdout'u geri verir

Avantajları:
    - Donanım hatalarını sonradan inceleme imkanı
    - Thread-safe: birden fazla thread'den print() yapılabilir
    - Performans: satır bazında buffering ile dosyaya yazar
"""

import sys
import threading
from pathlib import Path
from datetime import datetime

# Log dosyalarının kaydedileceği klasör
LOG_DIR = Path(__file__).parent.parent / "logs"


class TeeLogger:
    """
    sys.stdout'u yakalar, hem terminale hem dosyaya yazar.

    Parametreler:
        prefix: Log dosya adının başlangıcı (örn: "decoder", "controller")
                Dosya adı: {prefix}_run_{timestamp}.txt
    """

    def __init__(self, prefix: str = "run"):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = LOG_DIR / f"{prefix}_run_{timestamp}.txt"

        self._terminal = sys.stdout           # Orijinal stdout'u sakla
        self._file = open(
            self.log_path, "w", encoding="utf-8", buffering=1  # line buffering
        )
        self._lock = threading.Lock()
        sys.stdout = self                     # print()'i yakala

        # Dosya başlığı
        self._file.write(f"WHEELCHAIR BCI — {prefix.upper()} LOG\n")
        self._file.write(f"Başlangıç: {datetime.now().isoformat()}\n")
        self._file.write("=" * 70 + "\n\n")

        self._terminal.write(f"[LOG] Çıktı kaydediliyor: {self.log_path}\n")

    def write(self, message: str):
        """Her print() çağrısında hem terminale hem dosyaya yazar."""
        with self._lock:
            self._terminal.write(message)
            self._file.write(message)

    def flush(self):
        """Buffer'ı temizler — Python bazı durumlarda bunu bekler."""
        self._terminal.flush()
        self._file.flush()

    def close(self):
        """Log dosyasını kapatır ve stdout'u orijinaline döndürür."""
        sys.stdout = self._terminal
        self._file.write(f"\n\nBitiş: {datetime.now().isoformat()}\n")
        self._file.close()
        self._terminal.write(f"[LOG] Log kaydedildi → {self.log_path}\n")
