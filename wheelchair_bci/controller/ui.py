"""
Wheelchair BCI — NiceGUI Web Dashboard (Controller / Pi 5)
Tarayıcıdan erişilen gerçek zamanlı kontrol ve izleme arayüzü.
http://<pi-ip>:8080 adresinde çalışır.

3 Sekme:
  1. DRIVE    — Anlık komut, güven, dağılım, log, manuel kontrol
  2. CALIBRATE — Kalibrasyon cue arayüzü ve sonuçlar
  3. SETTINGS  — Sistem ayarları ve bağlantı durumları
"""

from wheelchair_bci.config import (
    HEARTBEAT_TIMEOUT, COMMAND_TIMEOUT,
    SERIAL_PORT, SERIAL_BAUD,
    CAL_TRIALS_PER_CLASS, CAL_FIXATION_S, CAL_IMAGERY_S, CAL_REST_S,
    DASHBOARD_PORT, CLASS_NAMES, CHANNELS,
)

# ══════════════════════════════════════════════════
# KOMUT GÖRSEL BİLGİLERİ
# ══════════════════════════════════════════════════

CMD_INFO = {
    "F": {"label": "İLERİ",  "icon": "arrow_upward",   "color": "#22c55e",
           "bg": "rgba(34,197,94,0.08)"},
    "L": {"label": "SOL",    "icon": "arrow_back",     "color": "#3b82f6",
           "bg": "rgba(59,130,246,0.08)"},
    "R": {"label": "SAĞ",    "icon": "arrow_forward",  "color": "#f59e0b",
           "bg": "rgba(245,158,11,0.08)"},
    "S": {"label": "DUR",    "icon": "stop_circle",    "color": "#ef4444",
           "bg": "rgba(239,68,68,0.08)"},
    "E": {"label": "E-STOP", "icon": "emergency",      "color": "#dc2626",
           "bg": "rgba(220,38,38,0.15)"},
}

CAL_CUES = {
    "F": {"text": "AYAK",    "detail": "Ayaklarınızı hareket ettirdiğinizi hayal edin",
           "icon": "download"},
    "L": {"text": "SOL EL",  "detail": "Sol elinizi sıktığınızı hayal edin",
           "icon": "arrow_back"},
    "R": {"text": "SAĞ EL", "detail": "Sağ elinizi sıktığınızı hayal edin",
           "icon": "arrow_forward"},
    "S": {"text": "DİL",    "detail": "Dilinizi damağınıza bastırdığınızı hayal edin",
           "icon": "stop_circle"},
}


# ══════════════════════════════════════════════════
# CSS STİLLERİ
# ══════════════════════════════════════════════════

DASHBOARD_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;700;900&family=JetBrains+Mono:wght@400;700&display=swap');

    body {
        background: #0a0a0f !important;
        font-family: 'Inter', sans-serif !important;
    }
    .stat-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 16px;
        backdrop-filter: blur(12px);
        transition: border-color 0.3s, box-shadow 0.3s;
    }
    .stat-card:hover {
        border-color: rgba(255,255,255,0.12);
    }
    .log-entry {
        padding: 6px 12px;
        border-radius: 8px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
    }
    .dist-bar-bg {
        background: rgba(255,255,255,0.03);
        border-radius: 8px;
        height: 32px;
        margin-bottom: 4px;
    }
    .dist-bar-fill {
        border-radius: 8px;
        height: 100%;
        display: flex;
        align-items: center;
        padding-left: 12px;
        transition: width 0.3s;
    }
    .cal-fixation {
        font-size: 72px;
        color: #666;
        font-weight: 100;
    }
    .cal-cue-display {
        font-size: 48px;
        font-weight: 900;
        letter-spacing: 4px;
    }
    .cal-rest {
        font-size: 32px;
        color: #444;
    }

    /* ── Yeni: Premium status göstergeleri ── */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        transition: all 0.3s ease;
    }
    .status-ok {
        background: rgba(34, 197, 94, 0.12);
        color: #22c55e;
        border: 1px solid rgba(34, 197, 94, 0.2);
    }
    .status-warn {
        background: rgba(245, 158, 11, 0.12);
        color: #f59e0b;
        border: 1px solid rgba(245, 158, 11, 0.2);
    }
    .status-danger {
        background: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.3);
        animation: pulse-danger 2s ease-in-out infinite;
    }
    @keyframes pulse-danger {
        0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.0); }
        50% { box-shadow: 0 0 12px 2px rgba(239, 68, 68, 0.25); }
    }
    @keyframes pulse-glow {
        0%, 100% { opacity: 0.6; }
        50% { opacity: 1.0; }
    }

    .electrode-dot {
        width: 14px; height: 14px;
        border-radius: 50%;
        display: inline-block;
        transition: background 0.3s, box-shadow 0.3s;
    }
    .electrode-ok {
        background: #22c55e;
        box-shadow: 0 0 6px rgba(34,197,94,0.4);
    }
    .electrode-off {
        background: #ef4444;
        box-shadow: 0 0 10px rgba(239,68,68,0.6);
        animation: pulse-glow 1s ease-in-out infinite;
    }

    .mini-stat {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
    }
    .mini-stat-value {
        font-size: 20px;
        font-weight: 900;
        font-family: 'JetBrains Mono', monospace;
        line-height: 1;
    }
    .mini-stat-label {
        font-size: 10px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #666;
    }
