"""
================================================================================
NEURODRIVE — NODE 1 | CORAL HARDWARE PIPELINE
================================================================================
Production script for the Google Coral Dev Board Mini.

Replaces SITL components with real hardware:
    - spidev ADS1299 read loop (instead of MOABB replay)
    - TFLite Edge TPU inference (instead of PyTorch GPU)
    - WiFi UDP command TX to Node 2 (instead of terminal display)
    - Calibration listener: records labeled EEG + auto fine-tunes

Prerequisites (on Coral / Mendel Linux):
    1. NeuroDrive PCB connected via SPI
    2. EEG cap with 4 electrodes (ADS1299-4): C3, Cz, C4, CPz
    3. Model compiled for Edge TPU:
       $ edgetpu_compiler models/EEGNet_*_int8.tflite
    4. WiFi AP configured (Coral hosts AP, Pi 5 connects as client)

Usage:
    python node1_coral.py

================================================================================
"""

import os
import time
import threading
import collections
import sys
import json
import socket
from pathlib import Path
from datetime import datetime

import numpy as np
from scipy.signal import iirnotch, butter, sosfilt, sosfilt_zi, tf2sos

# ==============================================================================
# CONFIGURATION
# ==============================================================================

FS             = 250
BUFFER_SIZE    = FS          # 1 second rolling window
# 4-channel ADS1299-4 hat. Montage is the standard motor-imagery set;
# adjust to match the board's actual electrode wiring if different.
CHANNELS       = ["C3", "Cz", "C4", "CPz"]
N_CH           = len(CHANNELS)   # 4 — matches ADS1299-4 hardware
DSP_INTERVAL_S = 0.5         # inference every 500ms
SAMPLE_INTERVAL = 1.0 / FS   # 4ms between samples

# EEGNet class mapping (must match training)
CLASS_NAMES = ["F", "L", "R", "S"]
# LOCK: training's LabelEncoder assigns class indices in ALPHABETICAL order, so
# this exact order defines what each model output index means. Reordering it
# silently scrambles every wheelchair command. Keep it sorted (F, L, R, S).
assert CLASS_NAMES == sorted(CLASS_NAMES), "CLASS_NAMES must stay alphabetical (F,L,R,S)"

# Confidence + smoothing (same as SITL inference)
CONFIDENCE_THRESHOLD = 0.40
VOTE_WINDOW          = 3

# Online adaptation — pseudo-label accumulation + micro fine-tune
ADAPT_CONFIDENCE     = 0.80    # only pseudo-label when confidence > this
ADAPT_BUFFER_SIZE    = 50      # micro fine-tune every N confident predictions
ADAPT_MICRO_EPOCHS   = 5       # quick fine-tune epochs per batch
ADAPT_LR             = 0.00005 # very low LR to avoid catastrophic forgetting
ADAPT_ENABLED        = True    # toggle online adaptation

# WiFi UDP target — Node 2 (Raspberry Pi 5) connects to Coral's AP
# Coral AP is typically 192.168.4.1, Pi gets 192.168.4.x
NODE2_IP   = "192.168.4.2"
NODE2_PORT = 5000

# Model paths — look for Edge TPU model first, fall back to float32
MODELS_DIR     = Path(__file__).parent / "models"
EDGETPU_MODEL  = None  # set after scanning models dir
FLOAT32_MODEL  = None

# ADS1299 SPI config (matches reference implementation backend.py)
SPI_BUS     = 0
SPI_DEVICE  = 0
SPI_SPEED   = 1000000   # 1 MHz (default, safer than 2 MHz)

# ADS1299 data conversion (matches reference implementation config_hardware.py)
# GAIN = 24 (default), VREF from NeuroDrive PCB (NOT the ADS internal 4.5V)
ADS_GAIN    = 24
ADS_VREF    = 2.64      # NeuroDrive PCB reference voltage (measured)
ADS_LSB     = (2.0 / ADS_GAIN) / (2**24 - 1)  # LSB in volts per VREF

# ADS1299 SPI commands
ADS_RREG    = 0x20
ADS_WREG    = 0x40
ADS_RDATAC  = 0x10
ADS_SDATAC  = 0x11
ADS_RDATA   = 0x12
ADS_START   = 0x08      # begin conversions (DRDY won't toggle without this)

# LED GPIO pins (Coral Dev Board Mini)
LED_CAPTURE   = 28   # purple LED — on during capture
LED_INFERENCE = 30   # blue LED — blinks on each inference

# Calibration listener port (receives cue commands from Node 2 dashboard)
CAL_LISTEN_PORT = 5001

# Calibration data directory
CAL_DIR = Path(__file__).parent / "calibration_data"
CAL_DIR.mkdir(exist_ok=True)

# Log directory
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


# ==============================================================================
# HARDWARE DETECTION
# ==============================================================================

def is_coral():
    """Check if running on Google Coral Dev Board Mini."""
    try:
        with open("/sys/firmware/devicetree/base/model", "r") as f:
            return "Coral" in f.read()
    except FileNotFoundError:
        return False


RUNNING_ON_CORAL = is_coral()


# ==============================================================================
# ADS1299 SPI READER (hardware only)
# ==============================================================================

