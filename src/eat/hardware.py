"""Shared hardware context: one CH347 device + GPIO/power/UART/I2C/SPI objects.

Used by both tests/bench_selftest.py and the MCP server so resource lifetime
and the GPIO pairing guard behave identically everywhere.
"""
from __future__ import annotations

import threading

from .board import (BENCH_GPIO_PAIRS, bench_uart_cross_enabled,
                    detect_uart_coms, gpio_pairs)
from .ch347_api import CH347Device, CHIP_TYPE_CH347F
from .gpio_safe import SafeGpio
from .i2c_bus import AT24Cxx, I2CBus
from .power import Power
from .spi_flash import SpiBus
from .uart import UartChannel


class Hardware:
    _lock = threading.Lock()

    def __init__(self, index: int = 0, bench: bool = False):
        """bench=True enables the loopback self-test bench behaviour:
        GPIO pair guard (UART0<->UART1 cross-wired GPIOs). Normal tool usage
        keeps bench=False — GPIOs are fully independent."""
        self.dev = CH347Device(index)
        info = self.dev.device_info()
        if info["chip_type"] != CHIP_TYPE_CH347F:
            raise RuntimeError(f"expected CH347F, got chip_type="
                               f"{info['chip_type']} on index {index}")
        self.info = info
        pairs = BENCH_GPIO_PAIRS if bench else gpio_pairs()
        self.gpio = SafeGpio(self.dev, pairs=pairs)
        # deterministic power state: GPIO0 undriven floats to ~2.2V through the
        # R2/R3/R4 divider (partially-on territory) — drive it low = VOUT off
        self.gpio.set_output(0, 0)
        self.power = Power(self.gpio)
        self._uarts: dict[str, UartChannel] = {}
        self._i2c: I2CBus | None = None
        self._spi: SpiBus | None = None
        self._flash = None

    # -- UART ------------------------------------------------------------------
    def uart(self, channel: str, baud: int | None = None) -> UartChannel:
        ch = channel.upper()
        if ch not in ("UART0", "UART1"):
            raise ValueError("channel must be UART0 or UART1")
        with self._lock:
            if ch not in self._uarts:
                coms = detect_uart_coms()
                port = coms.get(ch)
                if not port:
                    raise RuntimeError(f"{ch} COM port not found (CH343SER?)")
                self._uarts[ch] = UartChannel(ch, port)
            # bench convenience (loopback rig): open the peer too, otherwise
            # bytes in flight while its COM port is closed are dropped;
            # disabled by default in normal deployment (EAT_BENCH_UART_CROSS=1)
            peer = "UART1" if ch == "UART0" else "UART0"
            if bench_uart_cross_enabled() and peer not in self._uarts:
                coms = detect_uart_coms()
                if coms.get(peer):
                    try:
                        self._uarts[peer] = UartChannel(peer, coms[peer])
                    except Exception:
                        pass
            if baud:
                self._uarts[ch].configure(baud=baud)
            return self._uarts[ch]

    def close_uart(self, channel: str) -> None:
        ch = channel.upper()
        with self._lock:
            u = self._uarts.pop(ch, None)
            if u:
                u.close()

    def uart_map(self) -> dict:
        return detect_uart_coms()

    # -- I2C ---------------------------------------------------------------------
    def i2c(self) -> I2CBus:
        with self._lock:
            if self._i2c is None:
                self._i2c = I2CBus(self.dev)
            return self._i2c

    def eeprom(self, model: str = "24C02", addr7: int = 0x50) -> AT24Cxx:
        return AT24Cxx(self.i2c(), addr7=addr7,
                       size={"24C02": 256, "24C04": 512, "24C08": 1024,
                             "24C16": 2048}.get(model.lower(), 256),
                       model=model)

    # -- SPI ---------------------------------------------------------------------
    def spi(self) -> SpiBus:
        with self._lock:
            if self._spi is None:
                self._spi = SpiBus(self.dev)
            return self._spi

    def close(self) -> None:
        for u in self._uarts.values():
            u.close()
        self._uarts.clear()
        try:
            self.gpio.all_inputs()
        except Exception:
            pass
        self.dev.close()
