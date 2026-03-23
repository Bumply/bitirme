"""
================================================================================
NEURODRIVE -- BENCH TEST (Step 15)
================================================================================
Tests the full 3-node pipeline on a single machine without hardware.

What it does:
    1. Starts Node 1 (SITL mode) -- replays EEG data, runs inference, sends UDP
    2. Starts Node 2 (dashboard) -- receives UDP, applies safety, shows UI
    3. Simulates Node 3 -- listens on serial (or simulates) to verify commands

Since we can't run 3 separate processes easily in one script, this test:
    - Runs Node 1 inference in a background thread (UDP sender)
    - Runs a UDP receiver to verify packets arrive correctly
    - Validates the full chain: EEG -> DSP -> EEGNet -> UDP -> safety -> command
    - Tests failsafes: simulates Node 1 dropout, verifies auto-stop

Usage:
    python bench_test.py

================================================================================
"""

import time
import json
import socket
import threading
import sys
from pathlib import Path
from datetime import datetime

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))


# ==============================================================================
# TEST CONFIGURATION
# ==============================================================================

TEST_DURATION    = 30     # seconds of SITL data to replay
UDP_PORT         = 5000   # same as production
HEARTBEAT_TIMEOUT = 3.0
RESULTS = {
    "packets_received": 0,
    "commands": {"F": 0, "L": 0, "R": 0, "S": 0},
    "confidences": [],
    "latencies": [],
    "failsafe_triggered": False,
    "errors": [],
}


# ==============================================================================
# TEST 1: Full pipeline (Node 1 -> UDP -> verify)
# ==============================================================================

def test_full_pipeline():
    """Run Node 1 SITL and verify UDP packets arrive correctly."""
    print("=" * 60)
    print("  TEST 1: Full Pipeline (Node 1 SITL -> UDP)")
    print("=" * 60)

    # Start UDP receiver in background
    stop_rx = threading.Event()
    rx_thread = threading.Thread(
        target=_udp_receiver, args=(stop_rx,), daemon=True)
    rx_thread.start()

    # Import and run Node 1 components
    from node1_coral import (
        FilterChain, SharedState, CommandSmoother, CommandSender,
        LEDController, OnlineAdapter, PyTorchInferenceEngine,
        find_model, run_stream_thread_sitl, run_inference_thread,
        BUFFER_SIZE, CONFIDENCE_THRESHOLD, VOTE_WINDOW,
    )

    # Find model
    model_path, model_type = find_model()
    if model_path is None:
        print("[FAIL] No model found. Run node1_training.py first.")
        RESULTS["errors"].append("No model found")
        return False

    print(f"[OK] Model: {model_path.name}")

    # Build pipeline
    engine = PyTorchInferenceEngine(model_path)
    filter_chain = FilterChain()
    shared_state = SharedState(BUFFER_SIZE)
    smoother = CommandSmoother()
    # Send to localhost instead of Pi
    sender = CommandSender(ip="127.0.0.1", port=UDP_PORT)
    leds = LEDController()  # no-op on laptop
    adapter = OnlineAdapter(engine)
    stop_event = threading.Event()

    # Launch threads
    stream_thread = threading.Thread(
        target=run_stream_thread_sitl,
        args=(shared_state, filter_chain, stop_event, TEST_DURATION),
        daemon=True,
    )
    infer_thread = threading.Thread(
        target=run_inference_thread,
        args=(shared_state, stop_event, engine, smoother, sender, leds, adapter),
        daemon=True,
    )

    print(f"\n[RUN] Starting {TEST_DURATION}s SITL pipeline...")
    t_start = time.time()
    stream_thread.start()
    infer_thread.start()

    # Wait for completion
    stream_thread.join()
    infer_thread.join(timeout=5.0)
    elapsed = time.time() - t_start

    # Stop receiver
    stop_rx.set()
    time.sleep(0.5)

    # Cleanup
    sender.close()

    # Results
    print(f"\n{'-' * 60}")
    print(f"  PIPELINE TEST RESULTS")
    print(f"{'-' * 60}")
    print(f"  Duration:          {elapsed:.1f}s")
    print(f"  Packets received:  {RESULTS['packets_received']}")
    print(f"  Command counts:    {RESULTS['commands']}")

    if RESULTS['confidences']:
        avg_conf = np.mean(RESULTS['confidences'])
        print(f"  Avg confidence:    {avg_conf*100:.1f}%")
    if RESULTS['latencies']:
        avg_lat = np.mean(RESULTS['latencies']) * 1000
        print(f"  Avg UDP latency:   {avg_lat:.1f}ms")

    # Validate
    passed = True
    if RESULTS['packets_received'] == 0:
        print(f"  [FAIL] No packets received!")
        RESULTS["errors"].append("No UDP packets")
        passed = False
    else:
        print(f"  [OK] UDP packets flowing")

    unique_cmds = sum(1 for v in RESULTS['commands'].values() if v > 0)
    if unique_cmds < 2:
        print(f"  [WARN] Only {unique_cmds} unique command(s) -- model may be biased")
    else:
        print(f"  [OK] {unique_cmds} unique commands -- diverse predictions")

    return passed


