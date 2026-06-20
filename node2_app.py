#!/usr/bin/env python3
"""
================================================================================
NEURODRIVE — NODE 2 | RASPBERRY PI 5 — NATIVE TOUCHSCREEN APP (PyQt5)
================================================================================
A fullscreen native dashboard for the 7" Pi display. Replaces the browser/
NiceGUI stack (which re-executed the whole script per page request and never
held a websocket on the kiosk).

Same backend as before — only the UI layer is native now:
    [UDP thread] receives {"cmd":"L","conf":0.85,...} from Node 1 (Coral)
        -> [SafetyController] validates / enforces timeouts
        -> [SerialRelay] sends a single byte to Node 3 (Arduino)
        -> [DashboardState] thread-safe snapshot
    [QTimer @10Hz] polls the snapshot and repaints the Qt widgets.

Run on the Pi (system python3 has PyQt5 + pyserial):
    python3 node2_app.py            # fullscreen
    python3 node2_app.py --windowed # for development
================================================================================
"""
import os
import gc
import sys
import time
import json
import socket
import threading
import collections
import random
from datetime import datetime

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QFont, QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QSlider,
    QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect,
)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
UDP_LISTEN_IP   = "0.0.0.0"
UDP_LISTEN_PORT = 5000
NODE1_PORT      = 5001            # calibration control port (to Node 1)
NODE1_IP_FALLBACK = "192.168.1.0" # only used until Node 1 is heard

SERIAL_PORT    = "/dev/ttyACM0"
SERIAL_BAUD    = 115200
SERIAL_ENABLED = True             # Arduino (Node 3) connected on /dev/ttyACM0

# Phone web control: tiny built-in HTTP server (no deps). Join the NeuroDrive
# AP on your phone and open http://<pi-ip>:8000  (Pi is 192.168.4.2 on the AP).
WEB_ENABLED = True
WEB_PORT    = 8000

# Drive mode. "EEG" = chair driven by Node 1 predictions; "MANUAL" = driven only
# by the dashboard / phone buttons (EEG shown but not relayed). E-STOP works in both.
DEFAULT_MODE = "EEG"

# Electrode-contact (lead-off proxy): a floating/disconnected electrode rails to a
# huge peak-to-peak. If filtered pp exceeds this (µV) we flag the channel OFF.
CONTACT_PP_THRESHOLD = 600.0

HEARTBEAT_TIMEOUT = 3.0
COMMAND_TIMEOUT   = 5.0
MAX_SPEED         = 100
# Safety auto-STOP on lost heartbeat / stale command. MUST be True for real
# driving — temporarily False for bench link-testing so the log/state only
# reflect genuine commands from Node 1 (no auto-STOP spam).
HEARTBEAT_ENABLED = False

HISTORY_SIZE = 50         # command log is a bounded ring buffer (never grows)

CAL_FIXATION_S = 2.0
CAL_IMAGERY_S  = 4.0
CAL_REST_S     = 2.0
CAL_TRIALS_PER_CLASS = 25

# F/L/R/S/E  — colours match the old dashboard
CMD_INFO = {
    "F": {"label": "FORWARD", "color": "#22c55e", "bg": "#052e16"},
    "L": {"label": "LEFT",    "color": "#3b82f6", "bg": "#172554"},
    "R": {"label": "RIGHT",   "color": "#f59e0b", "bg": "#451a03"},
    "S": {"label": "STOP",    "color": "#ef4444", "bg": "#450a0a"},
    "E": {"label": "E-STOP",  "color": "#dc2626", "bg": "#450a0a"},
}
CAL_CUES = {
    "L": "Imagine squeezing your RIGHT fist",
    "R": "Imagine squeezing your LEFT fist",
    "F": "Imagine wiggling your TOES",
    "S": "Imagine pressing your TONGUE to the roof of your mouth",
}


# ==============================================================================
# BACKEND (toolkit-agnostic — identical behaviour to the NiceGUI version)
# ==============================================================================
class SafetyController:
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


class SerialRelay:
    """Talks to Node 3 (Arduino). Auto-finds the port and reconnects if the
    Mega re-enumerates (ttyACM0<->ttyACM1 after a replug/reflash), so a moved
    port never silently kills driving again."""
    def __init__(self, port=SERIAL_PORT, baud=SERIAL_BAUD):
        self.enabled = SERIAL_ENABLED and HAS_SERIAL
        self.baud = baud
        self.ser = None
        self._lock = threading.Lock()
        self._last_try = 0.0
        if self.enabled:
            self._open()
        else:
            print("[SERIAL] Disabled -- commands logged only")

    def _candidates(self):
        import glob
        # stable /dev/serial/by-id symlink first (survives replug), then ttyACM*
        cands = (sorted(glob.glob("/dev/serial/by-id/*Arduino*")) +
                 sorted(glob.glob("/dev/serial/by-id/*0042*")) +
                 sorted(glob.glob("/dev/ttyACM*")) +
                 sorted(glob.glob("/dev/ttyUSB*")))
        seen, out = set(), []
        for c in cands:
            if c not in seen:
                seen.add(c); out.append(c)
        return out or [SERIAL_PORT]

    def _open(self):
        for p in self._candidates():
            try:
                self.ser = serial.Serial(p, self.baud, timeout=1)
                time.sleep(2)                       # Arduino auto-reset settle
                print(f"[SERIAL] Connected: {p} @ {self.baud}")
                return True
            except Exception as e:
                print(f"[SERIAL] open {p} failed: {e}")
        self.ser = None
        return False

    def send(self, cmd):
        if not self.enabled:
            return
        with self._lock:
            if self.ser is None or not self.ser.is_open:
                if time.time() - self._last_try > 1.0:   # throttle reopen tries
                    self._last_try = time.time()
                    self._open()
                if self.ser is None:
                    return
            try:
                self.ser.write(cmd.encode())
                self.ser.flush()
            except Exception as e:
                print(f"[SERIAL] Write error: {e} -- reconnecting")
                try: self.ser.close()
                except Exception: pass
                self.ser = None                          # next send reopens

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()


