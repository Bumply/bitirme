"""
Wheelchair BCI — OTA Model Gönderici (Pi5 / Laptop)

Eğitilmiş .tflite model dosyasını WiFi üzerinden Coral'a gönderir.
Coral'daki ota_receiver.py bu dosyayı alıp inference motorunu günceller.

Kullanım:
    python -m wheelchair_bci.ota_push models/EEGNet_personal.tflite
    python -m wheelchair_bci.ota_push models/EEGNet_personal.tflite --ip 192.168.4.2

Protokol:
    1. TCP bağlantısı aç
    2. 4 byte dosya boyutu gönder (big-endian)
    3. Dosya içeriğini gönder
    4. Onay mesajı bekle
"""

import sys
import struct
import socket
import argparse
from pathlib import Path

from wheelchair_bci.config import DECODER_IP, OTA_PORT


def push_model(file_path: str, ip: str = DECODER_IP, port: int = OTA_PORT):
    """
    Model dosyasını Coral'a TCP üzerinden gönderir.

    Parametreler:
        file_path: Gönderilecek .tflite dosyasının yolu
        ip:        Coral'ın IP adresi
        port:      OTA TCP port numarası
    """
    path = Path(file_path)
    if not path.exists():
        print(f"[OTA] ❌ Dosya bulunamadı: {path}")
        sys.exit(1)

    if not path.suffix == ".tflite":
        print(f"[OTA] ⚠ Uyarı: Dosya uzantısı .tflite değil: {path.suffix}")

    file_data = path.read_bytes()
    file_size = len(file_data)

    print(f"[OTA] Model: {path.name} ({file_size / 1024:.1f} KB)")
    print(f"[OTA] Hedef: {ip}:{port}")

    # TCP bağlantısı kur
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)

    try:
        sock.connect((ip, port))
        print("[OTA] Bağlantı kuruldu, gönderiliyor...")

        # 1. Dosya boyutu (4 byte, big-endian)
        sock.sendall(struct.pack(">I", file_size))

        # 2. Dosya içeriği (parça parça gönder — büyük dosyalar için)
        sent = 0
        chunk_size = 65536
        while sent < file_size:
            end = min(sent + chunk_size, file_size)
            sock.sendall(file_data[sent:end])
            sent = end
            pct = sent / file_size * 100
            print(f"\r[OTA] İlerleme: {pct:.0f}% ({sent / 1024:.0f} KB)", end="")

        print()

        # 3. Onay bekle
        response = sock.recv(1024).decode().strip()
        if response.startswith("OK:"):
            model_name = response.split(":", 1)[1]
            print(f"[OTA] ✅ Başarılı! Model kaydedildi: {model_name}")
        else:
            print(f"[OTA] ❌ Hata: {response}")
            sys.exit(1)

    except ConnectionRefusedError:
        print(f"[OTA] ❌ Bağlantı reddedildi. Coral'ın OTA sunucusu çalışıyor mu?")
        print(f"       Coral'da: python -m wheelchair_bci.decoder.main")
        sys.exit(1)
    except socket.timeout:
        print(f"[OTA] ❌ Zaman aşımı. Coral'a ulaşılamıyor: {ip}")
        sys.exit(1)
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser(
        description="BCI Model OTA Push — WiFi üzerinden model gönder"
    )
    parser.add_argument("model", help=".tflite model dosyasının yolu")
    parser.add_argument("--ip", default=DECODER_IP,
                        help=f"Coral IP adresi (varsayılan: {DECODER_IP})")
    parser.add_argument("--port", type=int, default=OTA_PORT,
                        help=f"OTA portu (varsayılan: {OTA_PORT})")
    args = parser.parse_args()

    print("=" * 50)
    print("  WHEELCHAIR BCI — OTA MODEL PUSH")
    print("=" * 50)

    push_model(args.model, args.ip, args.port)


if __name__ == "__main__":
    main()
