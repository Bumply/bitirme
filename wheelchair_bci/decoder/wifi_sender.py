"""
Wheelchair BCI — WiFi UDP Komut Gönderici
Decoder (Coral) → Controller (Pi5) yönünde tahmin sonuçlarını JSON paket olarak gönderir.
Bağlantısız (connectionless) UDP: düşük gecikme, paket kaybına toleranslı.
"""

import json
import time
import socket

from wheelchair_bci.config import CONTROLLER_IP, UDP_CMD_PORT


class CommandSender:
    """
    Sandalye komutlarını Controller'a (Pi 5) UDP üzerinden gönderir.

    Neden UDP (TCP değil)?
    - BCI'da gecikme kritiktir (~100ms'den fazla olmamalı)
    - TCP'nin el sıkışma + yeniden gönderme mekanizması gecikme ekler
    - Bir paket kaybolursa sorun yok — 500ms sonra yenisi gelir
    - UDP: gönder ve unut, minimum overhead
    """

    def __init__(self, ip: str = CONTROLLER_IP, port: int = UDP_CMD_PORT):
        """
        UDP soketini oluşturur.

        Parametreler:
            ip:   Hedef IP adresi (Pi 5)
            port: Hedef port numarası
        """
        self.addr = (ip, port)

        # SOCK_DGRAM = UDP (SOCK_STREAM olsaydı TCP olurdu)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        print(f"[WIFI] UDP hedef: {ip}:{port}")

    def send(self, command: str, confidence: float):
        """
        Komut paketini JSON formatında gönderir.

        Paket yapısı:
            {"cmd": "L", "conf": 0.853, "ts": 1711234567.89}

        Parametreler:
            command:    str   — "F", "L", "R" veya "S"
            confidence: float — güven skoru (0-1)
        """
        packet = json.dumps({
            "cmd":  command,                # Komut harfi
            "conf": round(confidence, 3),   # Güven (3 ondalık basamak yeterli)
            "ts":   time.time(),            # Zaman damgası (gecikme ölçümü için)
        }).encode()                         # String → bytes (UTF-8)

        try:
            self.sock.sendto(packet, self.addr)
        except OSError:
            # Pi henüz bağlanmamışsa → sessizce geç
            # Bir sonraki paket 500ms sonra denenecek
            pass

    def close(self):
        """UDP soketini kapatır."""
        self.sock.close()
        print("[WIFI] UDP bağlantısı kapatıldı.")
