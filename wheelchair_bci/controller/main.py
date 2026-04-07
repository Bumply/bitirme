"""
Wheelchair BCI — Controller (Pi 5) Ana Çalıştırma Script'i

Görevleri:
1. Bileşenleri oluştur (UDP, Safety, Serial, State, Calibration, Dashboard)
2. Arka plan thread'inde komut döngüsünü çalıştır:
   Decoder'dan UDP paket al → güvenlik kontrolü → Arduino'ya gönder
3. NiceGUI dashboard'unu başlat (tarayıcıdan erişim)
"""

import time
import threading
from datetime import datetime

from wheelchair_bci.config import DASHBOARD_PORT, SERIAL_ENABLED, UDP_CMD_PORT

from wheelchair_bci.controller.udp_listener import UDPListener
from wheelchair_bci.controller.safety import SafetyController
from wheelchair_bci.controller.serial_relay import SerialRelay
from wheelchair_bci.controller.state import DashboardState
from wheelchair_bci.controller.calibration_engine import CalibrationEngine
from wheelchair_bci.tee_logger import TeeLogger

# NiceGUI opsiyonel — yüklü değilse terminalde çalışır
try:
    from nicegui import ui
    HAS_NICEGUI = True
except ImportError:
    HAS_NICEGUI = False


# ==============================================================================
# KOMUT DÖNGÜSÜ (Arka plan thread'i)
# ==============================================================================

def run_command_loop(udp_listener, safety, serial_relay, state,
                     cal_engine, stop_event):
    """
    Ana komut döngüsü — kendi thread'inde sürekli çalışır.

    Her turda:
    1. UDP'den paket al (100ms timeout)
    2. Varsa: heartbeat güncelle → güvenlik kontrolü → Arduino'ya gönder
    3. Yoksa: heartbeat timeout kontrolü yap
    """
    print("[LOOP] Komut döngüsü başladı")

    while not stop_event.is_set():
        packet = udp_listener.receive()

        if packet:
            cmd = packet.get("cmd", "S")
            conf = packet.get("conf", 0.0)
            ts = packet.get("ts", time.time())
            latency = max(0.0, time.time() - ts)

            # ── Kalibrasyon sonucu mu? ──
            if packet.get("type") == "cal_result":
                cal_engine.handle_result(packet)
                continue

            # ── Normal komut ──
            # 1. Heartbeat güncelle (Decoder hayatta)
            safety.heartbeat()

            # 2. Güvenlik kontrolünden geçir
            safe_cmd, reason = safety.check(cmd, conf)

            # 3. Arduino'ya gönder
            serial_relay.send(safe_cmd)

            # 4. Dashboard state'i güncelle
            state.update(safe_cmd, conf, reason, latency)

        else:
            # Paket gelmedi — güvenlik kontrolü yap
            # (heartbeat timeout tetiklenebilir)
            safe_cmd, reason = safety.check("S", 0.0)
            if reason != "OK":
                serial_relay.send("S")
                # Sadece durum değiştiğinde dashboard'u güncelle (yoksa saniyede 10 kere spam yapar)
                if state.snapshot()["reason"] != reason:
                    state.update("S", 0.0, reason)

    print("[LOOP] Komut döngüsü durduruldu")


# Global referanslar (temizlik ve frontend için)
_stop_event = threading.Event()
_cmd_thread = None
_serial_relay = None
_udp_listener = None
_state = None
_safety = None
_cal_engine = None
_logger = None


def startup():
    global _cmd_thread, _serial_relay, _udp_listener, _state, _safety, _cal_engine, _logger

    # Tüm çıktıları log dosyasına kaydet
    _logger = TeeLogger("controller")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=" * 60)
    print("  WHEELCHAIR BCI -- CONTROLLER | Pi 5 GİRİŞ NOKTASI")
    print(f"  Serial:    {'AÇIK' if SERIAL_ENABLED else 'KAPALI (simülasyon)'}")
    print(f"  UDP:       0.0.0.0:{UDP_CMD_PORT}")
    print(f"  Dashboard: http://0.0.0.0:{DASHBOARD_PORT}")
    print(f"  Zaman:     {timestamp}")
    print("=" * 60)

    # ── 1. Bileşenleri oluştur ──
    _udp_listener = UDPListener()
    _safety = SafetyController()
    _serial_relay = SerialRelay()
    _state = DashboardState()
    _cal_engine = CalibrationEngine(_state)

    print("\n[INIT] Tüm bileşenler başarıyla oluşturuldu.\n")

    # ── 2. Komut döngüsünü arka plan thread'inde başlat ──
    _cmd_thread = threading.Thread(
        target=run_command_loop,
        args=(_udp_listener, _safety, _serial_relay, _state,
              _cal_engine, _stop_event),
        daemon=True,
    )
    _cmd_thread.start()


def shutdown():
    print("\n[MAIN] Kapatılıyor...")
    _stop_event.set()
    if _cmd_thread:
        _cmd_thread.join(timeout=3)
    if _serial_relay:
        _serial_relay.close()
    if _udp_listener:
        _udp_listener.close()
    print("[MAIN] Controller kapatıldı.")
    if _logger:
        _logger.close()


if HAS_NICEGUI:
    from nicegui import app, ui
    
    # Her tarayıcı sekmesi açıldığında bu sayfa oluşturulur
    @ui.page('/')
    def index():
        from wheelchair_bci.controller.ui import build_dashboard
        if _state is None:
            ui.label("Sistem başlatılıyor, lütfen sayfayı yenileyin...")
            return
        build_dashboard(_state, _safety, _serial_relay, _cal_engine)

    # NiceGUI yaşam döngüsü hook'ları
    app.on_startup(startup)
    app.on_shutdown(shutdown)

if __name__ in {"__main__", "__mp_main__"}:
    if HAS_NICEGUI:
        from nicegui import ui
        # Ortam değişkeniyle çift çalışmayı önleme (FastAPI uvicorn vs runpy)
        ui.run(
            host="0.0.0.0",
            port=DASHBOARD_PORT,
            title="Wheelchair BCI Dashboard",
            reload=False,
            dark=True,
        )
    else:
        # NiceGUI yoksa doğrudan startup'ı çağır ve terminalde blokla
        startup()
        print("[MAIN] Dashboard yok (nicegui yüklü değil)")
        print("[MAIN] Terminal modunda çalışıyor...\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            shutdown()
