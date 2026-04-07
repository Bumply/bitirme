"""
Wheelchair BCI — Otomatik Test Süiti (Bench Test)
=================================================
Tüm pipeline'ı donanımsız test eder.

Testler:
  1. Command Smoother — majority vote, LOW_CONF, TIE
  2. Safety Controller — heartbeat timeout, E-Stop
  3. UDP Pipeline — Decoder → Controller veri akışı
  4. Serial Protocol — Arduino komut formatı doğrulama
  5. Inference Engine — Model yükleme ve tahmin
  6. OTA Model Push — TCP transfer ve dosya kaydetme
  7. Lead-Off Detection — Elektrot kopma algılama

Kullanım:
    python -m wheelchair_bci.bench_test
"""

import time
import json
import socket
import threading
import sys
from pathlib import Path
from datetime import datetime

import numpy as np

# ==============================================================================
# TEST SONUÇLARI
# ==============================================================================

PASS_COUNT = 0
FAIL_COUNT = 0
ERRORS = []


def _check(condition, name):
    """Test sonucunu raporlar."""
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  [OK]   {name}")
    else:
        FAIL_COUNT += 1
        ERRORS.append(name)
        print(f"  [FAIL] {name}")


# ==============================================================================
# TEST 1: Command Smoother
# ==============================================================================

def test_smoother():
    """Majority vote, LOW_CONF ve TIE davranışlarını doğrular."""
    print(f"\n{'=' * 55}")
    print(f"  TEST 1: Command Smoother (Majority Vote)")
    print(f"{'=' * 55}")

    from wheelchair_bci.decoder.smoother import CommandSmoother

    sm = CommandSmoother(window_size=3)

    # Düşük güven → önceki komut korunur (varsayılan 'S')
    cmd, reason = sm.update("F", 0.15)
    _check(reason == "LOW_CONF", "Düşük güven → LOW_CONF")
    _check(cmd == "S", "Düşük güvende varsayılan S korunur")

    # Pencere doldurma (3 tahmin gerekli)
    sm.update("L", 0.80)
    sm.update("L", 0.70)
    cmd, reason = sm.update("R", 0.60)
    _check(cmd == "L", "Majority vote: L,L,R → L kazanır")

    # Unanimous (hepsi aynı)
    sm.update("F", 0.90)
    sm.update("F", 0.85)
    cmd, reason = sm.update("F", 0.80)
    _check(cmd == "F", "Unanimous: F,F,F → F")

    # Reset
    sm.reset()
    _check(sm.last_command == "S", "Reset sonrası S'ye döner")


# ==============================================================================
# TEST 2: Safety Controller
# ==============================================================================

def test_safety():
    """Heartbeat timeout ve E-Stop kontrolünü doğrular."""
    print(f"\n{'=' * 55}")
    print(f"  TEST 2: Safety Controller")
    print(f"{'=' * 55}")

    from wheelchair_bci.controller.safety import SafetyController

    safety = SafetyController()

    # E-Stop testi
    safety.heartbeat()   # heartbeat'i başlat
    cmd, reason = safety.check("F", 0.90)
    _check(cmd == "F" and reason == "OK", "Normal komut geçer")

    safety.trigger_estop()
    cmd, reason = safety.check("F", 0.90)
    _check(cmd == "S" and reason == "E-STOP", "E-Stop aktifken F → S")

    safety.reset_estop()
    cmd, reason = safety.check("L", 0.80)
    _check(cmd == "L" and reason == "OK", "E-Stop reset sonrası komut geçer")

    # Heartbeat timeout testi
    safety2 = SafetyController()
    safety2.heartbeat()
    time.sleep(0.1)
    cmd, reason = safety2.check("F", 0.90)
    _check(reason == "OK", "Heartbeat yakın zamanda → OK")

    # Timeout'u simüle et (last_heartbeat'i eskiye çek)
    safety2.last_heartbeat = time.time() - 10.0  # 10 saniye önce
    cmd, reason = safety2.check("F", 0.90)
    _check(cmd == "S" and reason == "NO_HEARTBEAT",
           "Heartbeat timeout → S + NO_HEARTBEAT")


# ==============================================================================
# TEST 3: UDP Pipeline
# ==============================================================================

