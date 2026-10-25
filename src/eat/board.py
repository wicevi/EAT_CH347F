"""Board model & bench configuration for Embedded_Agent_Tool V1.0 (CH347F).

Hardware facts mirror docs/HARDWARE.md — the authoritative schematic reading.
Bench wiring describes the current test setup on this machine.
"""
from __future__ import annotations

import os
import winreg

USB_VID_PID = r"VID_1A86&PID_55DE"

# DLL GPIO bit -> physical pin / connector location (CH347DLL.H table 4-7)
GPIO_MAP = {
    0: {"pin": 17, "net": "VOUT_EN", "location": "power switch Q3 gate",
        "note": "RESERVED for VOUT power control (high=on)"},
    1: {"pin": 18, "net": "NC", "location": "not connected",
        "note": "unusable"},
    2: {"pin": 10, "net": "GPIO2", "location": "UART0 connector pin1"},
    3: {"pin": 9,  "net": "GPIO3", "location": "UART0 connector pin2",
        "note": "shared with JTAG TRST"},
    4: {"pin": 23, "net": "SWCLK", "location": "LINK1 pin2",
        "note": "shared with SWD clock"},
    5: {"pin": 24, "net": "GPIO5", "location": "UART1 connector pin1",
        "note": "shared with JTAG TDO"},
    6: {"pin": 25, "net": "GPIO6", "location": "UART1 connector pin2",
        "note": "shared with JTAG TDI"},
    7: {"pin": 26, "net": "SWDIO", "location": "LINK1 pin1",
        "note": "shared with SWD data"},
}

VOUT_EN_GPIO = 0  # high = VOUT on

# --- bench (test rig) wiring ---------------------------------------------------
# UART0/UART1 6P connectors are mated through an adapter: TX/RX crossed
# (pin3<->pin4), all other pins straight in order (1<->1, 2<->2, 5<->5, 6<->6).
# With UART0 pin1=GPIO2/pin2=GPIO3 and UART1 pin1=GPIO5/pin2=GPIO6 (schematic
# + user-confirmed), the straight mating yields the pairs below — matching
# the measured drive/read matrix exactly.
# DANGER: a pair driven as opposing outputs is a hard short -> chip overheats.
BENCH_GPIO_PAIRS = [(2, 5), (3, 6)]


def bench_uart_cross_enabled() -> bool:
    """Bench convenience: auto-open the peer UART when opening one channel,
    so bytes in flight are not dropped on a UART0<->UART1 loopback rig.
    Off by default (product behaviour); enable with EAT_BENCH_UART_CROSS=1."""
    return os.environ.get("EAT_BENCH_UART_CROSS", "").strip().lower() in (
        "1", "true", "yes", "on")


def gpio_pairs() -> list[tuple[int, int]]:
    """GPIO pairing for the guard in gpio_safe.

    Default: NO pairs — GPIOs are independent (normal tool usage). The guard
    exists only for the loopback self-test bench, where SafeGpio is created
    with pairs explicitly (Hardware(bench=True)). To protect custom wiring
    where two GPIOs are physically shorted together, set:
        EAT_GPIO_PAIRS=2:5,3:6
    """
    v = os.environ.get("EAT_GPIO_PAIRS")
    if v is None:
        return []
    v = v.strip().lower()
    if v in ("", "none", "off"):
        return []
    pairs = []
    for item in v.split(","):
        a, b = item.strip().split(":")
        pairs.append((int(a), int(b)))
    return pairs
# --- dev-bench (loopback rig) reference values, used by tests only ----------
# These describe the self-test rig on the development machine; they are NOT
# product behaviour. See tests/bench_selftest.py for the wiring they assume.
BENCH_UART_CROSS = True           # loopback: UART0 TX/RX wired to UART1
BENCH_I2C_EEPROM = "AT24C02"      # 7-bit address 0x50 on IIC1
BENCH_SPI_FLASH = "W25Q80"        # JEDEC EF 40 14 on SPI1
# SPI1 wiring note on that rig: the flash module's MOSI/MISO are crossed
# relative to the SPI1 connector. Measured consequence: full-duplex
# CH347SPI_WriteRead captures MISO fine, but the endpoint CH347SPI_Read
# ("send cmd, then read") returns 0xFF — the driver layer always reads via
# full-duplex frames (see spi_flash.py), so this does not affect users.
BENCH_SPI_MOSI_MISO_CROSSED = True

AT24C02_SIZE = 256
W25Q_PAGE = 256
W25Q_SECTOR = 4096


def detect_uart_coms() -> dict[str, str | None]:
    """Map {'UART0': 'COMx', 'UART1': 'COMy'} from the USB enum registry.

    CH347F composite interfaces: MI_00 = UART0 (SERIAL-A), MI_02 = UART1
    (SERIAL-B). Returns None for missing channels.
    """
    out: dict[str, str | None] = {"UART0": None, "UART1": None}
    base = r"SYSTEM\CurrentControlSet\Enum\USB" + "\\" + USB_VID_PID
    for mi, name in (("MI_00", "UART0"), ("MI_02", "UART1")):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{base}&{mi}")
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    inst = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(key, rf"{inst}\Device Parameters") as dp:
                        port, _ = winreg.QueryValueEx(dp, "PortName")
                        out[name] = port
                        break
                except OSError:
                    continue
        finally:
            winreg.CloseKey(key)
    return out