class UDPListener:
    def __init__(self, ip=UDP_LISTEN_IP, port=UDP_LISTEN_PORT):
        # No SO_REUSEADDR on purpose: a duplicate instance must fail loudly
        # rather than silently split the incoming command packets.
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
        self.sock.settimeout(0.5)
        print(f"[UDP] Listening on {ip}:{port}")

    def receive(self):
        try:
            data, addr = self.sock.recvfrom(8192)   # diagnostics packets are ~1 KB
            return json.loads(data.decode()), addr[0]
        except socket.timeout:
            return None, None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, None

    def close(self):
        self.sock.close()


class DashboardState:
    def __init__(self):
        self._lock = threading.Lock()
        self.current_cmd    = "S"      # the command actually DRIVING the chair
        self.current_conf   = 0.0
        self.current_reason = "WAITING"
        self.mode           = DEFAULT_MODE  # "EEG" | "MANUAL"
        self.eeg_cmd        = "S"      # latest Node 1 prediction (shown even in MANUAL)
        self.eeg_conf       = 0.0
        self.packets_received = 0
        self.last_packet_time = 0.0
        self.command_log    = collections.deque(maxlen=HISTORY_SIZE)
        self.cmd_counts     = {"F": 0, "L": 0, "R": 0, "S": 0, "E": 0}
        self.start_time     = time.time()
        self.node1_ip       = None
        # calibration
        self.cal_running  = False
        self.cal_phase    = ""
        self.cal_cue      = ""
        self.cal_trial    = 0
        self.cal_total    = 0
        self.cal_progress = 0.0
        # Debug/diagnostics (from Node 1)
        self.debug = {}
        self.debug_time = 0.0

    def set_debug(self, d):
        with self._lock:
            self.debug = d
            self.debug_time = time.time()

    def get_mode(self):
        with self._lock:
            return self.mode

    def set_mode(self, m):
        with self._lock:
            if m in ("EEG", "MANUAL"):
                self.mode = m
                return True
            return False

    def note_eeg(self, cmd, conf):
        """Record the latest Node 1 prediction (always, regardless of mode).
        Drives the distribution + connectivity, never the chair."""
        with self._lock:
            self.eeg_cmd = cmd
            self.eeg_conf = conf
            self.packets_received += 1
            self.last_packet_time = time.time()
            self.cmd_counts[cmd] = self.cmd_counts.get(cmd, 0) + 1

    def update(self, cmd, conf, reason):
        """The command actually driving the chair (EEG-relayed or manual)."""
        with self._lock:
            self.current_cmd    = cmd
            self.current_conf   = conf
            self.current_reason = reason
            self.command_log.appendleft({
                "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "cmd": cmd, "conf": conf, "reason": reason,
            })

    def snapshot(self):
        with self._lock:
            return {
                "cmd": self.current_cmd, "conf": self.current_conf,
                "reason": self.current_reason, "mode": self.mode,
                "eeg_cmd": self.eeg_cmd, "eeg_conf": self.eeg_conf,
                "packets": self.packets_received,
                "last_pkt": self.last_packet_time, "counts": dict(self.cmd_counts),
                "uptime": time.time() - self.start_time,
                "log": list(self.command_log)[:12], "node1_ip": self.node1_ip,
                "cal_running": self.cal_running, "cal_phase": self.cal_phase,
                "cal_cue": self.cal_cue, "cal_trial": self.cal_trial,
                "cal_total": self.cal_total, "cal_progress": self.cal_progress,
                "debug": dict(self.debug), "debug_age": time.time() - self.debug_time if self.debug_time else 999,
            }


class CalibrationEngine:
    """Cue-based motor-imagery protocol; tells Node 1 to record + fine-tune."""
    def __init__(self, state):
        self.state = state
        self.running = False
        self._stop = threading.Event()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.running = False

    def _send(self, msg):
        ip = self.state.node1_ip or NODE1_IP_FALLBACK
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(json.dumps(msg).encode(), (ip, NODE1_PORT))
            s.close()
        except Exception as e:
            print(f"[CAL] send failed ({ip}): {e}")

    def _wait(self, secs):
        end = time.time() + secs
        while time.time() < end:
            if self._stop.is_set():
                return True
            time.sleep(0.05)
        return False

    def _run(self):
        classes = list(CAL_CUES.keys())
        trials = classes * CAL_TRIALS_PER_CLASS
        random.shuffle(trials)
        self.state.cal_running = True
        self.state.cal_total = len(trials)
        self._send({"type": "cal_start", "n_trials": len(trials)})
        for i, cue in enumerate(trials):
            if self._stop.is_set():
                break
            self.state.cal_trial = i + 1
            self.state.cal_progress = (i + 1) / len(trials)
            self.state.cal_phase = "fixation"; self.state.cal_cue = ""
            self._send({"type": "cal_phase", "phase": "fixation", "trial": i + 1, "class": cue})
            if self._wait(CAL_FIXATION_S):
                break
            self.state.cal_phase = "imagery"; self.state.cal_cue = cue
            self._send({"type": "cal_phase", "phase": "imagery", "trial": i + 1, "class": cue})
            if self._wait(CAL_IMAGERY_S):
                break
            self.state.cal_phase = "rest"; self.state.cal_cue = ""
            self._send({"type": "cal_phase", "phase": "rest", "trial": i + 1, "class": cue})
            if self._wait(CAL_REST_S):
                break
        if not self._stop.is_set():
            self.state.cal_phase = "training"
            self._send({"type": "cal_train"})
            self.state.cal_phase = "done"
        else:
            self.state.cal_phase = "cancelled"
            self._send({"type": "cal_stop"})
        self.state.cal_running = False
        self.running = False


def apply_manual(safety, relay, state, cmd):
    """Drive command from a human (dashboard touch or phone). Honours mode +
    E-STOP. Returns the reason string (for the web API)."""
    if cmd == "E":
        safety.trigger_estop(); relay.send("E"); state.update("E", 1.0, "E-STOP")
        return "E-STOP"
    if safety.e_stop_active:
        return "E-STOP ACTIVE"
    # Directional commands only take effect in MANUAL mode; STOP always allowed.
    if cmd in ("F", "L", "R") and state.get_mode() != "MANUAL":
        return "IGNORED (EEG mode)"
    safety.process(cmd, 1.0)            # keep SafetyController's current_command in sync
    relay.send(cmd)
    state.update(cmd, 1.0, "MANUAL")
    return "MANUAL"