def test_udp():
    """Decoder → Controller UDP iletişimini doğrular."""
    print(f"\n{'=' * 55}")
    print(f"  TEST 3: UDP Pipeline")
    print(f"{'=' * 55}")

    TEST_PORT = 9999  # Gerçek portu bozmamak için farklı port

    # Alıcı başlat
    received = []
    stop_rx = threading.Event()

    def receiver():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", TEST_PORT))
        sock.settimeout(0.5)
        while not stop_rx.is_set():
            try:
                data, _ = sock.recvfrom(1024)
                received.append(json.loads(data.decode()))
            except socket.timeout:
                pass
        sock.close()

    rx_thread = threading.Thread(target=receiver, daemon=True)
    rx_thread.start()
    time.sleep(0.2)  # Alıcının başlamasını bekle

    # Gönderici
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    test_commands = ["F", "L", "R", "S"]

    for cmd in test_commands:
        packet = json.dumps({
            "cmd": cmd,
            "conf": 0.85,
            "ts": time.time(),
        }).encode()
        tx_sock.sendto(packet, ("127.0.0.1", TEST_PORT))
        time.sleep(0.05)

    tx_sock.close()
    time.sleep(0.3)
    stop_rx.set()

    # Doğrulama
    _check(len(received) == 4, f"4 paket gönderildi, {len(received)} alındı")
    if received:
        cmds = [p["cmd"] for p in received]
        _check(set(cmds) == set(test_commands),
               f"Tüm komutlar alındı: {cmds}")


# ==============================================================================
# TEST 4: Serial Protocol
# ==============================================================================

def test_serial_protocol():
    """Arduino'nun beklediği komut formatını doğrular."""
    print(f"\n{'=' * 55}")
    print(f"  TEST 4: Serial Protocol Validation")
    print(f"{'=' * 55}")

    valid_commands = ['F', 'L', 'R', 'S', 'E']

    for cmd in valid_commands:
        encoded = cmd.encode()
        _check(len(encoded) == 1, f"'{cmd}' → 1 byte")
        _check(encoded[0] >= ord('A') and encoded[0] <= ord('Z'),
               f"'{cmd}' → 0x{encoded[0]:02X} (büyük harf)")


# ==============================================================================
# TEST 5: Inference Engine
# ==============================================================================

def test_inference():
    """Model yükleme ve tahmin boyutlarını doğrular."""
    print(f"\n{'=' * 55}")
    print(f"  TEST 5: Inference Engine")
    print(f"{'=' * 55}")

    from wheelchair_bci.config import MODELS_DIR, BUFFER_SIZE, N_CH

    # Model var mı kontrol et
    pt_files = sorted(MODELS_DIR.glob("*.pt"), reverse=True) if MODELS_DIR.exists() else []
    if not pt_files:
        print(f"  [SKIP] models/ içinde .pt dosyası bulunamadı")
        return

    # Model yükle
    from wheelchair_bci.decoder.inference import PyTorchEngine
    engine = PyTorchEngine(pt_files[0])

    # Rastgele EEG verisi ile tahmin yap
    dummy_window = np.random.randn(BUFFER_SIZE, N_CH) * 1e-6  # Simüle EEG (volt)
    cmd, conf, probs = engine.predict(dummy_window)

    _check(cmd in ["F", "L", "R", "S"], f"Geçerli komut: {cmd}")
    _check(0.0 <= conf <= 1.0, f"Güven [0,1] aralığında: {conf:.3f}")
    _check(len(probs) == 4, f"4 sınıf olasılığı: {probs}")
    _check(abs(probs.sum() - 1.0) < 0.01,
           f"Olasılıklar toplamı ≈ 1.0: {probs.sum():.4f}")


# ==============================================================================
# TEST 6: OTA Model Push
# ==============================================================================

