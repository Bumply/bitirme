#!/usr/bin/env python3
"""
ADS1299 hardware self-test — no electrodes required.

Uses the production ADS1299Reader in test_signal mode: the chip's internal
square-wave generator is routed to every channel. If the acquisition chain is
healthy, each channel swings between two distinct levels (the square wave)
instead of sitting flat — proving SPI + DRDY + the ADC are all live.

Run on the Coral:
    /opt/miniforge3/envs/portiloop/bin/python -u selftest_ads1299.py
"""
import numpy as np
from node1_coral import ADS1299Reader, N_CH, FS

SECONDS = 2.4


def main():
    reader = ADS1299Reader(test_signal=True)
    n = int(FS * SECONDS)
    data = np.empty((n, N_CH))
    for i in range(n):
        data[i] = reader.read_sample()          # microvolts
        if i % 100 == 0:
            print(f"  ... {i}/{n} samples", flush=True)
    reader.close()

    print("\nch     min(uV)      max(uV)     std(uV)   square-edges")
    for ch in range(N_CH):
        x = data[:, ch]
        mid = (x.max() + x.min()) / 2.0
        edges = int(np.sum(np.abs(np.diff((x >= mid).astype(int)))))
        print(f"{ch:2d}  {x.min():10.1f}  {x.max():10.1f}  {x.std():8.1f}   {edges}")

    print("\nchannel 0 trace (every 10th sample, uV):")
    print("  " + " ".join(f"{v:6.0f}" for v in data[::10, 0]))

    swinging = all(data[:, ch].std() > 100 for ch in range(N_CH))
    print(f"\n[RESULT] {'PASS - all 4 channels reproduce the test signal' if swinging else 'FLAT - check chip/wiring'}")


if __name__ == "__main__":
    main()
