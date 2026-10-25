"""Toggle VOUT once per second so the user can watch the OUT1 (green) LED.

If OUT1 follows the toggling -> software VOUT control works end-to-end and the
bench modules are simply self-powered. If OUT1 stays lit -> VOUT is stuck on
(hardware). Run:  python tests/vout_blink.py
"""
import sys
import time

sys.path.insert(0, r"D:\EAT_CH347F\src")

from eat.ch347_api import CH347Device

dev = CH347Device()
print("toggling VOUT_EN 1s on / 1s off x5 — watch the OUT1 LED on the board")
for i in range(5):
    dev.gpio_set(enable=1, dir_out=1, data_out=1)
    print(f"  cycle {i+1}: VOUT_EN=1 (expect OUT1 ON)")
    time.sleep(1.0)
    dev.gpio_set(enable=1, dir_out=1, data_out=0)
    print(f"  cycle {i+1}: VOUT_EN=0 (expect OUT1 OFF)")
    time.sleep(1.0)
dev.gpio_set(enable=1, dir_out=1, data_out=0)  # leave off
print("done — VOUT_EN left at 0 (off)")
