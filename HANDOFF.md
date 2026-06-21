# NeuroDrive — Session Handoff (2026-06-21)

Paste this path into a new chat: **"read ~/NeuroDrive/HANDOFF.md and continue."**
Host = CachyOS (Arch), cwd usually `/home/ali`. Repo at `~/NeuroDrive`.

## What NeuroDrive is
3-node motor-imagery BCI wheelchair:
- **Node 1 = Coral Dev Board Mini + Portiloop hat** (`node1_coral.py`): ADS1299-**4** (4-ch) → DSP → EEGNet TFLite → UDP to Pi.
- **Node 2 = Raspberry Pi 5** (`node2_app.py`, PyQt5 + phone web): receives UDP :5000, safety, relays serial to Arduino.
- **Node 3 = Arduino Mega** (`node3_motor_control/`): motors (hub DAC + steer/brake BTS7960).
- Hardware is **4-channel** (ADS1299-4, ID=0x3C), C3/Cz/C4/CPz. Docs keep the "8 design · 4 wired" framing.

## Repo / git state
- GitHub: `github.com/Bumply/bitirme` (gh authenticated as Bumply). Pages from main `/docs`.
- **Open PR #1**: branch `phase3-safety-fixes` → `main`. Three commits:
  1. `d879baa` soft-start ramp + DRDY timeout + adaptation honesty
  2. `07f7db6` comms-loss brake + (first, WRONG) LED pin fix
  3. `36d9bde` final LED rewrite + this HANDOFF.md
- ✅ **PR is in sync with the board** (as of 2026-06-22): the final LED rewrite deployed on the Coral is committed (`36d9bde`) and pushed. Nothing local is behind origin.
- Untracked: `hardware/*.scad` (wet-cup electrode holders), `led_probe.py` (throwaway), this `HANDOFF.md`.

## This session's work
1. **Safety fixes (committed to PR #1, verified compiling `arduino:avr:mega`):**
   - Arduino: restored throttle **soft-start ramp** (`rampTick`); E-STOP snaps via `hubKill()`. **Comms-loss now brakes + latches** (gated on recent drive), needs `S` to re-arm.
   - `node1_coral.py`: `drdy.poll(timeout=None)` → `DRDY_TIMEOUT_S=1.0` (RuntimeError on stall). Adaptation log now states it's PyTorch-only / no-op on Coral TFLite.
2. **Deferred (user choice):** battery low-voltage cutoff — A0 divider **not wired yet**; spec ready (24V example: R1=100k/R2=18k, warn/cutoff per chemistry). Independent hardware E-stop = wiring task.
3. **LED saga — RESOLVED.** Status LEDs are on the **Portiloop hat**, not the Coral. Final working mapping (gpiochip0, traced from `~/Downloads/portiloop-hardware/portiloop.net` + `portiloop-software/.../hardware/leds.py`):
   - **D1 green = line 39** (the "LEDCTL" line) — used as solid "running" light.
   - **D2 red = line 22** — heartbeat blink.
   - **D2 green (9) and blue (10) are DEAD/unpopulated** on the user's boards (confirmed on two).
   - `LEDController` rewritten to drive only lines 39 (green solid) + 22 (red toggle). Green works (solid = Node 1 running); red blink not visibly confirmed but harmless. **User said drop LEDs** — do not rabbit-hole here again.

## Coral is TURNKEY (verified)
Power-on flow already works:
1. **Power on Coral** → ~90 s boot → `hostapd` brings up AP **`NeuroDrive`** (ap0 = 192.168.4.1) + `dnsmasq` + `neurodrive-node1` autostarts → streams → UDP to **192.168.4.2:5000**. D1 solid green = ready.
2. **Power on Pi** → joins `NeuroDrive` AP → static lease pins it to **192.168.4.2** (`dhcp-host=2c:cf:67:91:f7:1d`) → Node 2 receives → cruise.
- All three services **enabled + active**: `neurodrive-node1`, `hostapd`, `dnsmasq`.
- Coral also on home WiFi: wlan0 = 192.168.1.25.
- **Live output is stuck at S:100%** because no electrodes on scalp + uncalibrated. Pipeline/front-end are healthy (selftest PASSES). Real EEG-driving needs headset on + `node1_calibrate.py`. Manual/phone path via Node 2 works regardless.
- **Last unverified link:** the **Pi (Node 2) autostart** on :5000 — not checked this session. Verify via `pi_ssh.py` / SSH.

## Coral access + GOTCHAS (important)
- SSH: `ssh -i ~/.config/mdt/keys/mdt.key mendel@192.168.100.2` (USB-OTG). Hostname `tuned-wasp`.
- Conda python on board: `/opt/miniforge3/envs/portiloop/bin/python` (env `portiloop`, has periphery/tflite/pycoral).
- Service: `sudo systemctl {restart,stop,status} neurodrive-node1`. ExecStart runs `~/NeuroDrive/node1_coral.py`.
- **Logs go to the JOURNAL** (`sudo journalctl -u neurodrive-node1`), NOT `~/nd-node1.log` (that file is a STALE manual-run log — ignore it).
- **`scp` FAILS** (host OpenSSH 9.x SFTP vs board). Use `ssh -i ... mendel@... 'cat > ~/NeuroDrive/FILE' < FILE`.
- **Software reset does NOT work** — user physically unplugs/replugs to reset (then ~90 s boot). `systemctl restart` is fine; full reboots are not.
- selftest: `/opt/miniforge3/envs/portiloop/bin/python -u ~/NeuroDrive/selftest_ads1299.py` (stop the service first to free SPI/DRDY).
- Always filter SSH noise: `... 2>&1 | grep -ivE "post-quantum|store now|may need|openssh.com|vulnerable"`.

## Open items / next steps
- [x] ~~Commit final `node1_coral.py` (LED rewrite) to `phase3-safety-fixes`; sync PR #1.~~ DONE (`36d9bde`, pushed 2026-06-22).
- [ ] Verify Node 2 (Pi) autostarts + listens on :5000 (last turnkey link).
- [ ] Personal calibration (`node1_calibrate.py`) with electrodes on scalp for real classification (currently ~42% / stuck-S without it).
- [ ] (Deferred) battery cutoff firmware once A0 divider wired; comms-loss brake already in PR.
- [ ] (Optional) commit `hardware/*.scad` wet-cup holders.

## Secrets / constraints
- Never echo/store passwords: Pi sudo, AP `neurodrive2026`. `pi_ssh.py` keeps password env-only (`PI_PASS`).