class ADS1299Reader:
    """
    Reads 8-channel 24-bit EEG samples from ADS1299 via SPI.

    Based on reference implementation/hardware/backend.py — uses the same register
    config, data conversion, and DRDY handling that the original NeuroDrive uses.

    Data conversion chain (matches NeuroDrive exactly):
        raw 24-bit -> 2's complement -> microvolts
        uV = raw_signed * 1e6 * VREF * ADS_LSB
        where ADS_LSB = (2/GAIN) / (2^24 - 1)

    Also reads lead-off status bytes for electrode contact detection.
    """

    # Channel modes (matches ADS1299 config mod_config)
    CHANNEL_MODES = {
        "simple":   0x60,  # Normal measurement, gain=24, SRB2 enabled
        "bias":     0x62,  # BIAS measurement (MUX=010)
        "disabled": 0x81,  # Power down + input shorted (PD=1, MUX=001)
        "test":     0x65,  # Test signal output (MUX=101)
        "temp":     0x64,  # Temperature sensor (MUX=100)
    }

    # Datarate register values (CONFIG1 bits [2:0])
    DATARATES = {
        250: 0x06, 500: 0x05, 1000: 0x04, 2000: 0x03,
        4000: 0x02, 8000: 0x01, 16000: 0x00,
    }

    def __init__(self, bus=SPI_BUS, device=SPI_DEVICE, speed=SPI_SPEED,
                 channel_modes=None, test_signal=False):
        if not RUNNING_ON_CORAL:
            raise RuntimeError("ADS1299Reader requires Coral hardware (spidev)")

        import spidev
        from periphery import GPIO

        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = speed
        self.spi.mode = 0b01   # CPOL=0, CPHA=1 (ADS1299 mode)

        # DRDY pin — active low, signals new data ready
        # Uses edge polling like NeuroDrive (not busy-wait)
        # DRDY = gpiochip0 line 45 on the Coral (matches Portiloop's proven
        # backend.py for hardware_version 2 — line 27 here was a transcription
        # bug that left read_sample() blocking on edges that never came).
        self.drdy = GPIO("/dev/gpiochip0", 45, "in", edge="falling")

        # Default: all channels active in simple mode. test_signal routes the
        # ADS1299's internal square-wave generator to every channel — a bench
        # self-test that needs no electrodes.
        self._test_signal = test_signal
        if test_signal:
            channel_modes = ["test"] * N_CH
        elif channel_modes is None:
            channel_modes = ["simple"] * N_CH

        # Lead-off status (updated every read)
        self.loff_statp = 0    # positive electrode lead-off (8 bits, 1=off)
        self.loff_statn = 0    # negative electrode lead-off (8 bits, 1=off)

        # --- Verify the ADS1299 BEFORE entering continuous-read mode ---
        # Register reads only work in command mode (SDATAC). Reading the ID
        # register while in RDATAC returns streamed data bytes instead, which
        # is what produced the bogus "0x00 -> 4 channels" misread.
        self.spi.xfer2([ADS_SDATAC])
        time.sleep(0.01)
        id_reg  = self._read_reg(0x00)
        nu_ch   = id_reg & 0x03                       # ID[1:0] = NU_CH
        n_ch_hw = {0: 4, 1: 6, 2: 8}.get(nu_ch)
        # ID[4] is hard-wired to 1 on a real ADS1299; 0x00/0xFF mean no/bad SPI.
        if (id_reg & 0x10) == 0 or id_reg in (0x00, 0xFF) or n_ch_hw is None:
            print(f"[ADS1299] WARNING: invalid ID register 0x{id_reg:02X} -- "
                  f"check hat seating / SPI wiring (expected 8-channel ADS1299)")
            n_ch_hw = N_CH
        elif n_ch_hw != N_CH:
            print(f"[ADS1299] WARNING: chip reports {n_ch_hw} channels but "
                  f"code expects N_CH={N_CH}")

        # Configure registers (this re-enters continuous-read mode at the end)
        self._configure_registers(channel_modes)

        print(f"[ADS1299] SPI bus={bus} dev={device} speed={speed//1000}kHz "
              f"channels={n_ch_hw} VREF={ADS_VREF}V (ID=0x{id_reg:02X})")

    def _write_reg(self, reg, value):
        """Write a single ADS1299 register."""
        self.spi.xfer2([ADS_WREG | (reg & 0x1F), 0x00, value])

    def _read_reg(self, reg):
        """Read a single ADS1299 register."""
        result = self.spi.xfer2([ADS_RREG | (reg & 0x1F), 0x00, 0x00])
        return result[2]

    def _configure_registers(self, channel_modes):
        """
        Configure ADS1299 registers for EEG acquisition.
        Matches reference implementation config_hardware.py register layout.
        """
        # Stop continuous read mode
        self.spi.xfer2([ADS_SDATAC])
        time.sleep(0.01)

        # CONFIG1 (reg 0x01): set datarate to 250 SPS
        # Base value 0x90 (daisy disabled, CLK output disabled)
        # OR with datarate bits
        config1 = 0x90 | self.DATARATES.get(FS, 0x06)
        self._write_reg(0x01, config1)

        # CONFIG2 (reg 0x02): 0xD0 enables the internal test-signal generator
        # (INT_CAL=1) for the bench self-test; 0xC0 = off for normal acquisition.
        self._write_reg(0x02, 0xD0 if self._test_signal else 0xC0)

        # CONFIG3 (reg 0x03): internal reference, bias enabled
        # PD_REFBUF=1, BIAS_MEAS=0, BIASREF_INT=1, PD_BIAS=1
        self._write_reg(0x03, 0xEC)

        # LOFF (reg 0x04): lead-off detection disabled for now
        # (can be enabled later for electrode quality monitoring)
        self._write_reg(0x04, 0x00)

        # CHnSET registers (0x05-0x0C): per-channel configuration
        bias_sensp = 0x00
        bias_sensn = 0x00
        for ch, mode in enumerate(channel_modes):
            reg_val = self.CHANNEL_MODES.get(mode, 0x81)
            self._write_reg(0x05 + ch, reg_val)
            # Active channels contribute to BIAS circuit
            if mode == "simple":
                bias_sensp |= (1 << ch)
                bias_sensn |= (1 << ch)

        # BIAS_SENSP (reg 0x0D) and BIAS_SENSN (reg 0x0E)
        self._write_reg(0x0D, bias_sensp)
        self._write_reg(0x0E, bias_sensn)

        # LOFF_SENSP/N (regs 0x0F-0x10): no lead-off sensing
        self._write_reg(0x0F, 0x00)
        self._write_reg(0x10, 0x00)

        # LOFF_FLIP (reg 0x11): normal polarity
        self._write_reg(0x11, 0x00)

        # GPIO (reg 0x14): all as output
        self._write_reg(0x14, 0x00)

        # MISC1 (reg 0x15): enable SRB1 (reference buffer)
        self._write_reg(0x15, 0x20)

        # Begin conversions (START), then enter continuous-read mode.
        # Without START the ADC never converts and DRDY never toggles.
        self.spi.xfer2([ADS_START])
        time.sleep(0.01)
        self.spi.xfer2([ADS_RDATAC])
        time.sleep(0.01)

        print(f"[ADS1299] Config: {FS} SPS, modes={channel_modes}")
        print(f"[ADS1299] BIAS: SENSP=0x{bias_sensp:02X} SENSN=0x{bias_sensn:02X}")

    def read_sample(self):
        """
        Read one 8-channel sample from ADS1299.

        Uses DRDY edge polling (like NeuroDrive), not busy-wait.
        Also parses lead-off status bytes for electrode quality monitoring.

        Returns
        -------
        sample : np.ndarray, shape (8,), dtype float64 — microvolts
        """
        # Wait for DRDY falling edge (tuple style)
        self.drdy.poll(timeout=None)
        self.drdy.read_event()

        # Read: 3 status bytes + N_CH channels * 3 bytes each
        raw = self.spi.xfer2([0x00] * (3 + N_CH * 3))

        # Parse lead-off status from status bytes
        # Byte 0: [1100 LOFF_STATP[7:4]]
        # Byte 1: [LOFF_STATP[3:0] LOFF_STATN[7:4]]
        # Byte 2: [LOFF_STATN[3:0] GPIO[3:0]]
        self.loff_statp = ((raw[0] & 0x0F) << 4) | ((raw[1] & 0xF0) >> 4)
        self.loff_statn = ((raw[1] & 0x0F) << 4) | ((raw[2] & 0xF0) >> 4)

        # Parse 8 channels: 24-bit -> 2's complement -> microvolts
        # Matches NeuroDrive: uV = filter_2scomplement(raw) * 1e6 * VREF * ADS_LSB
        raw_values = np.array([
            (raw[3 + ch*3] << 16) | (raw[4 + ch*3] << 8) | raw[5 + ch*3]
            for ch in range(N_CH)
        ], dtype=np.int32)

        # 2's complement (matches filter_2scomplement_np)
        raw_signed = np.where(
            (raw_values & (1 << 23)) != 0,
            raw_values - (1 << 24),
            raw_values
        )

        # Scale to microvolts (matches filter_scale)
        sample_uv = raw_signed.astype(np.float64) * 1e6 * ADS_VREF * ADS_LSB

        return sample_uv

    def get_loff_status(self):
        """
        Check which electrodes have lost contact.

        Returns
        -------
        bad_channels : list of int — channel indices with lead-off detected
        """
        bad = []
        for ch in range(N_CH):
            if (self.loff_statp >> ch) & 1 or (self.loff_statn >> ch) & 1:
                bad.append(ch)
        return bad

    def close(self):
        self.spi.close()


