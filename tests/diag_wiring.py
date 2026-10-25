"""Wiring diagnostics: GPIO connectivity matrix + UART COM mapping.

Use after changing bench wiring to re-verify which GPIOs are connected:
drives each usable pin and reports which other pins follow. Also prints the
UART0/UART1 -> COM port mapping from the USB registry.

Run:  python tests/diag_wiring.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"D:\EAT_CH347F\src")

from eat.board import GPIO_MAP, detect_uart_coms
from eat.ch347_api import CH347Device

USABLE = (2, 3, 5, 6)  # UART connector GPIOs (4/7 are SWD pins)


def main() -> int:
    dev = CH347Device()
    print("=== UART COM mapping ===")
    print("  ", detect_uart_coms())

    print("=== GPIO connectivity matrix (drive one pin, read all) ===")
    for bit in USABLE:
        for level in (1, 0):
            dev.gpio_set(enable=1 << bit, dir_out=1 << bit, data_out=level << bit)
            _, v = dev.gpio_get()
            follows = [f"GPIO{i}" for i in USABLE if i != bit
                       and ((v >> i) & 1) == level]
            print(f"  GPIO{bit} out={level}: followed by {follows or 'nothing'}")
        dev.gpio_set(enable=1 << bit, dir_out=0, data_out=0)

    d, v = dev.gpio_get()
    print(f"  idle (all inputs): dir={d:02X} data={v:02X}")
    print("  pin locations:", {f"GPIO{k}": GPIO_MAP[k]["location"]
                               for k in USABLE})
    return 0


if __name__ == "__main__":
    sys.exit(main())