</style>
"""


# ══════════════════════════════════════════════════
# DASHBOARD OLUŞTURUCU
# ══════════════════════════════════════════════════

def build_dashboard(state, safety, serial_relay, cal_engine):
    """
    NiceGUI dashboard'unu oluşturur.

    Parametreler:
        state:        DashboardState — paylaşımlı durum nesnesi
        safety:       SafetyController — güvenlik kontrolü
        serial_relay: SerialRelay — motor komut gönderici
        cal_engine:   CalibrationEngine — kalibrasyon yöneticisi
    """
    from nicegui import ui

    ui.add_head_html(DASHBOARD_CSS)

    # ══════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════

    with ui.header().classes("bg-transparent border-b border-gray-800 px-6 py-3"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("♿ Wheelchair BCI").classes(
                "text-xl font-black tracking-wider text-white")

            # Header sağ taraf: durum göstergeleri
            with ui.row().classes("items-center gap-3"):
                # Artifact durumu
                artifact_pill = ui.element("div").classes("status-pill status-ok")
                with artifact_pill:
                    artifact_pill_text = ui.label("🧠 TEMİZ").style(
                        "font-size: 11px;")

                # Lead-off durumu
                leadoff_pill = ui.element("div").classes("status-pill status-ok")
                with leadoff_pill:
                    leadoff_pill_text = ui.label("🔌 BAĞLI").style(
                        "font-size: 11px;")

                # Decoder bağlantı
                node_status = ui.label("DECODER: BEKLENİYOR").classes(
                    "text-sm font-mono px-3 py-1 rounded-lg bg-gray-800 text-gray-400")

    # ══════════════════════════════════════════════
    # SEKMELER
    # ══════════════════════════════════════════════

    with ui.tabs().classes("w-full bg-gray-900") as tabs:
        tab_drive = ui.tab("Drive").classes("text-white")
        tab_cal = ui.tab("Calibrate").classes("text-white")
        tab_settings = ui.tab("Settings").classes("text-white")

    with ui.tab_panels(tabs, value=tab_drive).classes("w-full bg-transparent"):

        # ══════════════════════════════════════
        # SEKME 1: DRIVE (Sürüş)
        # ══════════════════════════════════════

        with ui.tab_panel(tab_drive):
            with ui.row().classes("w-full gap-6 flex-wrap"):

                # ── Sol kolon: Komut göstergesi + Manuel kontrol ──
                with ui.column().classes("flex-1 min-w-[300px] gap-4"):

                    # Büyük komut kartı
                    cmd_card = ui.element("div").classes("stat-card p-8 text-center")
                    with cmd_card:
                        cmd_icon_el = ui.icon("stop_circle", size="64px").classes(
                            "text-red-500 mx-auto mb-2")
                        cmd_label = ui.label("S").classes(
                            "text-6xl font-black text-red-500")
                        cmd_sublabel = ui.label("DUR").classes(
                            "text-xl font-bold text-red-500 mt-1")

                    # Güven barı
                    with ui.element("div").classes("stat-card p-5"):
                        ui.label("Güven Skoru").classes(
                            "text-sm font-bold text-gray-400 mb-2")
                        with ui.row().classes("items-center gap-3"):
                            conf_pct = ui.label("0%").classes(
                                "text-2xl font-black text-white w-20")
                            with ui.element("div").classes(
                                "flex-1 h-4 rounded-full bg-gray-800 overflow-hidden"):
                                conf_bar_fill = ui.element("div").classes(
                                    "h-full rounded-full transition-all duration-300"
                                ).style("width: 0%; background: #ef4444;")

                    # Manuel kontrol butonları
                    with ui.element("div").classes("stat-card p-5"):
                        ui.label("Manuel Kontrol").classes(
                            "text-sm font-bold text-gray-400 mb-3")
                        with ui.row().classes("justify-center gap-2"):
                            for cmd_key, info in CMD_INFO.items():
                                if cmd_key == "E":
                                    continue
                                ui.button(
                                    info["label"],
                                    icon=info["icon"],
                                    on_click=lambda _, c=cmd_key: manual_cmd(c),
                                ).props(f'flat color={info["color"]}').classes(
                                    "text-xs")

                    # E-Stop ve Reset
                    with ui.row().classes("gap-2"):
                        ui.button(
                            "E-STOP", icon="emergency",
                            on_click=lambda e: do_estop(),
                        ).props('color=red').classes("flex-1 text-lg font-black h-14")
                        ui.button(
                            "RESET", icon="restart_alt",
                            on_click=lambda e: do_reset(),
                        ).props('flat color=white').classes("h-14")

                # ── Sağ kolon: İstatistikler + Log ──
                with ui.column().classes("flex-1 min-w-[300px] gap-4"):

                    # ✨ YENİ: Canlı metrikleri (Latency, Artifact, Paket, Uptime)
                    with ui.row().classes("gap-3"):
                        # Latency
                        with ui.element("div").classes("stat-card p-4 flex-1"):
                            ui.label("Ping").classes("text-xs text-gray-500")
                            with ui.element("div").classes("mini-stat"):
                                latency_val = ui.label("—").classes("mini-stat-value text-white")
                                latency_unit = ui.label("ms").classes("mini-stat-label")

                        # Paketler
                        with ui.element("div").classes("stat-card p-4 flex-1"):
                            ui.label("Paketler").classes("text-xs text-gray-500")
                            packets_val = ui.label("0").classes(
                                "text-xl font-black text-white")

                        # Uptime
                        with ui.element("div").classes("stat-card p-4 flex-1"):
                            ui.label("Çalışma").classes("text-xs text-gray-500")
                            uptime_val = ui.label("0:00").classes(
                                "text-xl font-black text-white")

                        # Durum
                        with ui.element("div").classes("stat-card p-4 flex-1"):
                            ui.label("Durum").classes("text-xs text-gray-500")
                            reason_val = ui.label("INIT").classes(
                                "text-xl font-black text-green-400")

                    # ✨ YENİ: Elektrot Durumu (Lead-Off) kartı
                    with ui.element("div").classes("stat-card p-5"):
                        with ui.row().classes("items-center justify-between mb-3"):
                            ui.label("Elektrot Durumu").classes(
                                "text-sm font-bold text-gray-400")
                            leadoff_status_text = ui.label("Tümü Bağlı").classes(
                                "text-xs font-bold text-green-400")

                        electrode_container = ui.row().classes(
                            "justify-between gap-2 flex-wrap")

                    # ✨ YENİ: Artifact Rejection kartı
                    with ui.element("div").classes("stat-card p-5"):
                        with ui.row().classes("items-center justify-between mb-2"):
                            ui.label("Artifact Rejection").classes(
                                "text-sm font-bold text-gray-400")
                            artifact_status_text = ui.label("TEMİZ").classes(
                                "text-xs font-bold text-green-400")
                        with ui.row().classes("items-center gap-4"):
                            with ui.element("div").classes("flex-1"):
                                ui.label("Red Oranı").classes(
                                    "text-xs text-gray-600")
                                artifact_rate_val = ui.label("0.0%").classes(
                                    "text-lg font-black text-white")
                            artifact_reason_label = ui.label("").classes(
                                "text-xs text-gray-500 font-mono")

                    # Komut dağılım barları
                    with ui.element("div").classes("stat-card p-5"):
                        ui.label("Komut Dağılımı").classes(
                            "text-sm font-bold text-gray-400 mb-3")
                        dist_container = ui.column().classes("w-full gap-1")

                    # Komut logu
                    with ui.element("div").classes("stat-card p-5"):
                        ui.label("Son Komutlar").classes(
                            "text-sm font-bold text-gray-400 mb-3")
                        log_container = ui.column().classes(
                            "w-full gap-1 max-h-[300px] overflow-auto")

                    # Hız slider
                    with ui.element("div").classes("stat-card p-5"):
                        with ui.row().classes("items-center justify-between"):
                            ui.label("Hız Limiti").classes(
                                "text-sm font-bold text-gray-400")
                            speed_display = ui.label(
                                f"{safety.max_speed}%").classes(
                                "text-lg font-black text-white")
                        ui.slider(
                            min=0, max=100, value=safety.max_speed,
                            on_change=lambda e: _update_speed(e.value),
                        ).props("color=blue")

        # ══════════════════════════════════════
        # SEKME 2: CALIBRATE (Kalibrasyon)
        # ══════════════════════════════════════

        with ui.tab_panel(tab_cal):
            with ui.column().classes("w-full items-center gap-6"):

                # İlerleme barı
                cal_progress_bar = ui.linear_progress(value=0).classes(
                    "w-full max-w-2xl").props("color=blue rounded size=20px")
                cal_status_label = ui.label(
                    "Kalibrasyona hazır").classes("text-lg text-gray-400")

                # Cue gösterim alanı
                with ui.element("div").classes(
                    "stat-card w-full max-w-2xl p-16 text-center"
                ).style("min-height: 300px;"):
                    cal_icon_el = ui.icon("psychology", size="80px").classes(
                        "text-gray-600 mx-auto").style("display: none;")
                    cal_center_text = ui.label("Başla butonuna basın").classes(
                        "text-3xl text-gray-500 mt-4")
                    cal_detail_text = ui.label("").classes(
                        "text-lg mt-2").style("display: none;")

                # Başlat / Durdur butonları
                with ui.row().classes("gap-4"):
                    cal_start_btn = ui.button(
                        "Kalibrasyonu Başlat", icon="play_arrow",
                        on_click=lambda e: start_cal(),
                    ).props("color=blue size=lg")
                    cal_stop_btn = ui.button(
                        "İptal", icon="stop",
                        on_click=lambda e: stop_cal(),
                    ).props("color=red size=lg")
                    cal_stop_btn.set_visibility(False)

                # Sonuç kartı
                cal_results_card = ui.element("div").classes(
                    "stat-card p-6 w-full max-w-md text-center"
                ).style("display: none;")
                with cal_results_card:
                    ui.label("Fine-Tune Sonuçları").classes(
                        "text-lg font-bold text-gray-300 mb-3")
                    cal_result_before = ui.label("").classes(
                        "text-xl text-gray-400")
                    cal_result_after = ui.label("").classes(
                        "text-2xl font-black text-green-400")

        # ══════════════════════════════════════
        # SEKME 3: SETTINGS (Ayarlar)
        # ══════════════════════════════════════

        with ui.tab_panel(tab_settings):
            with ui.column().classes("w-full max-w-xl gap-4"):

                with ui.element("div").classes("stat-card p-5"):
                    ui.label("Güvenlik").classes(
                        "text-sm font-bold text-gray-400 mb-3")
                    for label, val in [
                        ("Heartbeat Timeout", f"{HEARTBEAT_TIMEOUT}s"),
                        ("Command Timeout", f"{COMMAND_TIMEOUT}s"),
                    ]:
                        with ui.row().classes("justify-between"):
                            ui.label(label).classes("text-sm text-gray-300")
                            ui.label(val).classes("text-sm font-mono text-white")

                with ui.element("div").classes("stat-card p-5"):
                    ui.label("Serial (Arduino)").classes(
                        "text-sm font-bold text-gray-400 mb-3")
                    for label, val in [
                        ("Port", SERIAL_PORT),
                        ("Baud Rate", str(SERIAL_BAUD)),
                    ]:
                        with ui.row().classes("justify-between"):
                            ui.label(label).classes("text-sm text-gray-300")
                            ui.label(val).classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Status").classes("text-sm text-gray-300")
                        s_status = "BAĞLI" if serial_relay.enabled else "KAPALI"
                        s_color = "#22c55e" if serial_relay.enabled else "#ef4444"
                        ui.label(s_status).classes("text-sm font-bold").style(
                            f"color: {s_color};")

                with ui.element("div").classes("stat-card p-5"):
                    ui.label("Kalibrasyon Protokolü").classes(
                        "text-sm font-bold text-gray-400 mb-3")
                    for label, val in [
                        ("Sınıf başına deneme", str(CAL_TRIALS_PER_CLASS)),
                        ("Fixation süresi", f"{CAL_FIXATION_S}s"),
                        ("Imagery süresi", f"{CAL_IMAGERY_S}s"),
                        ("Rest süresi", f"{CAL_REST_S}s"),
                    ]:
                        with ui.row().classes("justify-between"):
                            ui.label(label).classes("text-sm text-gray-300")
                            ui.label(val).classes("text-sm font-mono text-white")

    # ══════════════════════════════════════════════
    # EYLEM FONKSİYONLARI
    # ══════════════════════════════════════════════

    def manual_cmd(cmd):
        serial_relay.send(cmd)
        state.update(cmd, 1.0, "MANUAL")

    def do_estop():
        safety.trigger_estop()
        serial_relay.send("E")
        state.update("E", 1.0, "E-STOP")

    def do_reset():
        safety.reset_estop()
        serial_relay.send("S")
        state.update("S", 0.0, "RESET")

    def _update_speed(val):
        safety.max_speed = val
        speed_display.text = f"{int(val)}%"

    def start_cal():
        cal_engine.start()
        cal_start_btn.set_visibility(False)
        cal_stop_btn.set_visibility(True)
        cal_results_card.style("display: none;")

    def stop_cal():
        cal_engine.stop()
        cal_start_btn.set_visibility(True)
        cal_stop_btn.set_visibility(False)

    # ══════════════════════════════════════════════
    # PERİYODİK UI GÜNCELLEMESİ (200ms)
    # ══════════════════════════════════════════════

    def update_ui():
        snap = state.snapshot()
        cmd = snap["cmd"]
        info = CMD_INFO.get(cmd, CMD_INFO["S"])

        # Komut göstergesi
        cmd_label.text = cmd
        cmd_label.style(f"color: {info['color']};")
        cmd_sublabel.text = info["label"]
        cmd_sublabel.style(f"color: {info['color']};")
        cmd_icon_el._props["name"] = info["icon"]
        cmd_icon_el.style(f"color: {info['color']};")
        cmd_icon_el.update()
        cmd_card.style(
            f"background: {info['bg']}; "
            f"box-shadow: 0 0 60px {info['color']}15;")

        # Güven barı
        conf = snap["conf"]
        conf_pct.text = f"{conf*100:.0f}%"
        c_color = "#22c55e" if conf >= 0.6 else "#f59e0b" if conf >= 0.4 else "#ef4444"
        conf_bar_fill.style(f"width: {conf*100:.0f}%; background: {c_color};")

        # ✨ Latency göstergesi
        lat_ms = snap["latency"] * 1000  # saniye → ms
        if snap["last_pkt"] == 0:
            latency_val.text = "—"
            latency_val.style("color: #666;")
        elif lat_ms < 50:
            latency_val.text = f"{lat_ms:.0f}"
            latency_val.style("color: #22c55e;")  # Yeşil: < 50ms
        elif lat_ms < 150:
            latency_val.text = f"{lat_ms:.0f}"
            latency_val.style("color: #f59e0b;")  # Sarı: 50-150ms
        else:
            latency_val.text = f"{lat_ms:.0f}"
            latency_val.style("color: #ef4444;")  # Kırmızı: > 150ms

        # İstatistikler
        packets_val.text = f"{snap['packets']:,}"
        mins = int(snap["uptime"]) // 60
        secs = int(snap["uptime"]) % 60
        uptime_val.text = f"{mins}:{secs:02d}"
        reason_val.text = snap["reason"][:8]
        r_color = "#22c55e" if snap["reason"] == "OK" else \
                  "#f59e0b" if snap["reason"] == "MANUAL" else "#ef4444"
        reason_val.style(f"color: {r_color};")

        # ✨ Elektrot Lead-Off durumu
        off_channels = snap.get("lead_off_channels", [])
        is_loff_safe = snap.get("lead_off_safe", True)

        electrode_container.clear()
        with electrode_container:
            for ch_name in CHANNELS:
                is_off = ch_name in off_channels
                dot_cls = "electrode-off" if is_off else "electrode-ok"
                with ui.column().classes("items-center gap-1"):
                    ui.element("div").classes(f"electrode-dot {dot_cls}")
                    ui.label(ch_name).classes("text-xs font-mono").style(
                        f"color: {'#ef4444' if is_off else '#666'};")

        if not is_loff_safe:
            leadoff_status_text.text = f"KOPUK: {', '.join(off_channels)}"
            leadoff_status_text.classes(replace="text-xs font-bold text-red-400")
            leadoff_pill_text.text = f"🔌 KOPUK ({len(off_channels)})"
            leadoff_pill.classes(replace="status-pill status-danger")
        elif off_channels:
            leadoff_status_text.text = f"Uyarı: {', '.join(off_channels)}"
            leadoff_status_text.classes(replace="text-xs font-bold text-amber-400")
            leadoff_pill_text.text = "🔌 UYARI"
            leadoff_pill.classes(replace="status-pill status-warn")
        else:
            leadoff_status_text.text = "Tümü Bağlı"
            leadoff_status_text.classes(replace="text-xs font-bold text-green-400")
            leadoff_pill_text.text = "🔌 BAĞLI"
            leadoff_pill.classes(replace="status-pill status-ok")

        # ✨ Artifact Rejection durumu
        art_rejected = snap.get("artifact_rejected", False)
        art_rate = snap.get("artifact_rate", 0.0)
        art_reason = snap.get("artifact_reason", "")

        artifact_rate_val.text = f"{art_rate:.1f}%"
        if art_rejected:
            artifact_status_text.text = "⚡ REDDEDİLDİ"
            artifact_status_text.classes(replace="text-xs font-bold text-red-400")
            artifact_reason_label.text = art_reason
            artifact_pill_text.text = f"🧠 ARTİFAKT"
            artifact_pill.classes(replace="status-pill status-danger")
        else:
            artifact_status_text.text = "TEMİZ"
            artifact_status_text.classes(replace="text-xs font-bold text-green-400")
            artifact_reason_label.text = ""
            artifact_pill_text.text = "🧠 TEMİZ"
            artifact_pill.classes(replace="status-pill status-ok")

        # Artifact oranı rengi
        if art_rate > 30:
            artifact_rate_val.style("color: #ef4444;")  # Kırmızı
        elif art_rate > 10:
            artifact_rate_val.style("color: #f59e0b;")  # Sarı
        else:
            artifact_rate_val.style("color: #22c55e;")    # Yeşil

        # Decoder bağlantı durumu
        import time as _time
        ago = _time.time() - snap["last_pkt"] if snap["last_pkt"] > 0 else 999
        if ago < 1:
            node_status.text = "DECODER: BAĞLI"
            node_status.classes(replace=(
                "text-sm font-mono px-3 py-1 rounded-lg "
                "bg-green-900 text-green-300"))
        elif ago < HEARTBEAT_TIMEOUT:
            node_status.text = f"DECODER: {ago:.0f}s önce"
            node_status.classes(replace=(
                "text-sm font-mono px-3 py-1 rounded-lg "
                "bg-amber-900 text-amber-300"))
        else:
            node_status.text = "DECODER: BAĞLANTI YOK"
            node_status.classes(replace=(
                "text-sm font-mono px-3 py-1 rounded-lg "
                "bg-red-900 text-red-300"))

        # Komut dağılımı
        dist_container.clear()
        total = max(sum(snap["counts"].values()), 1)
        with dist_container:
            for c in ["F", "L", "R", "S"]:
                count = snap["counts"].get(c, 0)
                pct = count / total * 100
                ci = CMD_INFO[c]
                with ui.element("div").classes("dist-bar-bg w-full"):
                    with ui.element("div").classes("dist-bar-fill").style(
                        f"width: {max(pct, 2):.0f}%; "
                        f"background: {ci['color']}33;"):
                        ui.label(
                            f"{ci['label']}  {count}  ({pct:.0f}%)"
                        ).classes(
                            "text-xs font-bold whitespace-nowrap"
                        ).style(f"color: {ci['color']};")

        # Komut logu (latency dahil)
        log_container.clear()
        with log_container:
            for entry in snap["log"][:20]:
                ci = CMD_INFO.get(entry["cmd"], CMD_INFO["S"])
                lat_entry = entry.get("latency", 0)
                lat_color = "#22c55e" if lat_entry < 50 else \
                            "#f59e0b" if lat_entry < 150 else "#ef4444"
                with ui.element("div").classes("log-entry flex gap-3").style(
                    f"background: {ci['color']}08; "
                    f"border-left: 3px solid {ci['color']};"):
                    ui.label(entry["time"]).classes("text-gray-600")
                    ui.label(entry["cmd"]).classes("font-black").style(
                        f"color: {ci['color']};")
                    ui.label(f"{entry['conf']*100:.0f}%").classes("text-gray-400")
                    ui.label(entry["reason"]).classes("text-gray-600")
                    if lat_entry > 0:
                        ui.label(f"{lat_entry}ms").classes(
                            "font-mono text-xs").style(f"color: {lat_color};")

        # Kalibrasyon UI
        if snap["cal_running"]:
            phase = snap["cal_phase"]
            cue = snap["cal_cue"]

            cal_progress_bar.value = snap["cal_progress"]
            cal_status_label.text = (
                f"Deneme {snap['cal_trial']}/{snap['cal_total']} — "
                f"{phase.upper()}")

            if phase == "fixation":
                cal_center_text.text = "+"
                cal_center_text.classes(replace="cal-fixation")
                cal_detail_text.style("display: none;")
                cal_icon_el.style("display: none;")
            elif phase == "imagery" and cue in CAL_CUES:
                cue_info = CAL_CUES[cue]
                ci = CMD_INFO[cue]
                cal_center_text.text = cue_info["text"]
                cal_center_text.classes(replace="cal-cue-display")
                cal_center_text.style(f"color: {ci['color']};")
                cal_detail_text.text = cue_info["detail"]
                cal_detail_text.style(
                    f"display: block; color: {ci['color']}88;")
                cal_icon_el._props["name"] = cue_info["icon"]
                cal_icon_el.style(f"display: block; color: {ci['color']};")
                cal_icon_el.update()
            elif phase == "rest":
                cal_center_text.text = "Dinlenme..."
                cal_center_text.classes(replace="cal-rest")
                cal_detail_text.style("display: none;")
                cal_icon_el.style("display: none;")
            elif phase == "training":
                cal_center_text.text = "Model eğitiliyor..."
                cal_center_text.classes(replace="text-2xl text-amber-400")
                cal_detail_text.text = (
                    "Decoder verilerinizle modeli kişiselleştiriyor")
                cal_detail_text.style("display: block; color: #888;")
                cal_icon_el.style("display: none;")

        elif snap["cal_phase"] == "done":
            cal_center_text.text = "Kalibrasyon Tamamlandı!"
            cal_center_text.classes(replace="text-3xl text-green-400")
            cal_detail_text.style("display: none;")
            cal_icon_el.style("display: none;")
            cal_start_btn.set_visibility(True)
            cal_stop_btn.set_visibility(False)
            if snap["cal_results"]:
                cal_results_card.style("display: block;")
                cal_result_before.text = (
                    f"Önce: {snap['cal_results']['base_accuracy']:.1f}%")
                cal_result_after.text = (
                    f"Sonra: {snap['cal_results']['accuracy']:.1f}%")

        elif snap["cal_phase"] == "cancelled":
            cal_center_text.text = "Kalibrasyon İptal Edildi"
            cal_center_text.classes(replace="text-2xl text-red-400")
            cal_start_btn.set_visibility(True)
            cal_stop_btn.set_visibility(False)

    # Her 200ms'de UI güncelle
    ui.timer(0.2, update_ui)