def test_ota():
    """TCP üzerinden model push/receive mekanizmasını doğrular."""
    print(f"\n{'=' * 55}")
    print(f"  TEST 6: OTA Model Push")
    print(f"{'=' * 55}")

    import struct
    import tempfile
    import os
    from wheelchair_bci.decoder.ota_receiver import OTAReceiver

    received_path = [None]

    def on_receive(path):
        received_path[0] = path

    # OTA sunucuyu test portunda başlat
    TEST_OTA_PORT = 9998
    receiver = OTAReceiver(
        on_model_received=on_receive,
        port=TEST_OTA_PORT
    )
    receiver.start()
    time.sleep(0.3)

    # Sahte model verisi oluştur
    fake_model = b"FAKE_TFLITE_MODEL_DATA_" * 100  # ~2.2 KB

    # TCP ile gönder
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    try:
        sock.connect(("127.0.0.1", TEST_OTA_PORT))
        sock.sendall(struct.pack(">I", len(fake_model)))
        sock.sendall(fake_model)
        response = sock.recv(1024).decode().strip()
        _check(response.startswith("OK:"), f"OTA onay alındı: {response}")
    finally:
        sock.close()

    time.sleep(0.5)

    # Dosya kaydedildi mi?
    _check(received_path[0] is not None, "OTA callback çağrıldı")
    if received_path[0]:
        _check(received_path[0].exists(), f"Model dosyası mevcut: {received_path[0].name}")
        _check(received_path[0].stat().st_size == len(fake_model),
               f"Dosya boyutu doğru: {received_path[0].stat().st_size} byte")
        # Temizlik
        try:
            received_path[0].unlink()
        except FileNotFoundError:
            pass

    receiver.stop()


# ==============================================================================
# TEST 7: Lead-Off Detection
# ==============================================================================

def test_lead_off():
    """Elektrot kopma algılama mekanizmasını doğrular."""
    print(f"\n{'=' * 55}")
    print(f"  TEST 7: Lead-Off Detection")
    print(f"{'=' * 55}")

    from wheelchair_bci.decoder.lead_off import LeadOffDetector

    det = LeadOffDetector(threshold=3)

    # Test 1: Tüm kanallar bağlı (normal sinyal)
    normal = np.random.randn(250, 8) * 5e-6  # 5µV
    off = det.check_simulated(normal)
    _check(len(off) == 0, "Tüm kanallar bağlı → kopuk yok")

    safe, reason = det.is_safe()
    _check(safe and reason == "OK", "Güvenli mod: OK")

    # Test 2: Donanım modu simülasyonu (3. bit = C3 kopuk)
    det2 = LeadOffDetector(threshold=2)
    det2.check_hardware(status_p=0b00000100, status_n=0x00)  # bit 2 = C3
    _check("C3" in det2._off_channels, "Donanım: C3 kopuk tespit")

    # Ardışık 2. okuma
    det2.check_hardware(status_p=0b00000100, status_n=0x00)
    safe, reason = det2.is_safe()
    _check(not safe and "C3" in reason,
           f"Ardışık kopma → güvensiz: {reason}")

    # Test 3: Kanal düzeldikten sonra reset
    det2.check_hardware(status_p=0x00, status_n=0x00)  # hepsi bağlı
    safe, reason = det2.is_safe()
    _check(safe, "Kanal bağlandı → tekrar güvenli")

    # Test 4: Disabled mod
    det3 = LeadOffDetector(enabled=False)
    off = det3.check_hardware(status_p=0xFF, status_n=0xFF)
    _check(len(off) == 0, "Disabled → tüm kontroller bypass")


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    print()
    print("*" * 55)
    print("  WHEELCHAIR BCI — BENCH TEST SUITE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("*" * 55)

    test_smoother()
    test_serial_protocol()
    test_safety()
    test_udp()
    test_inference()
    test_ota()
    test_lead_off()

    # Özet
    total = PASS_COUNT + FAIL_COUNT
    print(f"\n{'*' * 55}")
    print(f"  SONUÇ: {PASS_COUNT}/{total} test geçti")
    print(f"{'*' * 55}")

    if ERRORS:
        print(f"\n  Başarısız testler:")
        for err in ERRORS:
            print(f"    ✗ {err}")

    print()
    if FAIL_COUNT == 0:
        print("  ✅ TÜM TESTLER GEÇTİ")
    else:
        print(f"  ❌ {FAIL_COUNT} TEST BAŞARISIZ")
    print(f"{'*' * 55}")

    return FAIL_COUNT == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