def command_loop(udp, safety, relay, state, stop_event):
    print("[LOOP] Command processing started")
    pkt_count = 0
    while not stop_event.is_set():
        packet, sender_ip = udp.receive()
        if packet and sender_ip and state.node1_ip != sender_ip:
            state.node1_ip = sender_ip
            print(f"[LOOP] Node 1 address learned: {sender_ip}")
        if packet and "cmd" in packet:
            cmd = packet["cmd"]
            conf = packet.get("conf", 0.0)
            state.note_eeg(cmd, conf)          # always record the prediction
            pkt_count += 1
            if pkt_count % 50 == 0:            # periodic cleanup every 50 packets
                gc.collect()
            if state.get_mode() == "EEG":
                safe_cmd, reason = safety.process(cmd, conf)
                relay.send(safe_cmd)
                state.update(safe_cmd, conf, reason)
            if "rms" in packet or "probs" in packet:
                state.set_debug(packet)
        elif HEARTBEAT_ENABLED and state.get_mode() == "EEG":
            safe_cmd, reason = safety.check_timeouts()
            if reason != "OK":
                relay.send(safe_cmd)
                state.update(safe_cmd, 0.0, reason)
    print("[LOOP] Command processing stopped")


# ==============================================================================
# UI HELPERS
# ==============================================================================
def glow(widget, color, radius=40):
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(radius)
    eff.setColor(QColor(color))
    eff.setOffset(0, 0)
    widget.setGraphicsEffect(eff)


def card(bg="#1a1a2e", border="#2a2a4e", radius=14):
    f = QFrame()
    f.setStyleSheet(
        f"background:{bg}; border:1px solid {border}; border-radius:{radius}px;")
    return f


