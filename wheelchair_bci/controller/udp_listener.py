"""
Wheelchair BCI — UDP Alıcı (Controller / Pi 5)
Decoder'dan (Coral) gelen JSON komut paketlerini dinler.
Gelen her paket: {"cmd": "L", "conf": 0.85, "ts": 1711234567.89}
Non-blocking (bloklamayan) tasarım — timeout ile çalışır.
"""

import json
import socket

from wheelchair_bci.config import UDP_CMD_PORT


class UDPListener:
    """
    Decoder düğümünden gelen komut paketlerini UDP üzerinden alır.

    Decoder (Coral) → wifi_sender.py ile gönderir
    Controller (Pi5) → UDPListener ile alır

    Tasarım kararları:
    - Timeout = 0.1s: recv çağrısı en fazla 100ms bekler.
      Bu sürede paket gelmezse None döner → ana döngü diğer
      işlerini yapabilir (güvenlik kontrolü, UI güncellemesi vs.)
    - SO_REUSEADDR: Port zaten kullanılıyorsa bile bağlan.
      Programı kapatıp hemen yeniden açarken port çakışması önlenir.
    """

    def __init__(self, port: int = UDP_CMD_PORT):
        """
        UDP soketini oluşturur ve belirtilen porta bağlar.

        Parametreler:
            port: Dinlenecek port numarası (varsayılan 5000)
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Port yeniden kullanımına izin ver (hızlı restart için)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Tüm ağ arayüzlerinden dinle ("0.0.0.0" = herhangi bir IP)
        self.sock.bind(("0.0.0.0", port))

        # 100ms timeout — bloklamayan davranış sağlar
        self.sock.settimeout(0.1)

        print(f"[UDP] Dinleniyor: 0.0.0.0:{port}")

    def receive(self):
        """
        Bir UDP paketi almayı dener.

        Döndürür:
            dict — paket geldi: {"cmd": "L", "conf": 0.85, "ts": ...}
            None — timeout doldu veya geçersiz paket geldi

        Bu metod BLOKLAMAZ. En fazla 100ms bekler.
        Ana döngüde sürekli çağrılmalıdır:

            while True:
                packet = listener.receive()
                if packet:
                    # komutu işle
                else:
                    # paket yok, diğer işleri yap
        """
        try:
            data, addr = self.sock.recvfrom(1024)       # Max 1KB paket
            packet = json.loads(data.decode())

            # Minimum doğrulama: "cmd" alanı olmalı
            if "cmd" not in packet:
                return None

            return packet

        except socket.timeout:
            # 100ms içinde paket gelmedi → normal durum
            return None

        except (json.JSONDecodeError, UnicodeDecodeError):
            # Bozuk paket → atla
            return None

    def close(self):
        """UDP soketini kapatır."""
        self.sock.close()
        print("[UDP] Dinleme durduruldu.")
