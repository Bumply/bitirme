"""
================================================================================
NEURODRIVE — NODE 2 | RASPBERRY PI 5 DASHBOARD
================================================================================
Receives wheelchair commands from Node 1 (Coral) via UDP, displays a real-time
dashboard, applies safety logic, relays validated commands to Node 3 (Arduino)
via serial, and provides a calibration interface for personal model training.

Architecture:
    [UDP Listener] ---- receives {"cmd":"L","conf":0.85,"ts":...} from Coral
          |
    [Safety Logic] ---- validates transitions, enforces timeouts
          |
    [Serial Relay] ---- sends single-byte command to Arduino (L/R/F/S/E)
          |
    [Dashboard UI] ---- NiceGUI web app on port 8080
          |                 Tab 1: Drive (real-time command + controls)
          |                 Tab 2: Calibrate (cue-based recording + fine-tune)
          |                 Tab 3: Settings
          |
    [Calibration] ----- sends cue protocol to Node 1, triggers fine-tune

Usage:
    pip install nicegui pyserial
    python node2_dashboard.py

    Open browser: http://<pi-ip>:8080

================================================================================
"""

import time
import json
import socket
import threading
import collections
import random
from datetime import datetime
from pathlib import Path

# Serial (Arduino connection)
try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# NiceGUI (dashboard)
try:
    from nicegui import ui, app
    HAS_NICEGUI = True
except ImportError:
    HAS_NICEGUI = False
    print("[WARN] NiceGUI not installed — dashboard disabled")
    print("[WARN] pip install nicegui")


# ==============================================================================
# CONFIGURATION
# ==============================================================================

# UDP listener — receives from Node 1 (Coral)
UDP_LISTEN_IP   = "0.0.0.0"
UDP_LISTEN_PORT = 5000

# UDP sender — sends calibration commands to Node 1.
# NODE1_IP is only a *fallback*: the real address is auto-learned from the
# source IP of the command packets Node 1 streams to us (works on any LAN,
# so we no longer depend on the old Coral AP address).
NODE1_IP   = "192.168.1.0"   # fallback only; overwritten once Node 1 is heard
NODE1_PORT = 5001            # Calibration control port

# Serial to Node 3 (Arduino)
SERIAL_PORT     = "/dev/ttyACM0"   # Linux/Pi default; Windows: "COM3"
SERIAL_BAUD     = 115200
SERIAL_ENABLED  = False   # set True when Arduino is connected

# Safety
HEARTBEAT_TIMEOUT = 3.0   # seconds — auto-stop if no packet from Node 1
COMMAND_TIMEOUT   = 5.0   # seconds — auto-stop if no confident command
MAX_SPEED         = 100   # percent (0-100), adjustable from dashboard

# Dashboard
DASHBOARD_PORT = 8080
HISTORY_SIZE   = 200      # keep last N commands for the log

# Calibration protocol
CAL_FIXATION_S   = 2.0    # cross on screen before cue
CAL_IMAGERY_S    = 4.0    # motor imagery period (data recorded)
CAL_REST_S       = 2.0    # rest between trials
CAL_TRIALS_PER_CLASS = 25 # 25 trials x 4 classes = 100 trials total (~13 min)

# Command display
CMD_INFO = {
    "F": {"label": "FORWARD",  "color": "#22c55e", "icon": "arrow_upward",    "arrow": "^", "bg": "#052e16"},
    "L": {"label": "LEFT",     "color": "#3b82f6", "icon": "arrow_back",      "arrow": "<", "bg": "#172554"},
    "R": {"label": "RIGHT",    "color": "#f59e0b", "icon": "arrow_forward",   "arrow": ">", "bg": "#451a03"},
    "S": {"label": "STOP",     "color": "#ef4444", "icon": "stop_circle",     "arrow": "X", "bg": "#450a0a"},
    "E": {"label": "E-STOP",   "color": "#dc2626", "icon": "dangerous",       "arrow": "!", "bg": "#450a0a"},
}

# Calibration imagery cues
CAL_CUES = {
    "L": {"text": "RIGHT HAND", "icon": "front_hand",     "detail": "Imagine squeezing your RIGHT fist"},
    "R": {"text": "LEFT HAND",  "icon": "front_hand",     "detail": "Imagine squeezing your LEFT fist"},
    "F": {"text": "FEET",       "icon": "directions_walk", "detail": "Imagine wiggling your TOES"},
    "S": {"text": "TONGUE",     "icon": "mic",             "detail": "Imagine pressing your TONGUE to the roof of your mouth"},
}


# ==============================================================================
# SAFETY LOGIC
# ==============================================================================