# ==============================================================================
# DRIVE TAB
# ==============================================================================
class DriveTab(QWidget):
    def __init__(self, state, safety, relay):
        super().__init__()
        self.state, self.safety, self.relay = state, safety, relay
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addLayout(self._left(), 4)
        root.addLayout(self._middle(), 4)
        root.addLayout(self._right(), 4)

    # ---- left: big command + confidence + stats ----
    def _left(self):
        col = QVBoxLayout(); col.setSpacing(6)
        self.cmd_card = QFrame()
        cc = QVBoxLayout(self.cmd_card); cc.setContentsMargins(6, 6, 6, 6)
        self.cmd_letter = QLabel("S"); self.cmd_letter.setAlignment(Qt.AlignCenter)
        self.cmd_letter.setFont(QFont("Arial", 72, QFont.Black))
        self.cmd_sub = QLabel("STOP"); self.cmd_sub.setAlignment(Qt.AlignCenter)
        self.cmd_sub.setFont(QFont("Arial", 15, QFont.Bold))
        self.cmd_sub.setStyleSheet("letter-spacing:4px;")
        cc.addStretch(); cc.addWidget(self.cmd_letter); cc.addWidget(self.cmd_sub); cc.addStretch()
        self.cmd_card.setMinimumHeight(190)
        col.addWidget(self.cmd_card, 1)

        crow = QHBoxLayout()
        clab = QLabel("CONFIDENCE"); clab.setStyleSheet("color:#9ca3af; font-weight:bold;")
        clab.setFont(QFont("Arial", 8))
        self.conf_pct = QLabel("0%"); self.conf_pct.setStyleSheet("color:#e5e7eb; font-weight:bold;")
        self.conf_pct.setAlignment(Qt.AlignRight)
        crow.addWidget(clab); crow.addWidget(self.conf_pct)
        col.addLayout(crow)
        self.conf_bar = QFrame(); self.conf_bar.setFixedHeight(12)
        self.conf_bar.setStyleSheet("background:#1a1a2e; border-radius:6px;")
        self.conf_fill = QFrame(self.conf_bar)
        self.conf_fill.setGeometry(0, 0, 0, 12)
        col.addWidget(self.conf_bar)

        stats = QHBoxLayout()
        self.packets_val = self._stat(stats, "PACKETS", "0")
        self.uptime_val  = self._stat(stats, "UPTIME", "0:00")
        self.status_val  = self._stat(stats, "STATUS", "WAIT", "#f59e0b")
        col.addLayout(stats)
        return col

    def _stat(self, row, label, val, color="#ffffff"):
        c = card()
        v = QVBoxLayout(c); v.setContentsMargins(4, 6, 4, 6)
        val_l = QLabel(val); val_l.setAlignment(Qt.AlignCenter)
        val_l.setFont(QFont("Arial", 16, QFont.Black)); val_l.setStyleSheet(f"color:{color};")
        lab_l = QLabel(label); lab_l.setAlignment(Qt.AlignCenter)
        lab_l.setFont(QFont("Arial", 7)); lab_l.setStyleSheet("color:#6b7280;")
        v.addWidget(val_l); v.addWidget(lab_l)
        row.addWidget(c)
        return val_l

    # ---- middle: manual override + E-STOP + speed ----
    def _middle(self):
        col = QVBoxLayout(); col.setSpacing(6)
        # mode toggle (EEG <-> MANUAL)
        self.mode_btn = QPushButton("MODE: EEG")
        self.mode_btn.setCursor(Qt.PointingHandCursor); self.mode_btn.setMinimumHeight(40)
        self.mode_btn.setFont(QFont("Arial", 13, QFont.Black))
        self.mode_btn.clicked.connect(self.toggle_mode)
        col.addWidget(self.mode_btn)
        title = QLabel("MANUAL CONTROL"); title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color:#6b7280; font-weight:bold; letter-spacing:3px;")
        title.setFont(QFont("Arial", 8))
        col.addWidget(title)
        self.fwd_btn = self._btn("FORWARD (hold)", "#15803d", lambda: self.manual("F"))
        # dead-man's hold: auto-repeat F while pressed, STOP the instant released
        self.fwd_btn.setAutoRepeat(True)
        self.fwd_btn.setAutoRepeatDelay(150)
        self.fwd_btn.setAutoRepeatInterval(180)
        self.fwd_btn.released.connect(lambda: self.manual("S"))
        col.addWidget(self.fwd_btn)
        lr = QHBoxLayout()
        self.left_btn = self._btn("LEFT", "#1d4ed8", lambda: self.manual("L"))
        self.right_btn = self._btn("RIGHT", "#b45309", lambda: self.manual("R"))
        lr.addWidget(self.left_btn); lr.addWidget(self.right_btn)
        col.addLayout(lr)
        col.addWidget(self._btn("STOP", "#b91c1c", lambda: self.manual("S")))
        self.estop = self._btn("E-STOP", "#991b1b", self.do_estop, height=54, big=True)
        col.addWidget(self.estop)
        col.addWidget(self._btn("RESET E-STOP", "#374151", self.do_reset, height=32, small=True))
        sp = QLabel("MAX SPEED"); sp.setAlignment(Qt.AlignCenter)
        sp.setStyleSheet("color:#6b7280; font-weight:bold; letter-spacing:3px;"); sp.setFont(QFont("Arial", 8))
        col.addWidget(sp)
        self.speed_lbl = QLabel(f"{MAX_SPEED}%"); self.speed_lbl.setAlignment(Qt.AlignCenter)
        self.speed_lbl.setFont(QFont("Arial", 14, QFont.Black)); self.speed_lbl.setStyleSheet("color:white;")
        col.addWidget(self.speed_lbl)
        sl = QSlider(Qt.Horizontal); sl.setRange(0, 100); sl.setValue(MAX_SPEED)
        sl.valueChanged.connect(self.set_speed)
        col.addWidget(sl)
        col.addStretch()
        return col

    def _btn(self, text, color, cb, height=44, big=False, small=False):
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(height)
        fs = 18 if big else (11 if small else 14)
        b.setFont(QFont("Arial", fs, QFont.Black))
        b.setStyleSheet(
            f"QPushButton{{background:{color}; color:white; border:none;"
            f" border-radius:12px; letter-spacing:1px;}}"
            f"QPushButton:pressed{{background:{color}; padding-top:2px;}}"
            f"QPushButton:disabled{{background:#1f2937; color:#4b5563;}}")
        b.clicked.connect(cb)
        if big:
            glow(b, "#dc2626", 25)
        return b

    # ---- right: distribution + log ----
    def _right(self):
        col = QVBoxLayout(); col.setSpacing(6)
        dt = QLabel("DISTRIBUTION"); dt.setStyleSheet("color:#6b7280; font-weight:bold; letter-spacing:3px;")
        dt.setFont(QFont("Arial", 8)); col.addWidget(dt)
        self.dist = {}
        for c in ["F", "L", "R", "S"]:
            bar = QFrame(); bar.setFixedHeight(24)
            bar.setStyleSheet("background:#111; border-radius:5px;")
            lab = QLabel(f"{CMD_INFO[c]['label']} 0 (0%)", bar)
            lab.setFont(QFont("Arial", 8, QFont.Bold))
            lab.setStyleSheet(f"color:{CMD_INFO[c]['color']}; background:transparent; padding-left:6px;")
            lab.setGeometry(0, 0, 200, 24)
            fill = QFrame(bar); fill.setGeometry(0, 0, 4, 24)
            fill.setStyleSheet(f"background:{CMD_INFO[c]['color']}33; border-radius:5px;")
            fill.lower()
            self.dist[c] = (bar, fill, lab)
            col.addWidget(bar)
        lt = QLabel("COMMAND LOG"); lt.setStyleSheet("color:#6b7280; font-weight:bold; letter-spacing:3px;")
        lt.setFont(QFont("Arial", 8)); col.addWidget(lt)
        self.log_lbl = QLabel(""); self.log_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.log_lbl.setFont(QFont("monospace", 7)); self.log_lbl.setStyleSheet("color:#9ca3af;")
        self.log_lbl.setWordWrap(False)
        col.addWidget(self.log_lbl, 1)
        return col

    # ---- actions ----
    def manual(self, cmd):
        apply_manual(self.safety, self.relay, self.state, cmd)

    def toggle_mode(self):
        new = "MANUAL" if self.state.get_mode() == "EEG" else "EEG"
        self.state.set_mode(new)
        # leaving a mode: stop the chair so it can't keep a stale command
        if new == "MANUAL":
            apply_manual(self.safety, self.relay, self.state, "S")
        else:
            self.state.update("S", 0.0, "MODE→EEG")

    def do_estop(self):
        self.safety.trigger_estop(); self.relay.send("E"); self.state.update("E", 1.0, "E-STOP")

    def do_reset(self):
        self.safety.reset_estop(); self.relay.send("S"); self.state.update("S", 0.0, "RESET")

    def set_speed(self, v):
        self.safety.max_speed = v
        self.speed_lbl.setText(f"{v}%")

    # ---- refresh (called by MainWindow QTimer) ----
    def refresh(self, snap):
        mode = snap.get("mode", "EEG")
        manual_on = mode == "MANUAL"
        self.mode_btn.setText(f"MODE: {mode}")
        mc = "#7c3aed" if manual_on else "#0891b2"
        self.mode_btn.setStyleSheet(
            f"QPushButton{{background:{mc}; color:white; border:none; border-radius:10px;"
            f" letter-spacing:2px;}} QPushButton:pressed{{padding-top:2px;}}")
        for b in (self.fwd_btn, self.left_btn, self.right_btn):
            b.setEnabled(manual_on)
        cmd = snap["cmd"]; info = CMD_INFO.get(cmd, CMD_INFO["S"])
        self.cmd_letter.setText(cmd)
        self.cmd_letter.setStyleSheet(f"color:{info['color']};")
        glow(self.cmd_letter, info["color"], 45)
        self.cmd_sub.setText(info["label"]); self.cmd_sub.setStyleSheet(f"color:{info['color']}; letter-spacing:4px;")
        self.cmd_card.setStyleSheet(
            f"background:{info['bg']}; border:1px solid {info['color']}44; border-radius:18px;")
        conf = snap["conf"]
        self.conf_pct.setText(f"{conf*100:.0f}%")
        cc = "#22c55e" if conf >= 0.6 else "#f59e0b" if conf >= 0.4 else "#ef4444"
        w = int(self.conf_bar.width() * conf)
        self.conf_fill.setGeometry(0, 0, w, 12)
        self.conf_fill.setStyleSheet(f"background:{cc}; border-radius:6px;")
        self.packets_val.setText(f"{snap['packets']:,}")
        m, s = divmod(int(snap["uptime"]), 60)
        self.uptime_val.setText(f"{m}:{s:02d}")
        self.status_val.setText(snap["reason"][:8])
        sc = "#22c55e" if snap["reason"] == "OK" else "#f59e0b" if snap["reason"] == "MANUAL" else "#ef4444"
        self.status_val.setStyleSheet(f"color:{sc};")
        total = max(sum(snap["counts"].values()), 1)
        for c, (bar, fill, lab) in self.dist.items():
            n = snap["counts"].get(c, 0); pct = n / total * 100
            lab.setText(f"{CMD_INFO[c]['label']} {n} ({pct:.0f}%)")
            fill.setGeometry(0, 0, max(int(bar.width() * pct / 100), 4), 24)
        lines = [f"{e['time']}  {e['cmd']}  {e['conf']*100:.0f}%  {e['reason']}" for e in snap["log"]]
        self.log_lbl.setText("\n".join(lines))


