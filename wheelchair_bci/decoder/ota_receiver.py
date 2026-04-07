"""
Wheelchair BCI — OTA Model Alıcısı (Coral / Decoder)

Pi5'ten (veya herhangi bir bilgisayardan) WiFi üzerinden gönderilen
eğitilmiş `.tflite` model dosyasını alır ve inference motorunu
canlı olarak değiştirir (hot-swap).

Protokol (TCP/IP):
    1. İstemci bağlanır (ota_push.py)
    2. 4 byte: dosya boyutu (big-endian uint32)
    3. N byte: dosya içeriği
    4. Sunucu dosyayı kaydeder ve onay gönderir

Güvenlik:
    - Maksimum dosya boyutu limiti (OTA_MAX_SIZE = 10MB)
    - Atomik yazma (geçici dosyaya yaz → rename)
    - Hatalı transfer → dosya silinir
"""

import os
import struct
import socket
import tempfile
import threading
from pathlib import Path
from datetime import datetime

from wheelchair_bci.config import (
    OTA_PORT, OTA_MAX_SIZE, MODELS_DIR, DECODER_IP,
)


class OTAReceiver:
    """
    Arka plan thread'inde TCP sunucu çalıştırarak model dosyası kabul eder.

    Kullanım:
        ota = OTAReceiver(on_model_received=reload_callback)
        ota.start()   # arka plan thread'i başlar
        ...
        ota.stop()    # kapatır

    on_model_received callback'i yeni model yolu ile çağrılır:
        def reload_callback(new_model_path: Path):
            engine = load_engine(new_model_path)
    """

    def __init__(self, on_model_received=None,
                 host: str = "0.0.0.0", port: int = OTA_PORT):
        """
        Parametreler:
            on_model_received: Yeni model geldiğinde çağrılacak callback.
                               Parametre: Path (kaydedilen model yolu)
            host: Dinlenecek IP (varsayılan tüm arayüzler)
            port: TCP port numarası
        """
        self.host = host
        self.port = port
        self.callback = on_model_received
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """Arka plan thread'inde TCP sunucuyu başlatır."""
        self._thread = threading.Thread(
            target=self._serve, daemon=True, name="OTA-Receiver"
        )
        self._thread.start()
        print(f"[OTA] TCP sunucu dinliyor: {self.host}:{self.port}")

    def stop(self):
        """Sunucuyu durdurur."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        print("[OTA] Sunucu durduruldu.")

    def _serve(self):
        """Ana sunucu döngüsü — her seferinde tek bağlantı kabul eder."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)  # stop_event kontrolü için
        sock.bind((self.host, self.port))
        sock.listen(1)

        while not self._stop_event.is_set():
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue

            print(f"[OTA] Bağlantı: {addr[0]}:{addr[1]}")
            try:
                self._handle_connection(conn, addr)
            except Exception as e:
                print(f"[OTA] ❌ Hata: {e}")
                try:
                    conn.sendall(f"ERROR: {e}\n".encode())
                except Exception:
                    pass
            finally:
                conn.close()

        sock.close()

    def _handle_connection(self, conn: socket.socket, addr: tuple):
        """Tek bir bağlantıyı işler: boyut oku → dosya al → kaydet."""
        # 1. İlk 4 byte: dosya boyutu (big-endian)
        size_data = self._recv_exact(conn, 4)
        file_size = struct.unpack(">I", size_data)[0]

        if file_size > OTA_MAX_SIZE:
            raise ValueError(
                f"Dosya çok büyük: {file_size / 1e6:.1f}MB "
                f"(limit: {OTA_MAX_SIZE / 1e6:.0f}MB)"
            )

        print(f"[OTA] Dosya alınıyor: {file_size / 1024:.1f} KB")

        # 2. Dosya içeriğini al
        file_data = self._recv_exact(conn, file_size)

        # 3. Atomik kaydetme: önce geçici dosyaya yaz, sonra taşı
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_name = f"OTA_{timestamp}.tflite"
        final_path = MODELS_DIR / final_name

        # Geçici dosyaya yaz
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tflite", dir=str(MODELS_DIR)
        )
        try:
            os.write(fd, file_data)
            os.close(fd)
            # Atomik rename
            os.rename(tmp_path, str(final_path))
        except Exception:
            # Hata durumunda geçici dosyayı sil
            os.close(fd) if not os.get_inheritable(fd) else None
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        print(f"[OTA] ✅ Model kaydedildi: {final_name}")

        # 4. Onay gönder
        conn.sendall(f"OK:{final_name}\n".encode())

        # 5. Callback çağır (hot-swap)
        if self.callback:
            try:
                self.callback(final_path)
                print(f"[OTA] ✅ Model hot-swap tamamlandı!")
            except Exception as e:
                print(f"[OTA] ⚠ Hot-swap başarısız: {e}")

    @staticmethod
    def _recv_exact(conn: socket.socket, n: int) -> bytes:
        """Tam olarak n byte alana kadar okur."""
        data = bytearray()
        while len(data) < n:
            chunk = conn.recv(min(n - len(data), 65536))
            if not chunk:
                raise ConnectionError(
                    f"Bağlantı koptu ({len(data)}/{n} byte alındı)"
                )
            data.extend(chunk)
        return bytes(data)