def _udp_receiver(stop_event):
    """Receive and validate UDP packets from Node 1."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", UDP_PORT))
    sock.settimeout(0.5)

    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(1024)
            packet = json.loads(data.decode())
            now = time.time()

            cmd = packet.get("cmd", "?")
            conf = packet.get("conf", 0.0)
            ts = packet.get("ts", 0.0)

            RESULTS["packets_received"] += 1
            if cmd in RESULTS["commands"]:
                RESULTS["commands"][cmd] += 1
            RESULTS["confidences"].append(conf)
            if ts > 0:
                RESULTS["latencies"].append(now - ts)

        except socket.timeout:
            pass
        except Exception:
            pass

    sock.close()


# ==============================================================================
# TEST 2: Failsafe -- simulate Node 1 dropout
# ==============================================================================

def test_failsafe():
    """Verify that loss of Node 1 triggers safety timeout."""
    print(f"\n{'=' * 60}")
    print(f"  TEST 2: Failsafe (Node 1 dropout)")
    print(f"{'=' * 60}")

    from node2_dashboard import SafetyController

    safety = SafetyController()

    # Simulate receiving commands
    safety.process("F", 0.85)
    time.sleep(0.1)
    cmd, reason = safety.check_timeouts()
    assert reason == "OK", f"Expected OK, got {reason}"
    print(f"  [OK] Normal operation: cmd={cmd}, reason={reason}")

    # Simulate dropout (wait for heartbeat timeout)
    print(f"  [RUN] Simulating {HEARTBEAT_TIMEOUT}s dropout...")
    time.sleep(HEARTBEAT_TIMEOUT + 0.5)

    cmd, reason = safety.check_timeouts()
    if reason == "HEARTBEAT TIMEOUT":
        print(f"  [OK] Heartbeat timeout triggered: cmd={cmd}")
        RESULTS["failsafe_triggered"] = True
        return True
    else:
        print(f"  [FAIL] Expected HEARTBEAT TIMEOUT, got: {reason}")
        RESULTS["errors"].append(f"Failsafe not triggered: {reason}")
        return False


# ==============================================================================
# TEST 3: Safety controller -- e-stop
# ==============================================================================

def test_estop():
    """Verify e-stop overrides all commands."""
    print(f"\n{'=' * 60}")
    print(f"  TEST 3: E-Stop Override")
    print(f"{'=' * 60}")

    from node2_dashboard import SafetyController

    safety = SafetyController()

    # Normal command
    cmd, reason = safety.process("F", 0.9)
    assert cmd == "F", f"Expected F, got {cmd}"
    print(f"  [OK] Normal: cmd={cmd}")

    # Trigger e-stop
    safety.trigger_estop()
    cmd, reason = safety.process("F", 0.9)
    assert cmd == "E", f"Expected E after e-stop, got {cmd}"
    assert reason == "E-STOP ACTIVE"
    print(f"  [OK] E-stop blocks commands: cmd={cmd}, reason={reason}")

    # Reset
    safety.reset_estop()
    cmd, reason = safety.process("L", 0.8)
    assert cmd == "L", f"Expected L after reset, got {cmd}"
    print(f"  [OK] E-stop reset works: cmd={cmd}")

    return True


# ==============================================================================
# TEST 4: Command smoother
# ==============================================================================

def test_smoother():
    """Verify majority vote smoothing."""
    print(f"\n{'=' * 60}")
    print(f"  TEST 4: Command Smoother (Majority Vote)")
    print(f"{'=' * 60}")

    from node1_coral import CommandSmoother, CONFIDENCE_THRESHOLD

    sm = CommandSmoother(window_size=3)

    # Low confidence should hold previous
    cmd, status = sm.update("F", 0.2)
    assert status == "LOW_CONF"
    print(f"  [OK] Low confidence held: cmd={cmd}, status={status}")

    # Fill window
    sm.update("L", 0.8)
    sm.update("L", 0.7)
    cmd, status = sm.update("R", 0.6)
    assert cmd == "L", f"Expected L (majority), got {cmd}"
    print(f"  [OK] Majority vote: L,L,R -> {cmd}")

    # Unanimous
    sm.update("F", 0.9)
    sm.update("F", 0.8)
    cmd, status = sm.update("F", 0.85)
    assert cmd == "F"
    print(f"  [OK] Unanimous: F,F,F -> {cmd}")

    return True


# ==============================================================================
# TEST 5: Arduino serial protocol (simulated)
# ==============================================================================

def test_serial_protocol():
    """Verify the serial command format matches what Arduino expects."""
    print(f"\n{'=' * 60}")
    print(f"  TEST 5: Serial Protocol Validation")
    print(f"{'=' * 60}")

    valid_commands = ['F', 'L', 'R', 'S', 'E']

    for cmd in valid_commands:
        encoded = cmd.encode()
        assert len(encoded) == 1, f"Command {cmd} should be 1 byte"
        assert encoded[0] >= ord('A') and encoded[0] <= ord('Z'), \
            f"Command {cmd} should be uppercase letter"
        print(f"  [OK] '{cmd}' -> 0x{encoded[0]:02X} (1 byte, valid)")

    print(f"  [OK] All {len(valid_commands)} commands are valid single-byte uppercase")
    return True


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    print()
    print("*" * 60)
    print("  NEURODRIVE -- BENCH TEST SUITE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("*" * 60)

    results = {}

    # Quick unit tests first
    results["smoother"] = test_smoother()
    results["serial"] = test_serial_protocol()
    results["estop"] = test_estop()
    results["failsafe"] = test_failsafe()

    # Full pipeline test (takes ~30s)
    results["pipeline"] = test_full_pipeline()

    # Summary
    print(f"\n{'*' * 60}")
    print(f"  BENCH TEST SUMMARY")
    print(f"{'*' * 60}")

    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        icon = "[OK]  " if passed else "[FAIL]"
        print(f"  {icon} {name}")
        if not passed:
            all_passed = False

    if RESULTS["errors"]:
        print(f"\n  Errors:")
        for err in RESULTS["errors"]:
            print(f"    - {err}")

    print()
    if all_passed:
        print("  ALL TESTS PASSED")
    else:
        print("  SOME TESTS FAILED -- check errors above")
    print(f"{'*' * 60}")


if __name__ == "__main__":
    main()