# ==============================================================================
# CALIBRATE TAB
# ==============================================================================
class CalibrateTab(QWidget):
    def __init__(self, state, cal):
        super().__init__()
        self.state, self.cal = state, cal
        col = QVBoxLayout(self); col.setContentsMargins(16, 10, 16, 10); col.setSpacing(8)
        t = QLabel("PERSONAL CALIBRATION"); t.setAlignment(Qt.AlignCenter)
        t.setFont(QFont("Arial", 16, QFont.Black)); t.setStyleSheet("color:white; letter-spacing:3px;")
        col.addWidget(t)
        self.cue = QLabel("Press START to begin"); self.cue.setAlignment(Qt.AlignCenter)
        self.cue.setFont(QFont("Arial", 26, QFont.Black)); self.cue.setStyleSheet("color:#9ca3af;")
        self.cue.setMinimumHeight(150)
        col.addWidget(self.cue, 1)
        self.detail = QLabel(""); self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setFont(QFont("Arial", 11)); self.detail.setStyleSheet("color:#6b7280;")
        col.addWidget(self.detail)
        self.status = QLabel("Ready"); self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color:#6b7280;")
        col.addWidget(self.status)
        row = QHBoxLayout()
        self.start_btn = QPushButton("START CALIBRATION"); self.start_btn.setMinimumHeight(46)
        self.start_btn.setFont(QFont("Arial", 13, QFont.Black))
        self.start_btn.setStyleSheet("background:#15803d; color:white; border:none; border-radius:12px;")
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("CANCEL"); self.cancel_btn.setMinimumHeight(46)
        self.cancel_btn.setFont(QFont("Arial", 13, QFont.Black))
        self.cancel_btn.setStyleSheet("background:#b91c1c; color:white; border:none; border-radius:12px;")
        self.cancel_btn.clicked.connect(self.cancel); self.cancel_btn.hide()
        row.addWidget(self.start_btn); row.addWidget(self.cancel_btn)
        col.addLayout(row)

    def start(self):
        self.cal.start(); self.start_btn.hide(); self.cancel_btn.show()

    def cancel(self):
        self.cal.stop(); self.start_btn.show(); self.cancel_btn.hide()

    def refresh(self, snap):
        if snap["cal_running"]:
            ph, cue, tr, tot = snap["cal_phase"], snap["cal_cue"], snap["cal_trial"], snap["cal_total"]
            self.status.setText(f"Trial {tr}/{tot} — {ph.upper()}")
            if ph == "fixation":
                self.cue.setText("+"); self.cue.setStyleSheet("color:#ffffff;"); self.detail.setText("")
            elif ph == "imagery" and cue in CAL_CUES:
                self.cue.setText(CMD_INFO[cue]["label"]); self.cue.setStyleSheet(f"color:{CMD_INFO[cue]['color']};")
                self.detail.setText(CAL_CUES[cue])
            elif ph == "rest":
                self.cue.setText("Rest..."); self.cue.setStyleSheet("color:#6b7280;"); self.detail.setText("")
            elif ph == "training":
                self.cue.setText("Training model..."); self.cue.setStyleSheet("color:#f59e0b;")
                self.detail.setText("Node 1 is fine-tuning on your data")
        elif snap["cal_phase"] == "done":
            self.cue.setText("Calibration Complete!"); self.cue.setStyleSheet("color:#22c55e;")
            self.detail.setText(""); self.start_btn.show(); self.cancel_btn.hide()
        elif snap["cal_phase"] == "cancelled":
            self.cue.setText("Cancelled"); self.cue.setStyleSheet("color:#ef4444;")
            self.start_btn.show(); self.cancel_btn.hide()


# ==============================================================================
# SETTINGS TAB
# ==============================================================================
class SettingsTab(QWidget):
    def __init__(self, state, relay):
        super().__init__()
        self.state = state
        grid = QGridLayout(self); grid.setContentsMargins(24, 14, 24, 14); grid.setVerticalSpacing(6)
        rows = [
            ("Node 1 IP", "—", "node1"),
            ("UDP Listen Port", str(UDP_LISTEN_PORT), None),
            ("Heartbeat Timeout", f"{HEARTBEAT_TIMEOUT}s", None),
            ("Command Timeout", f"{COMMAND_TIMEOUT}s", None),
            ("Serial (Arduino)", "CONNECTED" if relay.enabled else "DISABLED", None),
            ("Serial Port", SERIAL_PORT, None),
            ("Phone control", f"http://192.168.4.2:{WEB_PORT}" if WEB_ENABLED else "DISABLED", None),
            ("Calibration trials/class", str(CAL_TRIALS_PER_CLASS), None),
        ]
        self.node1_val = None
        for i, (k, v, tag) in enumerate(rows):
            kl = QLabel(k); kl.setStyleSheet("color:#9ca3af;"); kl.setFont(QFont("Arial", 11))
            vl = QLabel(v); vl.setStyleSheet("color:white;"); vl.setFont(QFont("monospace", 11))
            vl.setAlignment(Qt.AlignRight)
            grid.addWidget(kl, i, 0); grid.addWidget(vl, i, 1)
            if tag == "node1":
                self.node1_val = vl
        grid.setRowStretch(len(rows), 1)

    def refresh(self, snap):
        if self.node1_val is not None:
            self.node1_val.setText(snap["node1_ip"] or "not heard yet")


# ==============================================================================
# DEBUG / DEV TAB  — per-channel signals + model internals + diagnostics
# ==============================================================================
CH_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7"]