class SafetyController:
    """
    Validates commands before they reach the motors.

    Rules:
    1. Heartbeat timeout — if no packet from Node 1 for 3s, send STOP
    2. Command timeout — if no confident command for 5s, send STOP
    3. Speed limit — adjustable max speed from dashboard
    4. E-stop — immediate stop, requires manual reset
    """

    def __init__(self):
        self.last_packet_time  = time.time()
        self.last_command_time = time.time()
        self.current_command   = "S"
        self.e_stop_active     = False
        self.max_speed         = MAX_SPEED
        self._lock             = threading.Lock()

    def process(self, cmd, confidence):
        with self._lock:
            self.last_packet_time = time.time()

            if self.e_stop_active:
                return "E", "E-STOP ACTIVE"

            self.current_command = cmd
            self.last_command_time = time.time()
            return cmd, "OK"

    def check_timeouts(self):
        with self._lock:
            if self.e_stop_active:
                return "E", "E-STOP ACTIVE"

            now = time.time()

            if now - self.last_packet_time > HEARTBEAT_TIMEOUT:
                self.current_command = "S"
                return "S", "HEARTBEAT TIMEOUT"

            if now - self.last_command_time > COMMAND_TIMEOUT:
                self.current_command = "S"
                return "S", "COMMAND TIMEOUT"

            return self.current_command, "OK"

    def trigger_estop(self):
        with self._lock:
            self.e_stop_active = True
            self.current_command = "E"

    def reset_estop(self):
        with self._lock:
            self.e_stop_active = False
            self.current_command = "S"


# ==============================================================================
# SERIAL RELAY (to Arduino / Node 3)
# ==============================================================================

class SerialRelay:
    """Sends single-byte commands to Arduino via USB serial."""

    def __init__(self, port=SERIAL_PORT, baud=SERIAL_BAUD):
        self.enabled = SERIAL_ENABLED and HAS_SERIAL
        self.ser = None

        if self.enabled:
            try:
                self.ser = serial.Serial(port, baud, timeout=1)
                time.sleep(2)  # Arduino resets on serial connect
                print(f"[SERIAL] Connected: {port} @ {baud}")
            except Exception as e:
                print(f"[SERIAL] Failed to connect: {e}")
                self.enabled = False

        if not self.enabled:
            print("[SERIAL] Disabled -- commands will be logged only")

    def send(self, cmd):
        if self.enabled and self.ser and self.ser.is_open:
            try:
                self.ser.write(cmd.encode())
                self.ser.flush()
            except Exception as e:
                print(f"[SERIAL] Write error: {e}")

    def read_ack(self):
        if self.enabled and self.ser and self.ser.in_waiting:
            return self.ser.readline().decode().strip()
        return None

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()


# ==============================================================================
# UDP LISTENER
# ==============================================================================

