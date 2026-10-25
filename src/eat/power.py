"""VOUT (target power) control via GPIO0 = VOUT_EN, high = on."""
from __future__ import annotations

import time

from .ch347_api import CH347Device
from .gpio_safe import SafeGpio
from .board import VOUT_EN_GPIO


class Power:
    def __init__(self, gpio: SafeGpio):
        self.gpio = gpio

    def on(self) -> dict:
        self.gpio.set_output(VOUT_EN_GPIO, 1)
        return {"vout": "on"}

    def off(self) -> dict:
        self.gpio.set_output(VOUT_EN_GPIO, 0)
        return {"vout": "off"}

    def cycle(self, off_ms: int = 1000) -> dict:
        """Power-cycle: off, wait, on. '下电复位' for VOUT-powered targets."""
        self.off()
        time.sleep(off_ms / 1000.0)
        self.on()
        return {"vout": "on", "off_ms": off_ms}

    def status(self) -> dict:
        bit = self.gpio.read(VOUT_EN_GPIO)
        return {"vout": "on" if bit else "off",
                "vout_en_gpio": VOUT_EN_GPIO,
                "note": "physical state also forced by SW1 when set to GND"}