# ==============================================================================
# TFLITE EDGE TPU INFERENCE
# ==============================================================================

class TFLiteInferenceEngine:
    """
    Runs EEGNet inference on the Coral Edge TPU via TFLite.

    The int8 quantized model compiled with edgetpu_compiler runs fully
    on the Edge TPU coprocessor, achieving ~2-5ms inference latency.

    If no Edge TPU model is found, falls back to float32 TFLite on CPU.
    """

    def __init__(self, model_path):
        try:
            from tflite_runtime.interpreter import Interpreter
            from tflite_runtime.interpreter import load_delegate
            # Try Edge TPU delegate first
            if "_edgetpu" in str(model_path):
                self.interpreter = Interpreter(
                    str(model_path),
                    experimental_delegates=[load_delegate("libedgetpu.so.1")]
                )
                print(f"[MODEL] Edge TPU: {model_path.name}")
            else:
                self.interpreter = Interpreter(str(model_path))
                print(f"[MODEL] TFLite CPU: {model_path.name}")
        except ImportError:
            # Fallback: use full tensorflow
            import tensorflow as tf
            self.interpreter = tf.lite.Interpreter(str(model_path))
            print(f"[MODEL] TFLite (tf): {model_path.name}")

        self.interpreter.allocate_tensors()
        self.input_details  = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        inp = self.input_details[0]
        out = self.output_details[0]
        print(f"[MODEL] Input:  {inp['shape']}  dtype={inp['dtype']}")
        print(f"[MODEL] Output: {out['shape']}  dtype={out['dtype']}")

        # Quantization params — try both formats:
        #   NeuroDrive uses:      details[i]["quantization"] -> (scale, zero_point) tuple
        #   Some TFLite builds:  details[i]["quantization_parameters"] -> dict with "scales"/"zero_points"
        self.input_scale, self.input_zero = self._get_quant_params(inp)
        self.output_scale, self.output_zero = self._get_quant_params(out)
        self.is_int8 = (inp["dtype"] == np.int8 or inp["dtype"] == np.uint8)

        if self.is_int8:
            print(f"[MODEL] Quantized: input_scale={self.input_scale:.6f} "
                  f"input_zero={self.input_zero} output_scale={self.output_scale:.6f} "
                  f"output_zero={self.output_zero}")

    @staticmethod
    def _get_quant_params(details):
        """
        Extract quantization scale and zero_point from TFLite tensor details.
        Handles both formats:
          - tuple style: details["quantization"] -> (scale, zero_point)
          - Newer TFLite:    details["quantization_parameters"] -> dict
        """
        # Try NeuroDrive format first (tuple)
        q = details.get("quantization")
        if q is not None and isinstance(q, (tuple, list)) and len(q) == 2:
            scale, zero = q
            if scale != 0.0:
                return float(scale), int(zero)

        # Try newer format (dict with arrays)
        qp = details.get("quantization_parameters", {})
        if qp:
            scales = qp.get("scales", [1.0])
            zeros  = qp.get("zero_points", [0])
            if len(scales) > 0 and scales[0] != 0.0:
                return float(scales[0]), int(zeros[0])

        # No quantization
        return 1.0, 0

    def predict(self, window, data_in_uv=False):
        """
        Run inference on a 1-second EEG window.

        Parameters
        ----------
        window     : np.ndarray, shape (250, 8) — time x channels
        data_in_uv : bool — True if data is already in microvolts (hardware),
                     False if in volts (SITL, needs * 1e6)

        Returns
        -------
        command    : str
        confidence : float
        probs      : np.ndarray, shape (4,)
        """
        # Reshape: (250, 8) -> (1, 1, 8, 250)
        x = window.T[np.newaxis, np.newaxis, :, :].astype(np.float32)

        # Scale V -> uV only if input is in volts (SITL mode)
        if not data_in_uv:
            x *= 1e6

        if self.is_int8:
            # Quantize float -> int8 (matches TFLite forward pass)
            # Formula: quantized = (float_value / scale) + zero_point
            inp_dtype = self.input_details[0]["dtype"]
            x = (x / self.input_scale + self.input_zero).astype(inp_dtype)

        self.interpreter.set_tensor(self.input_details[0]["index"], x)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])

        if self.is_int8:
            # Dequantize int8 -> float (matches TFLite forward pass)
            # Formula: float_value = (quantized - zero_point) * scale
            output = (output.astype(np.float32) - self.output_zero) * self.output_scale

        # Softmax (TFLite model outputs raw logits)
        logits = output[0]
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        pred_idx   = int(np.argmax(probs))
        command    = CLASS_NAMES[pred_idx]
        confidence = float(probs[pred_idx])

        return command, confidence, probs