class UDPListener:
    """Listens for JSON command packets from Node 1."""

    def __init__(self, ip=UDP_LISTEN_IP, port=UDP_LISTEN_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # NOTE: deliberately NOT setting SO_REUSEADDR. If a second dashboard
        # instance is accidentally launched, we want its bind to FAIL loudly
        # rather than silently share :5000 and split incoming command packets
        # (which would make the UI appear to drop packets at random).
        self.sock.bind((ip, port))
        self.sock.settimeout(0.5)
        print(f"[UDP] Listening on {ip}:{port}")

    def receive(self):
        """Return (packet_dict, sender_ip) or (None, None)."""
        try:
            data, addr = self.sock.recvfrom(1024)
            return json.loads(data.decode()), addr[0]
        except socket.timeout:
            return None, None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, None

    def close(self):
        self.sock.close()


# ==============================================================================
# SHARED STATE (thread-safe)
# ==============================================================================

class DashboardState:
    """Thread-safe state shared between all components."""

    def __init__(self):
        self._lock = threading.Lock()
        self.current_cmd    = "S"
        self.current_conf   = 0.0
        self.current_reason = "WAITING"
        self.packets_received = 0
        self.last_packet_time = 0.0
        self.command_log    = collections.deque(maxlen=HISTORY_SIZE)
        self.cmd_counts     = {"F": 0, "L": 0, "R": 0, "S": 0, "E": 0}
        self.start_time     = time.time()
        # Calibration state
        self.cal_running    = False
        self.cal_phase      = ""       # "fixation", "imagery", "rest", "done"
        self.cal_cue        = ""       # current class being cued
        self.cal_trial      = 0
        self.cal_total      = 0
        self.cal_progress   = 0.0
        self.cal_results    = None     # accuracy after fine-tuning
        # Auto-learned address of Node 1 (Coral), from incoming packets
        self.node1_ip       = None

    def update(self, cmd, conf, reason):
        with self._lock:
            self.current_cmd    = cmd
            self.current_conf   = conf
            self.current_reason = reason
            self.packets_received += 1
            self.last_packet_time = time.time()
            self.cmd_counts[cmd] = self.cmd_counts.get(cmd, 0) + 1
            self.command_log.appendleft({
                "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "cmd": cmd,
                "conf": conf,
                "reason": reason,
            })

    def snapshot(self):
        with self._lock:
            return {
                "cmd":      self.current_cmd,
                "conf":     self.current_conf,
                "reason":   self.current_reason,
                "packets":  self.packets_received,
                "last_pkt": self.last_packet_time,
                "counts":   dict(self.cmd_counts),
                "uptime":   time.time() - self.start_time,
                "log":      list(self.command_log)[:20],
                "cal_running":  self.cal_running,
                "cal_phase":    self.cal_phase,
                "cal_cue":      self.cal_cue,
                "cal_trial":    self.cal_trial,
                "cal_total":    self.cal_total,
                "cal_progress": self.cal_progress,
                "cal_results":  self.cal_results,
                "node1_ip":     self.node1_ip,
            }


# ==============================================================================
# CALIBRATION ENGINE
# ==============================================================================

class CalibrationEngine:
    """
    Runs the cue-based calibration protocol.

    Protocol per trial:
        [fixation cross 2s] -> [imagery cue 4s] -> [rest 2s]

    Total: 25 trials x 4 classes = 100 trials
    Duration: 100 x (2+4+2) = ~13 minutes

    Sends control packets to Node 1 telling it to record EEG data with labels.
    After recording, tells Node 1 to run fine-tuning.
    """

    def __init__(self, state):
        self.state = state
        self.running = False
        self._stop = threading.Event()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.running = True
        t = threading.Thread(target=self._run_protocol, daemon=True)
        t.start()

    def stop(self):
        self._stop.set()
        self.running = False

    def _send_to_node1(self, msg):
        """Send calibration control message to Node 1 (auto-learned IP)."""
        target_ip = self.state.node1_ip or NODE1_IP
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(msg).encode(), (target_ip, NODE1_PORT))
            sock.close()
        except Exception as e:
            print(f"[CAL] Failed to send to Node 1 ({target_ip}): {e}")

    def _run_protocol(self):
        """Main calibration protocol loop."""
        classes = list(CAL_CUES.keys())
        trials_per_class = CAL_TRIALS_PER_CLASS
        total_trials = len(classes) * trials_per_class

        # Build randomized trial list
        trial_list = classes * trials_per_class
        random.shuffle(trial_list)

        self.state.cal_running = True
        self.state.cal_total = total_trials
        self.state.cal_results = None

        # Tell Node 1 to start recording
        self._send_to_node1({"type": "cal_start", "n_trials": total_trials})

        print(f"[CAL] Starting calibration: {total_trials} trials...")

        for i, cue_class in enumerate(trial_list):
            if self._stop.is_set():
                break

            trial_num = i + 1
            self.state.cal_trial = trial_num
            self.state.cal_progress = trial_num / total_trials

            # Phase 1: Fixation cross
            self.state.cal_phase = "fixation"
            self.state.cal_cue = ""
            self._send_to_node1({
                "type": "cal_phase", "phase": "fixation",
                "trial": trial_num, "class": cue_class,
            })
            if self._wait(CAL_FIXATION_S):
                break

            # Phase 2: Imagery cue (data is recorded during this phase)
            self.state.cal_phase = "imagery"
            self.state.cal_cue = cue_class
            self._send_to_node1({
                "type": "cal_phase", "phase": "imagery",
                "trial": trial_num, "class": cue_class,
            })
            if self._wait(CAL_IMAGERY_S):
                break

            # Phase 3: Rest
            self.state.cal_phase = "rest"
            self.state.cal_cue = ""
            self._send_to_node1({
                "type": "cal_phase", "phase": "rest",
                "trial": trial_num, "class": cue_class,
            })
            if self._wait(CAL_REST_S):
                break

        if not self._stop.is_set():
            # Tell Node 1 to run fine-tuning
            self.state.cal_phase = "training"
            self._send_to_node1({"type": "cal_train"})
            print("[CAL] Recording complete. Sent fine-tune command to Node 1.")

            # Wait for Node 1 to respond with results
            # (In real system, Node 1 sends accuracy back via UDP)
            # For now, just mark as done
            self.state.cal_phase = "done"
        else:
            self.state.cal_phase = "cancelled"
            self._send_to_node1({"type": "cal_stop"})

        self.state.cal_running = False
        self.running = False

    def _wait(self, seconds):
        """Sleep in small increments, checking for stop. Returns True if stopped."""
        end = time.time() + seconds
        while time.time() < end:
            if self._stop.is_set():
                return True
            time.sleep(0.05)
        return False


# ==============================================================================
# MAIN LOOP (UDP receive -> safety -> serial -> dashboard update)
# ==============================================================================

