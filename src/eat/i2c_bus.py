"""I2C bus helpers (CH347 as master) + AT24Cxx EEPROM driver."""
from __future__ import annotations

import time

from .ch347_api import CH347Device, I2C_SPEED_100K

# kHz -> DLL speed code (CH347I2C_Set)
SPEED_KHZ = {20: 0, 100: 1, 400: 2, 750: 3, 50: 4, 200: 5, 1000: 6}


class I2CBus:
    def __init__(self, dev: CH347Device, speed: int = I2C_SPEED_100K,
                 push_pull: bool = False, stretch: bool = False):
        self.dev = dev
        self.speed = speed
        self.push_pull = push_pull
        self.stretch = stretch
        # optional DLL features — not all firmware/DLL builds implement them
        self.driver_mode_ok = True
        self.stretch_ok = True
        self.dev.i2c_set_speed(speed)
        self._apply_optional()

    def _apply_optional(self) -> None:
        try:
            self.dev.i2c_set_stretch(self.stretch)
        except Exception:
            self.stretch_ok = False
        try:
            self.dev.i2c_set_driver_mode(self.push_pull)
        except Exception:
            self.driver_mode_ok = False

    def configure(self, speed_khz: int | None = None,
                  push_pull: bool | None = None,
                  stretch: bool | None = None) -> dict:
        if speed_khz is not None:
            if speed_khz not in SPEED_KHZ:
                raise ValueError(
                    f"I2C speed must be one of {sorted(SPEED_KHZ)} kHz")
            self.speed = SPEED_KHZ[speed_khz]
            self.dev.i2c_set_speed(self.speed)
        if push_pull is not None:
            self.push_pull = push_pull
        if stretch is not None:
            self.stretch = stretch
        self._apply_optional()
        return {"speed_khz": self.speed_khz(),
                "driver_mode_applied": self.driver_mode_ok,
                "stretch_applied": self.stretch_ok}

    def speed_khz(self) -> int:
        return next(k for k, v in SPEED_KHZ.items() if v == self.speed)

    def scan(self, lo: int = 0x08, hi: int = 0x77) -> list[int]:
        """Probe 7-bit addresses; returns those that ACK."""
        found = []
        for addr7 in range(lo, hi + 1):
            try:
                _, acks = self.dev.i2c_transfer_ack(bytes([(addr7 << 1) | 0]), 0)
                if acks >= 1:
                    found.append(addr7)
            except Exception:
                continue
        return found

    def write_reg(self, addr7: int, reg: int, data: bytes) -> None:
        self.dev.i2c_transfer(bytes([(addr7 << 1) | 0, reg]) + data, 0)

    def read_reg(self, addr7: int, reg: int, n: int) -> bytes:
        return self.dev.i2c_transfer(bytes([(addr7 << 1) | 0, reg]), n)

    def write_raw(self, addr7: int, data: bytes) -> None:
        self.dev.i2c_transfer(bytes([(addr7 << 1) | 0]) + data, 0)

    def read_raw(self, addr7: int, n: int) -> bytes:
        return self.dev.i2c_transfer(bytes([(addr7 << 1) | 1]), n)


class AT24Cxx:
    """AT24C02-class EEPROM (8-byte page write, ~5ms cycle)."""

    PAGE = 8
    WRITE_MS = 6

    def __init__(self, bus: I2CBus, addr7: int = 0x50, size: int = 256,
                 model: str = "24C02"):
        self.bus, self.addr7, self.size, self.model = bus, addr7, size, model

    def read(self, addr: int, n: int) -> bytes:
        return self.bus.read_reg(self.addr7, addr, n)

    def write(self, addr: int, data: bytes, verify: bool = True) -> None:
        for pos in range(0, len(data), self.PAGE):
            chunk = data[pos:pos + self.PAGE]
            page = addr + pos
            if page // self.PAGE != (page + len(chunk) - 1) // self.PAGE:
                raise ValueError("page-crossing chunk; split at caller")
            self.bus.write_reg(self.addr7, page, chunk)
            time.sleep(self.WRITE_MS / 1000.0)
        if verify:
            got = self.read(addr, len(data))
            if got != data:
                raise RuntimeError(f"EEPROM verify failed @{addr:#04x}: "
                                   f"wrote {data.hex()} read {got.hex()}")