# ==============================================================================
# PYTORCH INFERENCE (fallback for non-Coral)
# ==============================================================================

class PyTorchInferenceEngine:
    """Fallback inference using PyTorch (for testing on laptop)."""

    def __init__(self, model_path):
        import torch
        import torch.nn.functional as F
        self.torch = torch
        self.F = F

        # Import EEGNet from training script
        sys.path.insert(0, str(Path(__file__).parent))
        from node1_training import EEGNet

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = EEGNet()
        self.model.load_state_dict(
            torch.load(str(model_path), weights_only=True, map_location=self.device)
        )
        self.model.to(self.device)
        self.model.eval()
        total = sum(p.numel() for p in self.model.parameters())
        print(f"[MODEL] PyTorch: {model_path.name} ({total:,} params) on {self.device}")

    def predict(self, window, data_in_uv=False):
        x = window.T[np.newaxis, np.newaxis, :, :].astype(np.float32)
        if not data_in_uv:
            x *= 1e6
        x_tensor = self.torch.from_numpy(x).to(self.device)
        with self.torch.no_grad():
            logits = self.model(x_tensor)
            probs = self.F.softmax(logits, dim=1).cpu().numpy()[0]
        pred_idx   = int(np.argmax(probs))
        command    = CLASS_NAMES[pred_idx]
        confidence = float(probs[pred_idx])
        return command, confidence, probs


# ==============================================================================
# DSP FILTER CHAIN (same as SITL — no changes needed)
# ==============================================================================

class FilterChain:
    """Stateful multi-channel DSP: Notch (50Hz) -> Bandpass (8-30Hz)."""

    def __init__(self, n_channels=N_CH):
        # Notch
        b, a = iirnotch(50.0, 30.0, FS)
        self.notch_sos = tf2sos(b, a)
        # Bandpass
        self.bp_sos = butter(4, [8.0, 30.0], btype="bandpass", fs=FS, output="sos")
        # Zero-init state (avoids unit-step transient)
        notch_zi = sosfilt_zi(self.notch_sos)
        bp_zi    = sosfilt_zi(self.bp_sos)
        self.notch_zi = [np.zeros_like(notch_zi) for _ in range(n_channels)]
        self.bp_zi    = [np.zeros_like(bp_zi)    for _ in range(n_channels)]

    def process(self, sample):
        filtered = np.empty(len(sample), dtype=np.float64)
        for i in range(len(sample)):
            x = np.array([sample[i]], dtype=np.float64)
            x, self.notch_zi[i] = sosfilt(self.notch_sos, x, zi=self.notch_zi[i])
            x, self.bp_zi[i]    = sosfilt(self.bp_sos,    x, zi=self.bp_zi[i])
            filtered[i] = x[0]
        return filtered


# ==============================================================================
# SHARED STATE (same as SITL)
# ==============================================================================

class SharedState:
    def __init__(self, buffer_size):
        self._lock   = threading.Lock()
        self._buffer = collections.deque(maxlen=buffer_size)

    def push(self, filtered_sample):
        with self._lock:
            self._buffer.append(filtered_sample.copy())

    def snapshot(self):
        with self._lock:
            return list(self._buffer)

    @property
    def is_ready(self):
        with self._lock:
            return len(self._buffer) == self._buffer.maxlen


# ==============================================================================
# COMMAND SMOOTHER (same as SITL inference)
# ==============================================================================

class CommandSmoother:
    def __init__(self, window_size=VOTE_WINDOW):
        self.window_size = window_size
        self.history = collections.deque(maxlen=window_size)
        self.last_command = "S"

    def update(self, command, confidence):
        if confidence < CONFIDENCE_THRESHOLD:
            return self.last_command, "LOW_CONF"
        self.history.append(command)
        if len(self.history) < self.window_size:
            return self.last_command, "FILLING"
        counts = {}
        for cmd in self.history:
            counts[cmd] = counts.get(cmd, 0) + 1
        max_count = max(counts.values())
        winners = [cmd for cmd, cnt in counts.items() if cnt == max_count]
        if len(winners) == 1:
            self.last_command = winners[0]
            return self.last_command, "VOTE"
        return self.last_command, "TIE"


# ==============================================================================
# WIFI COMMAND SENDER
# ==============================================================================