def run_command_loop(udp_listener, safety, serial_relay, state, stop_event):
    """Main command processing loop — runs in background thread."""
    print("[LOOP] Command processing started...")

    while not stop_event.is_set():
        packet, sender_ip = udp_listener.receive()

        # Learn / refresh Node 1's address from whoever is streaming to us
        if packet and sender_ip and state.node1_ip != sender_ip:
            state.node1_ip = sender_ip
            print(f"[LOOP] Node 1 address learned: {sender_ip}")

        if packet and "cmd" in packet:
            cmd  = packet["cmd"]
            conf = packet.get("conf", 0.0)

            safe_cmd, reason = safety.process(cmd, conf)
            serial_relay.send(safe_cmd)
            state.update(safe_cmd, conf, reason)

        elif packet and packet.get("type") == "cal_result":
            # Node 1 sent back calibration results
            state.cal_results = {
                "accuracy": packet.get("accuracy", 0),
                "base_accuracy": packet.get("base_accuracy", 0),
            }
            state.cal_phase = "done"
        else:
            safe_cmd, reason = safety.check_timeouts()
            if reason != "OK":
                serial_relay.send(safe_cmd)
                state.update(safe_cmd, 0.0, reason)

    print("[LOOP] Command processing stopped.")


# ==============================================================================
# DASHBOARD UI (NiceGUI)
# ==============================================================================