class Sparkline(QWidget):
    """Lightweight live waveform (no external plotting lib)."""
    def __init__(self, color="#3b82f6"):
        super().__init__()
        self.color = color
        self.values = []
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, vals, color=None):
        self.values = vals or []
        if color:
            self.color = color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0d0d16"))
        # midline
        p.setPen(QPen(QColor("#222"), 1))
        p.drawLine(0, h // 2, w, h // 2)
        if len(self.values) < 2:
            return
        vmin, vmax = min(self.values), max(self.values)
        rng = (vmax - vmin) or 1.0
        pen = QPen(QColor(self.color)); pen.setWidth(2)
        p.setPen(pen)
        n = len(self.values)
        prev = None
        for i, v in enumerate(self.values):
            x = i / (n - 1) * (w - 4) + 2
            y = h - 3 - (v - vmin) / rng * (h - 6)
            pt = QPointF(x, y)
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt


class DebugTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        root = QVBoxLayout(self); root.setContentsMargins(10, 8, 10, 8); root.setSpacing(6)

        # ---- per-channel signals ----
        head = QLabel("LIVE CHANNELS (filtered µV, 8–30 Hz)  —  contact = lead-off proxy")
        head.setStyleSheet("color:#6b7280; font-weight:bold; letter-spacing:2px;")
        head.setFont(QFont("Arial", 8))
        root.addWidget(head)
        self.rows = []
        for i in range(4):
            row = QHBoxLayout(); row.setSpacing(8)
            name = QLabel("--"); name.setFixedWidth(40)
            name.setFont(QFont("Arial", 13, QFont.Black))
            name.setStyleSheet(f"color:{CH_COLORS[i]};")
            spark = Sparkline(CH_COLORS[i])
            rms = QLabel("— µV"); rms.setFixedWidth(70); rms.setAlignment(Qt.AlignRight)
            rms.setFont(QFont("monospace", 10)); rms.setStyleSheet("color:#e5e7eb;")
            pp = QLabel("pp —"); pp.setFixedWidth(72); pp.setAlignment(Qt.AlignRight)
            pp.setFont(QFont("monospace", 9)); pp.setStyleSheet("color:#9ca3af;")
            contact = QLabel("—"); contact.setFixedWidth(52); contact.setAlignment(Qt.AlignCenter)
            contact.setFont(QFont("Arial", 8, QFont.Black))
            contact.setStyleSheet("color:#6b7280; background:#1f2937; border-radius:6px; padding:2px;")
            row.addWidget(name); row.addWidget(spark, 1)
            row.addWidget(rms); row.addWidget(pp); row.addWidget(contact)
            root.addLayout(row, 1)
            self.rows.append((name, spark, rms, pp, contact))

        # ---- model probabilities + diagnostics ----
        bottom = QHBoxLayout(); bottom.setSpacing(14)
        # probs
        probcol = QVBoxLayout(); probcol.setSpacing(3)
        pt = QLabel("MODEL OUTPUT (raw softmax)")
        pt.setStyleSheet("color:#6b7280; font-weight:bold; letter-spacing:2px;"); pt.setFont(QFont("Arial", 8))
        probcol.addWidget(pt)
        self.probbars = {}
        for c in ["F", "L", "R", "S"]:
            bar = QFrame(); bar.setFixedHeight(20)
            bar.setStyleSheet("background:#111; border-radius:4px;")
            fill = QFrame(bar); fill.setGeometry(0, 0, 4, 20)
            fill.setStyleSheet(f"background:{CMD_INFO[c]['color']}55; border-radius:4px;")
            lab = QLabel(f"{c} 0%", bar); lab.setGeometry(0, 0, 220, 20)
            lab.setFont(QFont("monospace", 9, QFont.Bold))
            lab.setStyleSheet(f"color:{CMD_INFO[c]['color']}; background:transparent; padding-left:6px;")
            probcol.addWidget(bar)
            self.probbars[c] = (bar, fill, lab)
        bottom.addLayout(probcol, 1)

        # diagnostics
        diagcol = QVBoxLayout(); diagcol.setSpacing(3)
        dt = QLabel("DIAGNOSTICS")
        dt.setStyleSheet("color:#6b7280; font-weight:bold; letter-spacing:2px;"); dt.setFont(QFont("Arial", 8))
        diagcol.addWidget(dt)
        self.diag = {}
        for key, label in [("link", "Node 1 feed"), ("raw", "raw cmd"), ("vote", "vote"),
                           ("infer", "inference"), ("fs", "sample rate"), ("ip", "Node 1 IP")]:
            r = QHBoxLayout()
            k = QLabel(label); k.setStyleSheet("color:#9ca3af;"); k.setFont(QFont("Arial", 9))
            v = QLabel("—"); v.setAlignment(Qt.AlignRight); v.setFont(QFont("monospace", 9)); v.setStyleSheet("color:white;")
            r.addWidget(k); r.addWidget(v)
            diagcol.addLayout(r)
            self.diag[key] = v
        diagcol.addStretch()
        bottom.addLayout(diagcol, 1)
        root.addLayout(bottom, 1)

    def refresh(self, snap):
        d = snap.get("debug") or {}
        fresh = snap.get("debug_age", 999) < 2.0
        chans = d.get("ch", ["C3", "Cz", "C4", "CPz"])
        rms = d.get("rms", []); pp = d.get("pp", []); wave = d.get("wave", [])
        loff = d.get("loff", [])   # optional true ADS1299 lead-off bits (1=off)
        for i, (name, spark, rms_l, pp_l, contact) in enumerate(self.rows):
            name.setText(chans[i] if i < len(chans) else f"ch{i+1}")
            if fresh and i < len(wave):
                spark.set_values(wave[i])
            rms_l.setText(f"{rms[i]:.0f} µV" if i < len(rms) else "— µV")
            pp_l.setText(f"pp {pp[i]:.0f}" if i < len(pp) else "pp —")
            # contact: prefer real lead-off bit if Node 1 sends it, else pp railed-proxy
            if not fresh:
                txt, fg, bg = "—", "#6b7280", "#1f2937"
            elif i < len(loff):
                off = bool(loff[i])
                txt, fg, bg = ("OFF", "#fca5a5", "#7f1d1d") if off else ("OK", "#86efac", "#14532d")
            elif i < len(pp):
                off = pp[i] > CONTACT_PP_THRESHOLD
                txt, fg, bg = ("OFF", "#fca5a5", "#7f1d1d") if off else ("OK", "#86efac", "#14532d")
            else:
                txt, fg, bg = "—", "#6b7280", "#1f2937"
            contact.setText(txt)
            contact.setStyleSheet(f"color:{fg}; background:{bg}; border-radius:6px; padding:2px;")
        probs = d.get("probs", [])
        for i, c in enumerate(["F", "L", "R", "S"]):
            pr = probs[i] if i < len(probs) else 0.0
            bar, fill, lab = self.probbars[c]
            lab.setText(f"{c}  {pr*100:.0f}%")
            fill.setGeometry(0, 0, max(int(bar.width() * pr), 4), bar.height())
        self.diag["link"].setText("● LIVE" if fresh else "○ stale")
        self.diag["link"].setStyleSheet("color:%s;" % ("#22c55e" if fresh else "#ef4444"))
        self.diag["raw"].setText(str(d.get("raw", "—")))
        self.diag["vote"].setText(str(d.get("vote", "—")))
        self.diag["infer"].setText(f"{d.get('infer_ms', '—')} ms")
        self.diag["fs"].setText(f"{d.get('fs', '—')} Hz")
        self.diag["ip"].setText(snap.get("node1_ip") or "—")


# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class MainWindow(QMainWindow):
    def __init__(self, state, safety, relay, cal, windowed=False):
        super().__init__()
        self.state = state
        self.setWindowTitle("NeuroDrive")
        central = QWidget(); self.setCentralWidget(central)
        outer = QVBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # header
        header = QWidget(); header.setFixedHeight(46)
        header.setStyleSheet("background:#0f0f23;")
        h = QHBoxLayout(header); h.setContentsMargins(14, 0, 14, 0)
        logo = QLabel("◆ NEURODRIVE"); logo.setFont(QFont("Arial", 14, QFont.Black))
        logo.setStyleSheet("color:white; letter-spacing:3px;")
        self.node1_pill = QLabel("NODE 1: --"); self.node1_pill.setFont(QFont("monospace", 9))
        self.node1_pill.setStyleSheet("color:#9ca3af; background:#1f2937; border-radius:8px; padding:4px 10px;")
        h.addWidget(logo); h.addStretch(); h.addWidget(self.node1_pill)
        outer.addWidget(header)

        # tabs
        self.tabs = QTabWidget()
        self.drive = DriveTab(state, safety, relay)
        self.calib = CalibrateTab(state, cal)
        self.debug = DebugTab(state)
        self.settings = SettingsTab(state, relay)
        self.tabs.addTab(self.drive, "DRIVE")
        self.tabs.addTab(self.calib, "CALIBRATE")
        self.tabs.addTab(self.debug, "DEBUG")
        self.tabs.addTab(self.settings, "SETTINGS")
        outer.addWidget(self.tabs, 1)

        # dev: ND_START_TAB=DRIVE|CALIBRATE|DEBUG|SETTINGS (or index) to pick opening tab
        _start = os.environ.get("ND_START_TAB", "").strip().upper()
        _names = {"DRIVE": 0, "CALIBRATE": 1, "DEBUG": 2, "SETTINGS": 3}
        if _start in _names:
            self.tabs.setCurrentIndex(_names[_start])
        elif _start.isdigit():
            self.tabs.setCurrentIndex(int(_start))

        self.setStyleSheet(self.qss())

        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(100)
        if windowed:
            self.resize(800, 480)
        else:
            self.showFullScreen()

    def tick(self):
        snap = self.state.snapshot()
        self.drive.refresh(snap)
        self.calib.refresh(snap)
        self.debug.refresh(snap)
        self.settings.refresh(snap)
        ago = time.time() - snap["last_pkt"] if snap["last_pkt"] > 0 else 999
        if ago < 1:
            self.node1_pill.setText("NODE 1: CONNECTED")
            self.node1_pill.setStyleSheet("color:#86efac; background:#14532d; border-radius:8px; padding:4px 10px;")
        elif ago < HEARTBEAT_TIMEOUT:
            self.node1_pill.setText(f"NODE 1: {ago:.0f}s ago")
            self.node1_pill.setStyleSheet("color:#fcd34d; background:#78350f; border-radius:8px; padding:4px 10px;")
        else:
            self.node1_pill.setText("NODE 1: DISCONNECTED")
            self.node1_pill.setStyleSheet("color:#fca5a5; background:#7f1d1d; border-radius:8px; padding:4px 10px;")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    @staticmethod
    def qss():
        return """
        QWidget { background:#0a0a0a; color:#e5e7eb; }
        QTabWidget::pane { border:0; background:#0a0a0a; }
        QTabBar::tab { background:#0f0f23; color:#9ca3af; padding:8px 26px;
                       margin-right:2px; font-weight:bold; min-width:90px; }
        QTabBar::tab:selected { color:white; border-bottom:3px solid #3b82f6; }
        QPushButton:disabled { background:#1f2937; color:#4b5563; }
        QSlider::groove:horizontal { height:6px; background:#1a1a2e; border-radius:3px; }
        QSlider::handle:horizontal { background:#3b82f6; width:18px; margin:-7px 0; border-radius:9px; }
        QSlider::sub-page:horizontal { background:#3b82f6; border-radius:3px; }
        """


# ==============================================================================
# PHONE WEB CONTROL  — tiny stdlib HTTP server, shares safety/relay/state
# ==============================================================================
import http.server

WEB_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>NeuroDrive</title><style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none}
body{margin:0;background:#0a0a0a;color:#e5e7eb;font-family:Arial,sans-serif;
 padding:14px;max-width:520px;margin:auto}