class CommandSender:
    """Sends wheelchair commands to Node 2 (Pi 5) via UDP."""

    def __init__(self, ip=NODE2_IP, port=NODE2_PORT):
        self.addr = (ip, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_cmd = None
        print(f"[WIFI] UDP target: {ip}:{port}")

    def send(self, command, confidence, extra=None):
        payload = {
            "cmd":  command,
            "conf": round(confidence, 3),
            "ts":   time.time(),
        }
        if extra:
            payload.update(extra)   # per-channel + model diagnostics for the dashboard Debug tab
        packet = json.dumps(payload).encode()
        try:
            self.sock.sendto(packet, self.addr)
        except OSError:
            pass  # Pi not connected yet — silently drop

    def close(self):
        self.sock.close()


# ==============================================================================
# LED CONTROL (Coral only)
# ==============================================================================

class LEDController:
    def __init__(self):
        self.enabled = RUNNING_ON_CORAL
        if self.enabled:
            try:
                from periphery import GPIO
                self.capture_led   = GPIO("/dev/gpiochip2", LED_CAPTURE, "out")
                self.inference_led = GPIO("/dev/gpiochip2", LED_INFERENCE, "out")
            except Exception as e:
                # Status LEDs are cosmetic — never let a missing/!wired GPIO
                # chip (e.g. this board only exposes gpiochip0) crash Node 1.
                print(f"[LED] Disabled (no usable GPIO for LEDs: {e})")
                self.enabled = False

    def capture_on(self):
        if self.enabled:
            self.capture_led.write(True)

    def capture_off(self):
        if self.enabled:
            self.capture_led.write(False)

    def inference_blink(self):
        if self.enabled:
            self.inference_led.write(True)
            time.sleep(0.05)
            self.inference_led.write(False)

    def close(self):
        if self.enabled:
            self.capture_led.write(False)
            self.inference_led.write(False)


# ==============================================================================
# STREAM THREAD (hardware version)
# ==============================================================================

def run_stream_thread_hardware(ads_reader, filter_chain, shared_state, stop_event):
    """Read from ADS1299 at 250 SPS, filter, push to buffer."""
    print("[STREAM] ADS1299 hardware stream started...")
    sample_count = 0
    last_loff_check = time.time()
    loff_check_interval = 5.0  # check lead-off every 5s

    while not stop_event.is_set():
        try:
            sample = ads_reader.read_sample()   # blocks until DRDY (uV)
            filtered = filter_chain.process(sample)
            shared_state.push(filtered)
            sample_count += 1

            # Periodic lead-off check
            now = time.time()
            if now - last_loff_check > loff_check_interval:
                last_loff_check = now
                bad = ads_reader.get_loff_status()
                if bad:
                    bad_names = [CHANNELS[i] for i in bad if i < len(CHANNELS)]
                    print(f"[WARN] Electrode lead-off: {bad_names} "
                          f"-- check gel/contact")

        except Exception as e:
            print(f"[STREAM] SPI read error: {e}")
            time.sleep(0.001)

    print(f"[STREAM] Stopped after {sample_count:,} samples "
          f"({sample_count/FS:.1f}s)")


def run_stream_thread_sitl(shared_state, filter_chain, stop_event, max_seconds=60):
    """SITL fallback: replay BCI-IV-2a data (for testing on laptop)."""
    sys.path.insert(0, str(Path(__file__).parent))
    from node1_sitl_pipeline import load_bci_data

    raw_array, events_list, fs = load_bci_data()
    max_samples = int(max_seconds * fs)

    print(f"[STREAM] SITL mode: replaying {max_seconds}s at {FS} SPS...")
    t_next = time.perf_counter()

    for i in range(min(len(raw_array), max_samples)):
        if stop_event.is_set():
            break

        remaining = t_next - time.perf_counter()
        if remaining > 0.002:
            time.sleep(remaining - 0.002)
        while time.perf_counter() < t_next:
            pass
        t_next += SAMPLE_INTERVAL

        filtered = filter_chain.process(raw_array[i])
        shared_state.push(filtered)

    print(f"[STREAM] SITL finished")
    stop_event.set()


# ==============================================================================
# ONLINE ADAPTER (pseudo-label accumulation + micro fine-tune)
# ==============================================================================

class OnlineAdapter:
    """
    Tracks brain drift by accumulating high-confidence predictions as
    pseudo-labels and periodically micro fine-tuning Block 3 + classifier.

    Why this works:
    - EEG signals drift over a session (fatigue, electrode impedance,
      mental state changes). A static model slowly degrades.
    - High-confidence predictions (>80%) are very likely correct, so they
      serve as free labeled data.
    - We only update the separable conv + classifier (same freeze strategy
      as calibration), so the universal temporal/spatial features stay intact.
    - Very low LR (5e-5) and few epochs (5) per batch prevent catastrophic
      forgetting of the calibration data.

    Safety:
    - Only PyTorch models can be adapted (TFLite is frozen by design).
    - If adaptation degrades performance, the calibration model is still
      saved on disk — restart to revert.
    - Logs every adaptation step for post-session analysis.
    """

    def __init__(self, engine):
        self.enabled = ADAPT_ENABLED and hasattr(engine, 'model')
        self.engine = engine

        if not self.enabled:
            if ADAPT_ENABLED:
                print("[ADAPT] Disabled -- online adaptation requires PyTorch engine")
            else:
                print("[ADAPT] Disabled by config")
            return

        self.label_to_idx = {c: i for i, c in enumerate(CLASS_NAMES)}

        # Pseudo-label buffer
        self.windows = []     # raw (250, 8) windows in volts
        self.labels = []      # int class indices
        self.total_adapted = 0
        self.adapt_count = 0

        # Set up optimizer for unfrozen params only
        self._setup_optimizer()

        print(f"[ADAPT] Online adaptation enabled: "
              f"conf>{ADAPT_CONFIDENCE*100:.0f}%, "
              f"batch={ADAPT_BUFFER_SIZE}, "
              f"lr={ADAPT_LR}")

    def _setup_optimizer(self):
        """Freeze Block 1+2, prepare optimizer for Block 3 + classifier."""
        import torch
        import torch.nn as nn
        self.torch = torch
        self.nn = nn

        model = self.engine.model

        # Freeze everything first
        for param in model.parameters():
            param.requires_grad = False

        # Unfreeze Block 3 + classifier
        for name, param in model.named_parameters():
            if any(k in name for k in ["sep_depthwise", "sep_pointwise",
                                        "bn3", "classifier"]):
                param.requires_grad = True

        trainable = [p for p in model.parameters() if p.requires_grad]
        self.optimizer = torch.optim.Adam(trainable, lr=ADAPT_LR)
        self.criterion = nn.CrossEntropyLoss()

        n_trainable = sum(p.numel() for p in trainable)
        print(f"[ADAPT] Trainable params: {n_trainable:,}")

    def accumulate(self, window, command, confidence):
        """
        Called after every inference. If confidence is high enough,
        store as pseudo-labeled training sample.
        """
        if not self.enabled:
            return

        if confidence < ADAPT_CONFIDENCE:
            return

        if command not in self.label_to_idx:
            return

        self.windows.append(window.copy())
        self.labels.append(self.label_to_idx[command])

        # Check if we have enough for a micro fine-tune
        if len(self.windows) >= ADAPT_BUFFER_SIZE:
            self._micro_finetune()

    def _micro_finetune(self):
        """Run a quick fine-tune on the accumulated pseudo-labeled data."""
        torch = self.torch
        model = self.engine.model
        device = self.engine.device

        n = len(self.windows)
        self.adapt_count += 1

        # Prepare batch: (n, 250, 8) -> (n, 1, 8, 250), scale V -> uV
        X = np.array(self.windows)
        X = X.transpose(0, 2, 1)[:, np.newaxis, :, :].astype(np.float32) * 1e6
        y = np.array(self.labels)

        X_t = torch.from_numpy(X).to(device)
        y_t = torch.from_numpy(y).long().to(device)

        # Class distribution in this batch
        dist = {CLASS_NAMES[i]: int(np.sum(y == i)) for i in range(len(CLASS_NAMES))}

        # Micro fine-tune
        model.train()
        # Keep frozen BN in eval mode (same fix as calibration)
        for m in model.modules():
            if isinstance(m, self.nn.BatchNorm2d) and not m.weight.requires_grad:
                m.eval()

        losses = []
        for epoch in range(ADAPT_MICRO_EPOCHS):
            self.optimizer.zero_grad()
            logits = model(X_t)
            loss = self.criterion(logits, y_t)
            loss.backward()
            self.optimizer.step()

            # Apply max_norm constraint
            if hasattr(model, 'apply_max_norm'):
                model.apply_max_norm()

            losses.append(loss.item())

        # Back to eval mode for inference
        model.eval()

        self.total_adapted += n
        avg_loss = sum(losses) / len(losses)

        print(f"[ADAPT] Micro fine-tune #{self.adapt_count}: "
              f"{n} samples, loss={avg_loss:.4f}, "
              f"dist={dist}, total_adapted={self.total_adapted}")

        # Clear buffer
        self.windows = []
        self.labels = []

    def get_stats(self):
        """Return adaptation stats for logging."""
        if not self.enabled:
            # Disabled adapter never initializes its buffers — return defaults
            # so the inference thread's logging doesn't crash.
            return {"enabled": False, "buffer_size": 0,
                    "adapt_count": 0, "total_adapted": 0}
        return {
            "enabled": self.enabled,
            "buffer_size": len(self.windows),
            "adapt_count": self.adapt_count,
            "total_adapted": self.total_adapted,
        }


# ==============================================================================
# INFERENCE THREAD
# ==============================================================================

def run_inference_thread(shared_state, stop_event, engine, smoother,
                         sender, leds, adapter, data_in_uv=False):
    """Classify every 0.5s and send commands to Node 2."""
    print(f"[INFER] Thread started (data_in_uv={data_in_uv})...")

    step   = 0
    t_next = time.perf_counter() + DSP_INTERVAL_S

    # Profiling accumulators
    profile_infer_ms  = []
    profile_smooth_ms = []
    profile_total_ms  = []

    while not stop_event.is_set():
        remaining = t_next - time.perf_counter()
        if remaining > 0:
            time.sleep(min(remaining, 0.01))
            continue
        t_next += DSP_INTERVAL_S

        if not shared_state.is_ready:
            continue

        buf = shared_state.snapshot()
        if len(buf) < BUFFER_SIZE:
            continue

        t_total_start = time.perf_counter()
        window = np.array(buf, dtype=np.float64)

        # Inference
        t_start = time.perf_counter()
        raw_cmd, confidence, probs = engine.predict(window, data_in_uv=data_in_uv)
        t_infer = (time.perf_counter() - t_start) * 1000

        # Smoothing
        t_start = time.perf_counter()
        smooth_cmd, vote_status = smoother.update(raw_cmd, confidence)
        t_smooth = (time.perf_counter() - t_start) * 1000

        # Online adaptation — accumulate high-confidence pseudo-labels
        adapter.accumulate(window, raw_cmd, confidence)

        # LED blink
        leds.inference_blink()

        # Per-channel + model diagnostics for the dashboard Debug tab.
        # window is (BUFFER_SIZE, N_CH) filtered µV.
        ch_rms = np.sqrt(np.mean(window ** 2, axis=0))
        ch_pp  = window.max(axis=0) - window.min(axis=0)
        ds     = window[::10, :]            # ~25 pts/ch downsampled sparkline
        debug = {
            "raw":      raw_cmd,
            "vote":     vote_status,
            "probs":    [round(float(p), 3) for p in probs],
            "rms":      [round(float(x), 1) for x in ch_rms],
            "pp":       [round(float(x), 1) for x in ch_pp],
            "wave":     [[round(float(v), 1) for v in ds[:, c]]
                         for c in range(window.shape[1])],
            "ch":       CHANNELS,
            "infer_ms": round(t_infer, 1),
            "fs":       FS,
        }

        # Send to Node 2 (command + diagnostics)
        sender.send(smooth_cmd, confidence, debug)

        t_total = (time.perf_counter() - t_total_start) * 1000

        # Profile
        profile_infer_ms.append(t_infer)
        profile_smooth_ms.append(t_smooth)
        profile_total_ms.append(t_total)

        # Display
        step += 1
        adapt_stats = adapter.get_stats()
        adapt_buf = adapt_stats["buffer_size"] if adapt_stats["enabled"] else "-"
        prob_str = "  ".join(f"{c}:{p*100:4.1f}%" for c, p in zip(CLASS_NAMES, probs))
        print(f"[#{step:04d}]  {prob_str}  | raw={raw_cmd}({confidence*100:.0f}%)  "
              f"smooth={smooth_cmd}({vote_status})  {t_infer:.1f}ms  "
              f"adapt={adapt_buf}/{ADAPT_BUFFER_SIZE}")

    # Session summary with profiling
    print(f"\n[INFER] Stopped after {step} windows")
    if step > 0:
        print(f"[PROFILE] Inference: avg={np.mean(profile_infer_ms):.1f}ms  "
              f"max={np.max(profile_infer_ms):.1f}ms  "
              f"min={np.min(profile_infer_ms):.1f}ms")
        print(f"[PROFILE] Smooth:    avg={np.mean(profile_smooth_ms):.3f}ms")
        print(f"[PROFILE] Total:     avg={np.mean(profile_total_ms):.1f}ms  "
              f"budget={DSP_INTERVAL_S*1000:.0f}ms  "
              f"headroom={DSP_INTERVAL_S*1000 - np.mean(profile_total_ms):.0f}ms")
    adapt_stats = adapter.get_stats()
    if adapt_stats["enabled"]:
        print(f"[ADAPT] Session total: {adapt_stats['adapt_count']} adaptations, "
              f"{adapt_stats['total_adapted']} pseudo-labeled samples")


# ==============================================================================
# CALIBRATION RECORDER
# ==============================================================================

class CalibrationRecorder:
    """
    Records labeled EEG data during calibration sessions.

    Listens for control packets from Node 2 dashboard:
        {"type": "cal_start", "n_trials": 100}
        {"type": "cal_phase", "phase": "imagery", "trial": 1, "class": "L"}
        {"type": "cal_phase", "phase": "fixation"|"rest", ...}
        {"type": "cal_train"}
        {"type": "cal_stop"}

    During "imagery" phases, continuously grabs 1-second windows from
    SharedState and stores them with the cued class label. After recording,
    runs fine-tuning and sends results back to Node 2.
    """

    def __init__(self, shared_state, stop_event):
        self.shared_state = shared_state
        self.stop_event = stop_event
        self.recording = False
        self.current_class = None
        self.current_phase = None

        # Recorded data: list of (window, label) pairs
        self.windows = []
        self.labels = []

        # UDP listener
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", CAL_LISTEN_PORT))
        self.sock.settimeout(0.2)
        print(f"[CAL] Listening for calibration commands on port {CAL_LISTEN_PORT}")

    def run(self):
        """Main calibration listener loop — runs in its own thread."""
        while not self.stop_event.is_set():
            # Check for control packets
            try:
                data, addr = self.sock.recvfrom(1024)
                msg = json.loads(data.decode())
                self._handle_message(msg, addr)
            except socket.timeout:
                pass
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

            # If in imagery phase, record EEG windows
            if self.recording and self.current_phase == "imagery" and self.current_class:
                if self.shared_state.is_ready:
                    buf = self.shared_state.snapshot()
                    if len(buf) >= BUFFER_SIZE:
                        window = np.array(buf, dtype=np.float64)
                        self.windows.append(window)
                        self.labels.append(self.current_class)
                        # Don't grab overlapping windows too fast
                        time.sleep(DSP_INTERVAL_S)
                else:
                    time.sleep(0.01)
            else:
                time.sleep(0.01)

        self.sock.close()

    def _handle_message(self, msg, addr):
        msg_type = msg.get("type", "")

        if msg_type == "cal_start":
            n_trials = msg.get("n_trials", 100)
            print(f"[CAL] Calibration started ({n_trials} trials)")
            self.windows = []
            self.labels = []
            self.recording = True

        elif msg_type == "cal_phase":
            self.current_phase = msg.get("phase", "")
            self.current_class = msg.get("class", "")
            trial = msg.get("trial", 0)

            if self.current_phase == "imagery":
                print(f"[CAL] Trial {trial} -- RECORDING class={self.current_class}")
            elif self.current_phase == "fixation":
                print(f"[CAL] Trial {trial} -- fixation")

        elif msg_type == "cal_train":
            self.recording = False
            self.current_phase = None
            print(f"[CAL] Recording done: {len(self.windows)} windows, "
                  f"{len(set(self.labels))} classes")
            self._save_and_finetune(addr)

        elif msg_type == "cal_stop":
            self.recording = False
            self.current_phase = None
            print("[CAL] Calibration cancelled")
            self.windows = []
            self.labels = []

    def _save_and_finetune(self, dashboard_addr):
        """Save recorded data and run fine-tuning."""
        if len(self.windows) == 0:
            print("[CAL] No data recorded, skipping fine-tune")
            return

        # Save raw calibration data
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = CAL_DIR / f"cal_data_{timestamp}.npz"

        X = np.array(self.windows)  # (n_windows, 250, 8)
        y = np.array(self.labels)   # (n_windows,) string labels

        np.savez(save_path, X=X, y=y, channels=CHANNELS, fs=FS)
        print(f"[CAL] Saved {len(X)} windows to {save_path.name}")
        print(f"[CAL] Class distribution: ", end="")
        for cls in CLASS_NAMES:
            count = np.sum(y == cls)
            print(f"{cls}={count} ", end="")
        print()

        # Run fine-tuning
        print("[CAL] Starting fine-tuning...")
        base_accuracy, new_accuracy = self._run_finetune(X, y)

        # Send results back to dashboard
        result_packet = json.dumps({
            "type": "cal_result",
            "accuracy": round(new_accuracy * 100, 1),
            "base_accuracy": round(base_accuracy * 100, 1),
        }).encode()

        try:
            result_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Send to dashboard's UDP listener port (NODE2_PORT = 5000)
            result_sock.sendto(result_packet, (dashboard_addr[0], NODE2_PORT))
            result_sock.close()
            print(f"[CAL] Sent results to dashboard: "
                  f"base={base_accuracy*100:.1f}% -> personal={new_accuracy*100:.1f}%")
        except Exception as e:
            print(f"[CAL] Failed to send results: {e}")

    def _run_finetune(self, X_windows, y_labels):
        """
        Fine-tune the current model on recorded calibration data.

        X_windows: (n, 250, 8) — raw filtered EEG windows
        y_labels:  (n,) — string class labels ('L','R','F','S')

        Returns (base_accuracy, new_accuracy) on a held-out test split.
        """
        try:
            import torch
            import torch.nn as nn
            from sklearn.model_selection import StratifiedShuffleSplit

            sys.path.insert(0, str(Path(__file__).parent))
            from node1_training import EEGNet
            from node1_calibrate import finetune_train

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            # Find the current .pt model to fine-tune
            pt_models = sorted(MODELS_DIR.glob("*.pt"), reverse=True)
            if not pt_models:
                print("[CAL] No .pt model found for fine-tuning")
                return 0.0, 0.0

            base_path = pt_models[0]
            print(f"[CAL] Base model: {base_path.name}")

            # Encode labels: string -> int
            label_to_idx = {c: i for i, c in enumerate(CLASS_NAMES)}
            y_int = np.array([label_to_idx[l] for l in y_labels])

            # Reshape: (n, 250, 8) -> (n, 1, 8, 250) and scale V -> uV
            X_4d = X_windows.transpose(0, 2, 1)[:, np.newaxis, :, :].astype(np.float32) * 1e6

            # Split 70/15/15
            sss1 = StratifiedShuffleSplit(n_splits=1, test_size=0.3, random_state=42)
            tr_idx, tmp_idx = next(sss1.split(X_4d, y_int))

            sss2 = StratifiedShuffleSplit(n_splits=1, test_size=0.5, random_state=42)
            vl_sub, te_sub = next(sss2.split(X_4d[tmp_idx], y_int[tmp_idx]))
            vl_idx = tmp_idx[vl_sub]
            te_idx = tmp_idx[te_sub]

            X_tr, y_tr   = X_4d[tr_idx], y_int[tr_idx]
            X_val, y_val = X_4d[vl_idx], y_int[vl_idx]
            X_te, y_te   = X_4d[te_idx], y_int[te_idx]

            print(f"[CAL] Train: {len(X_tr)} | Val: {len(X_val)} | Test: {len(X_te)}")

            # Load base model
            model = EEGNet()
            model.load_state_dict(torch.load(str(base_path), weights_only=True))

            # Evaluate base accuracy on test set
            model.to(device)
            model.eval()
            with torch.no_grad():
                logits = model(torch.from_numpy(X_te).float().to(device))
                base_preds = logits.argmax(1).cpu().numpy()
            base_accuracy = float(np.mean(base_preds == y_te))

            # Freeze Block 1+2, train Block 3 + classifier
            for param in model.parameters():
                param.requires_grad = False
            for name, param in model.named_parameters():
                if any(k in name for k in ["sep_depthwise", "sep_pointwise",
                                            "bn3", "classifier"]):
                    param.requires_grad = True

            # Fine-tune
            model = finetune_train(model, X_tr, y_tr, X_val, y_val, device)

            # Evaluate new accuracy
            model.eval()
            with torch.no_grad():
                logits = model(torch.from_numpy(X_te).float().to(device))
                new_preds = logits.argmax(1).cpu().numpy()
            new_accuracy = float(np.mean(new_preds == y_te))

            # Save personal model
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_name = f"EEGNet_personal_{timestamp}.pt"
            torch.save(model.state_dict(), str(MODELS_DIR / save_name))
            print(f"[CAL] Saved: {save_name}")
            print(f"[CAL] Base: {base_accuracy*100:.1f}% -> Personal: {new_accuracy*100:.1f}%")

            return base_accuracy, new_accuracy

        except Exception as e:
            print(f"[CAL] Fine-tuning failed: {e}")
            import traceback
            traceback.print_exc()
            return 0.0, 0.0


# ==============================================================================
# MODEL DISCOVERY
# ==============================================================================

def find_model():
    """Find the best available model in priority order."""
    # 1. Edge TPU compiled model
    edgetpu_models = sorted(MODELS_DIR.glob("*_edgetpu.tflite"), reverse=True)
    if edgetpu_models:
        return edgetpu_models[0], "edgetpu"

    # 2. Int8 TFLite
    int8_models = sorted(MODELS_DIR.glob("*_int8.tflite"), reverse=True)
    if int8_models:
        return int8_models[0], "tflite"

    # 3. Float32 TFLite
    f32_models = sorted(MODELS_DIR.glob("*.tflite"), reverse=True)
    if f32_models:
        return f32_models[0], "tflite"

    # 4. PyTorch .pt (fallback for laptop testing)
    pt_models = sorted(MODELS_DIR.glob("*.pt"), reverse=True)
    if pt_models:
        return pt_models[0], "pytorch"

    return None, None


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 60)
    print("  NEURODRIVE -- NODE 1 | CORAL PIPELINE")
    print(f"  Hardware: {'CORAL' if RUNNING_ON_CORAL else 'SITL (laptop)'}")
    print(f"  Timestamp: {timestamp}")
    print("=" * 60)

    # ── Find model ────────────────────────────────────────────────────
    model_path, model_type = find_model()
    if model_path is None:
        print("[ERROR] No model found in models/")
        print("[ERROR] Run node1_training.py first.")
        return

    print(f"\n[INIT] Model: {model_path.name} (type={model_type})")

    try:
        if model_type in ("edgetpu", "tflite"):
            engine = TFLiteInferenceEngine(model_path)
        else:
            engine = PyTorchInferenceEngine(model_path)
    except ImportError as e:
        print(f"[ERROR] Could not load {model_type} inference engine: {e}")
        if model_type == "pytorch":
            print("[ERROR] PyTorch is not installed on this device (expected on the "
                  "Coral). Provide a .tflite/_edgetpu model built via "
                  "node1_training.export_models instead.")
        return

    # ── Build components ──────────────────────────────────────────────
    filter_chain = FilterChain()
    shared_state = SharedState(BUFFER_SIZE)
    smoother     = CommandSmoother()
    sender       = CommandSender()
    leds         = LEDController()
    adapter      = OnlineAdapter(engine)
    stop_event   = threading.Event()

    print(f"[INIT] Channels: {CHANNELS}")
    print(f"[INIT] Confidence threshold: {CONFIDENCE_THRESHOLD*100:.0f}%")
    print(f"[INIT] Vote window: {VOTE_WINDOW}")
    print()

    # ── Start capture LED ─────────────────────────────────────────────
    leds.capture_on()

    # ── Launch threads ────────────────────────────────────────────────
    if RUNNING_ON_CORAL:
        ads_reader = ADS1299Reader(
            test_signal=os.environ.get("ND_TEST_SIGNAL", "") == "1")
        if ads_reader._test_signal:
            print("[INIT] *** INTERNAL TEST-SIGNAL MODE *** "
                  "(square wave on all channels; electrodes ignored)")
        stream_thread = threading.Thread(
            target=run_stream_thread_hardware,
            args=(ads_reader, filter_chain, shared_state, stop_event),
            daemon=True,
        )
    else:
        stream_thread = threading.Thread(
            target=run_stream_thread_sitl,
            args=(shared_state, filter_chain, stop_event, 60),
            daemon=True,
        )

    # Hardware outputs microvolts directly, SITL outputs volts (needs * 1e6)
    infer_thread = threading.Thread(
        target=run_inference_thread,
        args=(shared_state, stop_event, engine, smoother, sender, leds, adapter),
        kwargs={"data_in_uv": RUNNING_ON_CORAL},
        daemon=True,
    )

    # Calibration listener -- always running, waits for dashboard commands
    cal_recorder = CalibrationRecorder(shared_state, stop_event)
    cal_thread = threading.Thread(
        target=cal_recorder.run,
        daemon=True,
        name="CalibrationThread",
    )

    stream_thread.start()
    infer_thread.start()
    cal_thread.start()

    # ── Wait ──────────────────────────────────────────────────────────
    try:
        stream_thread.join()
    except KeyboardInterrupt:
        print("\n[MAIN] Shutting down...")
        stop_event.set()

    infer_thread.join(timeout=3.0)
    cal_thread.join(timeout=2.0)

    # ── Cleanup ───────────────────────────────────────────────────────
    leds.capture_off()
    leds.close()
    sender.close()
    if RUNNING_ON_CORAL:
        ads_reader.close()

    print("[MAIN] Pipeline stopped.")


if __name__ == "__main__":
    main()