def build_dashboard(state, safety, serial_relay, cal_engine):
    """Build the NiceGUI web dashboard."""

    # ── Custom CSS ─────────────────────────────────────────────────────
    ui.add_head_html("""
    <style>
        body { background: #0a0a0a !important; }

        .cmd-display {
            font-size: 5rem;
            font-weight: 900;
            line-height: 1;
            text-shadow: 0 0 40px currentColor, 0 0 80px currentColor;
            transition: all 0.3s ease;
        }
        .cmd-sublabel {
            font-size: 1.15rem;
            font-weight: 600;
            letter-spacing: 0.3em;
            text-transform: uppercase;
            opacity: 0.8;
        }
        .cmd-card {
            border-radius: 20px;
            transition: background-color 0.3s ease, box-shadow 0.3s ease;
            min-height: 170px;
        }
        .stat-card {
            background: #1a1a2e;
            border-radius: 16px;
            border: 1px solid #2a2a4e;
        }
        .control-btn {
            border-radius: 16px !important;
            font-weight: 800 !important;
            font-size: 1.1rem !important;
            letter-spacing: 0.1em;
            transition: transform 0.15s ease, box-shadow 0.15s ease !important;
        }
        .control-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 0 20px rgba(255,255,255,0.2);
        }
        .estop-btn {
            border-radius: 20px !important;
            font-weight: 900 !important;
            font-size: 1.8rem !important;
            letter-spacing: 0.15em;
            animation: estop-pulse 2s infinite;
        }
        @keyframes estop-pulse {
            0%, 100% { box-shadow: 0 0 10px rgba(220,38,38,0.5); }
            50% { box-shadow: 0 0 30px rgba(220,38,38,0.8); }
        }
        .log-entry {
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 0.75rem;
            padding: 2px 8px;
            border-radius: 4px;
        }
        .conf-bar-bg {
            background: #1a1a2e;
            border-radius: 8px;
            overflow: hidden;
            height: 12px;
        }
        .conf-bar-fill {
            height: 100%;
            border-radius: 8px;
            transition: width 0.3s ease, background-color 0.3s ease;
        }
        .dist-bar-bg {
            background: #111;
            border-radius: 6px;
            overflow: hidden;
            height: 28px;
        }
        .dist-bar-fill {
            height: 100%;
            border-radius: 6px;
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            padding-left: 8px;
            font-size: 0.8rem;
            font-weight: 700;
        }
        /* Calibration */
        .cal-cue-display {
            font-size: 6rem;
            font-weight: 900;
            line-height: 1;
            transition: all 0.5s ease;
        }
        .cal-fixation {
            font-size: 8rem;
            color: #fff;
            opacity: 0.6;
        }
        .cal-rest {
            font-size: 2rem;
            color: #888;
        }
        .cal-progress-ring {
            width: 200px;
            height: 200px;
        }
        .tab-panel {
            background: #0a0a0a;
        }
    </style>
    """)

    # ── Header ────────────────────────────────────────────────────────
    with ui.header().classes("bg-[#0f0f23] items-center justify-between px-6"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("accessible").classes("text-3xl text-blue-400")
            ui.label("NEURODRIVE").classes(
                "text-xl font-black tracking-widest text-white")
        node1_status = ui.label("NODE 1: --").classes(
            "text-sm font-mono px-3 py-1 rounded-lg bg-gray-800 text-gray-400")

    # ── Tabs ──────────────────────────────────────────────────────────
    with ui.tabs().classes("bg-[#0f0f23] text-white w-full") as tabs:
        drive_tab = ui.tab("Drive").classes("text-white")
        cal_tab   = ui.tab("Calibrate").classes("text-white")
        settings_tab = ui.tab("Settings").classes("text-white")

    with ui.tab_panels(tabs, value=drive_tab).classes("w-full tab-panel flex-grow"):

        # ==============================================================
        # TAB 1: DRIVE
        # ==============================================================
        with ui.tab_panel(drive_tab).classes("p-2"):
            with ui.row().classes("w-full gap-3 flex-nowrap"):

                # ── Left: Big command display ─────────────────────────
                with ui.column().classes("flex-1 gap-2"):
                    cmd_card = ui.element("div").classes(
                        "cmd-card p-3 flex flex-col items-center justify-center"
                    ).style("background: #450a0a; box-shadow: 0 0 60px rgba(239,68,68,0.15);")

                    with cmd_card:
                        cmd_icon_el = ui.icon("stop_circle").classes(
                            "text-4xl mb-1").style("color: #ef4444;")
                        cmd_label = ui.label("S").classes("cmd-display").style(
                            "color: #ef4444;")
                        cmd_sublabel = ui.label("STOP").classes("cmd-sublabel").style(
                            "color: #ef4444;")

                    # Confidence bar
                    with ui.element("div").classes("w-full px-2"):
                        with ui.row().classes("justify-between items-center mb-1"):
                            ui.label("Confidence").classes(
                                "text-xs font-bold text-gray-400 uppercase tracking-wider")
                            conf_pct = ui.label("0%").classes(
                                "text-sm font-bold text-gray-300")
                        conf_bar_container = ui.element("div").classes("conf-bar-bg w-full")
                        conf_bar_fill = ui.element("div").classes("conf-bar-fill")
                        conf_bar_fill.style("width: 0%; background: #ef4444;")
                        conf_bar_container.move(conf_bar_fill)

                    # Stats row
                    with ui.row().classes("w-full gap-3"):
                        with ui.element("div").classes("stat-card flex-1 p-3 text-center"):
                            packets_val = ui.label("0").classes(
                                "text-2xl font-black text-white")
                            ui.label("PACKETS").classes(
                                "text-[10px] text-gray-500 tracking-wider")
                        with ui.element("div").classes("stat-card flex-1 p-3 text-center"):
                            uptime_val = ui.label("0:00").classes(
                                "text-2xl font-black text-white")
                            ui.label("UPTIME").classes(
                                "text-[10px] text-gray-500 tracking-wider")
                        with ui.element("div").classes("stat-card flex-1 p-3 text-center"):
                            reason_val = ui.label("WAIT").classes(
                                "text-2xl font-black text-amber-400")
                            ui.label("STATUS").classes(
                                "text-[10px] text-gray-500 tracking-wider")

                # ── Middle: Controls + E-stop ─────────────────────────
                with ui.column().classes("gap-2").style("width: 260px;"):
                    ui.label("MANUAL OVERRIDE").classes(
                        "text-xs font-black tracking-[0.3em] text-gray-500 text-center")

                    # D-pad layout
                    with ui.column().classes("items-center gap-2"):
                        ui.button("FORWARD", icon="arrow_upward",
                                  on_click=lambda: manual_cmd("F")).classes(
                            "control-btn bg-green-700 text-white w-44 h-11")
                        with ui.row().classes("gap-2"):
                            ui.button("LEFT", icon="arrow_back",
                                      on_click=lambda: manual_cmd("L")).classes(
                                "control-btn bg-blue-700 text-white w-[84px] h-11")
                            ui.button("RIGHT", icon="arrow_forward",
                                      on_click=lambda: manual_cmd("R")).classes(
                                "control-btn bg-amber-700 text-white w-[84px] h-11")
                        ui.button("STOP", icon="stop_circle",
                                  on_click=lambda: manual_cmd("S")).classes(
                            "control-btn bg-red-700 text-white w-44 h-11")

                    ui.separator().classes("my-1")

                    # E-stop — always visible, never below the fold
                    ui.button("E-STOP", icon="dangerous",
                              on_click=lambda: do_estop()).classes(
                        "estop-btn bg-red-800 text-white w-full h-14")
                    ui.button("Reset E-Stop", icon="restart_alt",
                              on_click=lambda: do_reset()).classes(
                        "control-btn bg-gray-700 text-white w-full h-8 text-sm")

                    # Speed slider
                    ui.label("MAX SPEED").classes(
                        "text-xs font-black tracking-[0.3em] text-gray-500 text-center mt-1")
                    speed_display = ui.label(f"{MAX_SPEED}%").classes(
                        "text-xl font-black text-white text-center")
                    speed_slider = ui.slider(
                        min=0, max=100, value=MAX_SPEED,
                        on_change=lambda e: _update_speed(e.value),
                    ).classes("w-full")

                # ── Right: Log + distribution ─────────────────────────
                with ui.column().classes("flex-1 gap-2"):
                    # Command distribution
                    ui.label("DISTRIBUTION").classes(
                        "text-xs font-black tracking-[0.3em] text-gray-500")
                    dist_container = ui.column().classes("w-full gap-2")

                    ui.separator().classes("my-1")

                    # Command log
                    ui.label("COMMAND LOG").classes(
                        "text-xs font-black tracking-[0.3em] text-gray-500")
                    log_container = ui.column().classes(
                        "w-full gap-0 overflow-auto").style("max-height: 170px;")

        # ==============================================================
        # TAB 2: CALIBRATE
        # ==============================================================
        with ui.tab_panel(cal_tab).classes("p-4"):
            with ui.column().classes("w-full items-center gap-6"):

                ui.label("PERSONAL CALIBRATION").classes(
                    "text-2xl font-black tracking-widest text-white")
                ui.label(
                    "This will guide you through motor imagery tasks to personalize the BCI model."
                ).classes("text-sm text-gray-400 text-center max-w-lg")

                # Protocol info
                with ui.row().classes("gap-6"):
                    for cls, info in CAL_CUES.items():
                        with ui.element("div").classes("stat-card p-4 text-center").style("width: 150px;"):
                            ui.icon(info["icon"]).classes("text-3xl").style(
                                f"color: {CMD_INFO[cls]['color']};")
                            ui.label(info["text"]).classes(
                                "text-sm font-bold text-white mt-1")
                            ui.label(f"= {CMD_INFO[cls]['label']}").classes(
                                "text-xs text-gray-500")

                with ui.element("div").classes("stat-card p-4 text-center").style("width: 400px;"):
                    ui.label("Protocol").classes("text-sm font-bold text-gray-400")
                    ui.label(
                        f"{CAL_TRIALS_PER_CLASS} trials x 4 classes = "
                        f"{CAL_TRIALS_PER_CLASS * 4} total"
                    ).classes("text-sm text-white")
                    ui.label(
                        f"~{int(CAL_TRIALS_PER_CLASS * 4 * (CAL_FIXATION_S + CAL_IMAGERY_S + CAL_REST_S) / 60)} "
                        f"minutes"
                    ).classes("text-sm text-gray-500")

                # Calibration visual area
                cal_visual = ui.element("div").classes(
                    "w-full flex items-center justify-center"
                ).style(
                    "min-height: 300px; background: #111; border-radius: 24px; "
                    "border: 2px solid #222;"
                )
                with cal_visual:
                    cal_center_text = ui.label("Press START to begin").classes(
                        "text-2xl text-gray-500")
                    cal_detail_text = ui.label("").classes(
                        "text-lg text-gray-600 mt-2").style("display: none;")
                    cal_icon_el = ui.icon("").classes("text-8xl mt-4").style("display: none;")

                # Progress
                cal_progress_bar = ui.linear_progress(value=0, show_value=False).classes(
                    "w-full max-w-lg")
                cal_status_label = ui.label("Ready").classes("text-sm text-gray-500")

                # Controls
                with ui.row().classes("gap-4"):
                    cal_start_btn = ui.button("START CALIBRATION", icon="play_arrow",
                        on_click=lambda: start_cal()).classes(
                        "control-btn bg-green-700 text-white px-8 h-14 text-lg")
                    cal_stop_btn = ui.button("CANCEL", icon="cancel",
                        on_click=lambda: stop_cal()).classes(
                        "control-btn bg-red-700 text-white px-8 h-14 text-lg")
                    cal_stop_btn.set_visibility(False)

                # Results area (shown after calibration)
                cal_results_card = ui.element("div").classes(
                    "stat-card p-6 text-center").style("width: 400px; display: none;")
                with cal_results_card:
                    ui.label("Calibration Results").classes("text-lg font-bold text-white")
                    cal_result_before = ui.label("Before: --").classes("text-sm text-gray-400 mt-2")
                    cal_result_after = ui.label("After: --").classes("text-lg font-bold text-green-400 mt-1")

        # ==============================================================
        # TAB 3: SETTINGS
        # ==============================================================
        with ui.tab_panel(settings_tab).classes("p-6"):
            with ui.column().classes("max-w-lg mx-auto gap-6"):
                ui.label("SYSTEM SETTINGS").classes(
                    "text-2xl font-black tracking-widest text-white")

                with ui.element("div").classes("stat-card p-5 w-full"):
                    ui.label("Network").classes("text-sm font-bold text-gray-400 mb-3")
                    with ui.row().classes("justify-between"):
                        ui.label("Node 1 IP").classes("text-sm text-gray-300")
                        node1_ip_label = ui.label("not heard yet").classes(
                            "text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("UDP Listen Port").classes("text-sm text-gray-300")
                        ui.label(str(UDP_LISTEN_PORT)).classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Dashboard Port").classes("text-sm text-gray-300")
                        ui.label(str(DASHBOARD_PORT)).classes("text-sm font-mono text-white")

                with ui.element("div").classes("stat-card p-5 w-full"):
                    ui.label("Safety").classes("text-sm font-bold text-gray-400 mb-3")
                    with ui.row().classes("justify-between"):
                        ui.label("Heartbeat Timeout").classes("text-sm text-gray-300")
                        ui.label(f"{HEARTBEAT_TIMEOUT}s").classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Command Timeout").classes("text-sm text-gray-300")
                        ui.label(f"{COMMAND_TIMEOUT}s").classes("text-sm font-mono text-white")

                with ui.element("div").classes("stat-card p-5 w-full"):
                    ui.label("Serial (Arduino)").classes("text-sm font-bold text-gray-400 mb-3")
                    with ui.row().classes("justify-between"):
                        ui.label("Port").classes("text-sm text-gray-300")
                        ui.label(SERIAL_PORT).classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Baud Rate").classes("text-sm text-gray-300")
                        ui.label(str(SERIAL_BAUD)).classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Status").classes("text-sm text-gray-300")
                        serial_status = "CONNECTED" if serial_relay.enabled else "DISABLED"
                        serial_color = "#22c55e" if serial_relay.enabled else "#ef4444"
                        ui.label(serial_status).classes("text-sm font-bold").style(
                            f"color: {serial_color};")

                with ui.element("div").classes("stat-card p-5 w-full"):
                    ui.label("Calibration Protocol").classes("text-sm font-bold text-gray-400 mb-3")
                    with ui.row().classes("justify-between"):
                        ui.label("Trials per class").classes("text-sm text-gray-300")
                        ui.label(str(CAL_TRIALS_PER_CLASS)).classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Fixation").classes("text-sm text-gray-300")
                        ui.label(f"{CAL_FIXATION_S}s").classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Imagery").classes("text-sm text-gray-300")
                        ui.label(f"{CAL_IMAGERY_S}s").classes("text-sm font-mono text-white")
                    with ui.row().classes("justify-between"):
                        ui.label("Rest").classes("text-sm text-gray-300")
                        ui.label(f"{CAL_REST_S}s").classes("text-sm font-mono text-white")

    # ── Action handlers ────────────────────────────────────────────────
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

    # ── Periodic UI update (every 200ms) ──────────────────────────────
    def update_ui():
        snap = state.snapshot()
        try:
            with open("/tmp/update_ui_debug.txt", "w") as _f:
                _f.write(f"state_id={id(state)} packets={snap['packets']} "
                         f"uptime={snap['uptime']:.0f}")
        except Exception:
            pass
        cmd = snap["cmd"]
        info = CMD_INFO.get(cmd, CMD_INFO["S"])

        # Update command display
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

        # Confidence
        conf = snap["conf"]
        conf_pct.text = f"{conf*100:.0f}%"
        conf_color = "#22c55e" if conf >= 0.6 else "#f59e0b" if conf >= 0.4 else "#ef4444"
        conf_bar_fill.style(f"width: {conf*100:.0f}%; background: {conf_color};")

        # Stats
        packets_val.text = f"{snap['packets']:,}"
        mins = int(snap["uptime"]) // 60
        secs = int(snap["uptime"]) % 60
        uptime_val.text = f"{mins}:{secs:02d}"
        reason_val.text = snap["reason"][:8]
        reason_color = "#22c55e" if snap["reason"] == "OK" else "#f59e0b" if snap["reason"] == "MANUAL" else "#ef4444"
        reason_val.style(f"color: {reason_color};")

        # Settings: live Node 1 IP
        node1_ip_label.text = snap["node1_ip"] or "not heard yet"

        # Node 1 status
        ago = time.time() - snap["last_pkt"] if snap["last_pkt"] > 0 else 999
        if ago < 1:
            node1_status.text = "NODE 1: CONNECTED"
            node1_status.classes(replace="text-sm font-mono px-3 py-1 rounded-lg bg-green-900 text-green-300")
        elif ago < HEARTBEAT_TIMEOUT:
            node1_status.text = f"NODE 1: {ago:.0f}s ago"
            node1_status.classes(replace="text-sm font-mono px-3 py-1 rounded-lg bg-amber-900 text-amber-300")
        else:
            node1_status.text = "NODE 1: DISCONNECTED"
            node1_status.classes(replace="text-sm font-mono px-3 py-1 rounded-lg bg-red-900 text-red-300")

        # Distribution bars
        dist_container.clear()
        total = max(sum(snap["counts"].values()), 1)
        with dist_container:
            for c in ["F", "L", "R", "S"]:
                count = snap["counts"].get(c, 0)
                pct = count / total * 100
                ci = CMD_INFO[c]
                with ui.element("div").classes("dist-bar-bg w-full"):
                    with ui.element("div").classes("dist-bar-fill").style(
                        f"width: {max(pct, 2):.0f}%; background: {ci['color']}33;"):
                        ui.label(
                            f"{ci['label']}  {count}  ({pct:.0f}%)"
                        ).classes("text-xs font-bold whitespace-nowrap").style(
                            f"color: {ci['color']};")

        # Command log
        log_container.clear()
        with log_container:
            for entry in snap["log"]:
                ci = CMD_INFO.get(entry["cmd"], CMD_INFO["S"])
                with ui.element("div").classes("log-entry flex gap-3").style(
                    f"background: {ci['color']}08; border-left: 3px solid {ci['color']};"):
                    ui.label(entry["time"]).classes("text-gray-600")
                    ui.label(entry["cmd"]).classes("font-black").style(f"color: {ci['color']};")
                    ui.label(f"{entry['conf']*100:.0f}%").classes("text-gray-400")
                    ui.label(entry["reason"]).classes("text-gray-600")

        # Calibration UI update
        if snap["cal_running"]:
            phase = snap["cal_phase"]
            cue = snap["cal_cue"]
            trial = snap["cal_trial"]
            total_trials = snap["cal_total"]

            cal_progress_bar.value = snap["cal_progress"]
            cal_status_label.text = f"Trial {trial}/{total_trials} - {phase.upper()}"

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
                cal_detail_text.style(f"display: block; color: {ci['color']}88;")
                cal_icon_el._props["name"] = cue_info["icon"]
                cal_icon_el.style(f"display: block; color: {ci['color']};")
                cal_icon_el.update()
            elif phase == "rest":
                cal_center_text.text = "Rest..."
                cal_center_text.classes(replace="cal-rest")
                cal_detail_text.style("display: none;")
                cal_icon_el.style("display: none;")
            elif phase == "training":
                cal_center_text.text = "Training model..."
                cal_center_text.classes(replace="text-2xl text-amber-400")
                cal_detail_text.text = "Node 1 is fine-tuning the model on your data"
                cal_detail_text.style("display: block; color: #888;")
                cal_icon_el.style("display: none;")
        elif snap["cal_phase"] == "done":
            cal_center_text.text = "Calibration Complete!"
            cal_center_text.classes(replace="text-3xl text-green-400")
            cal_detail_text.style("display: none;")
            cal_icon_el.style("display: none;")
            cal_start_btn.set_visibility(True)
            cal_stop_btn.set_visibility(False)

            if snap["cal_results"]:
                cal_results_card.style("display: block;")
                cal_result_before.text = f"Before: {snap['cal_results']['base_accuracy']:.1f}%"
                cal_result_after.text = f"After: {snap['cal_results']['accuracy']:.1f}%"
        elif snap["cal_phase"] == "cancelled":
            cal_center_text.text = "Calibration Cancelled"
            cal_center_text.classes(replace="text-2xl text-red-400")
            cal_start_btn.set_visibility(True)
            cal_stop_btn.set_visibility(False)

    ui.timer(0.2, update_ui)


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    print("=" * 60)
    print("  NEURODRIVE -- NODE 2 | DASHBOARD + RELAY")
    print(f"  Serial: {'ENABLED' if SERIAL_ENABLED else 'DISABLED'}")
    print(f"  UDP: {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}")
    print(f"  Dashboard: http://0.0.0.0:{DASHBOARD_PORT}")
    print("=" * 60)

    # Build components
    udp_listener  = UDPListener()
    safety        = SafetyController()
    serial_relay  = SerialRelay()
    state         = DashboardState()
    cal_engine    = CalibrationEngine(state)
    stop_event    = threading.Event()

    # Start command loop in background thread
    cmd_thread = threading.Thread(
        target=run_command_loop,
        args=(udp_listener, safety, serial_relay, state, stop_event),
        daemon=True,
    )
    cmd_thread.start()

    if HAS_NICEGUI:
        @app.get("/api/state")
        def _debug_state():
            snap = state.snapshot()
            snap["_state_id"] = id(state)
            return snap

        build_dashboard(state, safety, serial_relay, cal_engine)
        ui.run(
            host="0.0.0.0",
            port=DASHBOARD_PORT,
            title="NeuroDrive Dashboard",
            reload=False,
            dark=True,
        )
    else:
        print("[MAIN] Running without dashboard (install nicegui for UI)")
        try:
            while True:
                snap = state.snapshot()
                if snap["packets"] > 0:
                    print(f"  cmd={snap['cmd']}  conf={snap['conf']*100:.0f}%  "
                          f"reason={snap['reason']}  pkts={snap['packets']}")
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    # Cleanup
    stop_event.set()
    cmd_thread.join(timeout=3)
    serial_relay.close()
    udp_listener.close()
    print("[MAIN] Shutdown complete.")


if __name__ == "__main__":
    main()