h1{font-size:18px;letter-spacing:3px;margin:4px 0 10px}
.row{display:flex;gap:10px;margin:10px 0}
button{flex:1;border:none;border-radius:14px;color:#fff;font-weight:900;
 font-size:20px;padding:22px 0;letter-spacing:1px}
button:active{transform:translateY(2px)}
button:disabled{background:#1f2937 !important;color:#4b5563}
#mode{font-size:18px;padding:16px 0}
.f{background:#15803d}.l{background:#1d4ed8}.r{background:#b45309}.s{background:#b91c1c}
.e{background:#991b1b;font-size:24px;padding:26px 0;box-shadow:0 0 18px #dc2626aa}
.reset{background:#374151;font-size:14px;padding:12px 0}
#bar{display:flex;justify-content:space-between;font-size:13px;color:#9ca3af;margin-top:6px}
#big{text-align:center;font-size:64px;font-weight:900;margin:6px 0}
#sub{text-align:center;font-size:13px;color:#6b7280;letter-spacing:2px;margin-top:-6px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}
</style></head><body>
<h1>◆ NEURODRIVE</h1>
<button id="mode" onclick="toggleMode()">MODE: …</button>
<div id="big">S</div><div id="sub">STOP</div>
<div class="row"><button class="f" id="bF">HOLD TO GO</button></div>
<div class="row"><button class="l" id="bL" onclick="cmd('L')">LEFT</button>
<button class="r" id="bR" onclick="cmd('R')">RIGHT</button></div>
<div class="row"><button class="s" onclick="cmd('S')">STOP</button></div>
<div class="row"><button class="e" onclick="estop()">E-STOP</button></div>
<div class="row"><button class="reset" onclick="reset()">RESET E-STOP</button></div>
<div id="bar"><span id="link"><span class="dot" style="background:#6b7280"></span>…</span>
<span id="eeg">EEG: —</span><span id="pkts">0 pkts</span></div>
<script>
const CMI={F:['FORWARD','#22c55e'],L:['LEFT','#3b82f6'],R:['RIGHT','#f59e0b'],
 S:['STOP','#ef4444'],E:['E-STOP','#dc2626']};
let mode='EEG';
function post(u){fetch(u,{method:'POST'}).then(tick)}
function cmd(c){post('/api/cmd/'+c)}
function estop(){post('/api/estop')}
function reset(){post('/api/reset')}
function toggleMode(){post('/api/mode/'+(mode==='EEG'?'MANUAL':'EEG'))}
// FORWARD = dead-man's hold: repeat F while pressed, STOP the instant you let go.
let goTimer=null;
function goStart(ev){ev.preventDefault();if(goTimer)return;cmd('F');
 goTimer=setInterval(()=>cmd('F'),180);}
function goStop(){if(!goTimer)return;clearInterval(goTimer);goTimer=null;cmd('S');}
(function(){const b=document.getElementById('bF');
 b.addEventListener('pointerdown',goStart);
 ['pointerup','pointerleave','pointercancel'].forEach(e=>b.addEventListener(e,goStop));})();
function tick(){fetch('/api/status').then(r=>r.json()).then(s=>{
 mode=s.mode;
 const mb=document.getElementById('mode');
 mb.textContent='MODE: '+s.mode;
 mb.style.background=s.mode==='MANUAL'?'#7c3aed':'#0891b2';
 const man=s.mode==='MANUAL';
 ['bF','bL','bR'].forEach(id=>document.getElementById(id).disabled=!man);
 const ci=CMI[s.cmd]||CMI.S;
 const big=document.getElementById('big');big.textContent=s.cmd;big.style.color=ci[1];
 document.getElementById('sub').textContent=ci[0];
 const ec=CMI[s.eeg_cmd]||CMI.S;
 document.getElementById('eeg').textContent='EEG: '+s.eeg_cmd+' '+Math.round(s.eeg_conf*100)+'%';
 document.getElementById('pkts').textContent=s.packets+' pkts';
 const lk=document.getElementById('link');
 const col=s.connected?'#22c55e':'#ef4444';
 lk.innerHTML='<span class="dot" style="background:'+col+'"></span>'+(s.connected?'NODE 1':'no link');
})}
setInterval(tick,400);tick();
</script></body></html>"""


def make_web_handler(safety, relay, state):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"   # keep-alive: phones reuse one connection
        timeout = 15                    # drop idle/dead phone connections

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, WEB_PAGE, "text/html; charset=utf-8")
            elif self.path == "/api/status":
                snap = state.snapshot()
                connected = (time.time() - snap["last_pkt"]) < 1.0 if snap["last_pkt"] else False
                self._send(200, json.dumps({
                    "mode": snap["mode"], "cmd": snap["cmd"], "conf": snap["conf"],
                    "reason": snap["reason"], "eeg_cmd": snap["eeg_cmd"],
                    "eeg_conf": snap["eeg_conf"], "estop": safety.e_stop_active,
                    "packets": snap["packets"], "connected": connected,
                }))
            else:
                self._send(404, "{}")

        def do_POST(self):
            p = self.path
            if p.startswith("/api/cmd/"):
                apply_manual(safety, relay, state, p.rsplit("/", 1)[1][:1].upper())
            elif p.startswith("/api/mode/"):
                state.set_mode(p.rsplit("/", 1)[1].upper())
                if state.get_mode() == "MANUAL":
                    apply_manual(safety, relay, state, "S")
            elif p == "/api/estop":
                apply_manual(safety, relay, state, "E")
            elif p == "/api/reset":
                safety.reset_estop(); relay.send("S"); state.update("S", 0.0, "RESET")
            else:
                self._send(404, "{}"); return
            self._send(200, '{"ok":true}')
    return Handler


def start_web_server(safety, relay, state):
    try:
        httpd = http.server.ThreadingHTTPServer(
            ("0.0.0.0", WEB_PORT), make_web_handler(safety, relay, state))
    except OSError as e:
        print(f"[WEB] Could not bind :{WEB_PORT} — {e}")
        return None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[WEB] Phone control on http://0.0.0.0:{WEB_PORT}  (Pi AP IP 192.168.4.2)")
    return httpd


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    windowed = "--windowed" in sys.argv
    print("=" * 60)
    print("  NEURODRIVE -- NODE 2 | NATIVE TOUCHSCREEN APP (PyQt5)")
    print(f"  Serial: {'ENABLED' if SERIAL_ENABLED else 'DISABLED'}")
    print(f"  UDP: {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}   Mode: {'windowed' if windowed else 'fullscreen'}")
    print("=" * 60)

    state  = DashboardState()
    safety = SafetyController()
    relay  = SerialRelay()
    cal    = CalibrationEngine(state)
    udp    = UDPListener()
    stop_event = threading.Event()

    t = threading.Thread(target=command_loop, args=(udp, safety, relay, state, stop_event), daemon=True)
    t.start()

    if WEB_ENABLED:
        start_web_server(safety, relay, state)

    app = QApplication(sys.argv)
    app.setApplicationName("NeuroDrive")
    win = MainWindow(state, safety, relay, cal, windowed=windowed)
    win.show()
    try:
        rc = app.exec_()
    finally:
        stop_event.set()
        t.join(timeout=2)
        relay.close()
        udp.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
