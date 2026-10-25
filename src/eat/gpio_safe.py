"""GPIO manager with an optional pair guard.

The pair guard protects wiring where two GPIOs are physically shorted
together — by default the loopback self-test bench (UART0/UART1 connectors
cross-mated: GPIO2<->GPIO5, GPIO3<->GPIO6), where driving both sides of a
pair as opposing outputs would be a hard short. It is enabled ONLY when the
manager is created with pairs (Hardware(bench=True) for the self-test, or
EAT_GPIO_PAIRS for custom wiring). In normal tool usage no pairs are set and
every GPIO behaves independently.
"""
from __future__ import annotations

import time

from .board import GPIO_MAP, VOUT_EN_GPIO
from .ch347_api import CH347Device


class GpioSafetyError(RuntimeError):
    """Refused an operation that would create a drive conflict."""


class SafeGpio:
    def __init__(self, dev: CH347Device, pairs: list[tuple[int, int]] | None = None,
                 reserved: dict[int, str] | None = None):
        self.dev = dev
        self.pairs: dict[int, int] = {}
        for a, b in pairs or []:
            self.pairs[a] = b
            self.pairs[b] = a
        self.reserved = dict(reserved or {VOUT_EN_GPIO: "VOUT power control"})

    # -- low level -------------------------------------------------------------
    def _get(self) -> tuple[int, int]:
        return self.dev.gpio_get()

    def _apply(self, bit: int, out: bool, level: int) -> None:
        self.dev.gpio_set(enable=1 << bit, dir_out=(1 if out else 0) << bit,
                          data_out=(level & 1) << bit)

    # -- public API --------------------------------------------------------------
    def describe(self) -> dict:
        d, v = self._get()
        pins = {}
        for bit in range(8):
            info = GPIO_MAP[bit]
            pins[f"GPIO{bit}"] = {
                "dir": "out" if (d >> bit) & 1 else "in",
                "level": (v >> bit) & 1,
                "pin": info["pin"], "location": info["location"],
                **({"note": info["note"]} if info.get("note") else {}),
                **({"pair": f"GPIO{self.pairs[bit]}"} if bit in self.pairs else {}),
                **({"reserved": self.reserved[bit]} if bit in self.reserved else {}),
            }
        return {"pins": pins}

    def read(self, bit: int) -> int:
        if bit not in GPIO_MAP:
            raise GpioSafetyError(f"GPIO{bit} does not exist (0-7 only)")
        if GPIO_MAP[bit]["net"] == "NC":
            raise GpioSafetyError(f"GPIO{bit} is not connected on this board")
        _, v = self._get()
        return (v >> bit) & 1

    def set_input(self, bit: int) -> None:
        self._check_usable(bit)
        self._apply(bit, out=False, level=0)

    def set_output(self, bit: int, level: int) -> dict:
        """Configure pin as output at `level`, partner forced to input first."""
        self._check_usable(bit)
        partner = self.pairs.get(bit)
        if partner is not None:
            d, _ = self._get()
            if (d >> partner) & 1:  # partner currently output -> release it
                self._apply(partner, out=False, level=0)
                d2, _ = self._get()
                if (d2 >> partner) & 1:
                    raise GpioSafetyError(
                        f"partner GPIO{partner} still output after release; "
                        "refusing to drive GPIO{bit}")
                time.sleep(0.002)
        self._apply(bit, out=True, level=level)
        d, v = self._get()
        if not (d >> bit) & 1 or ((v >> bit) & 1) != (level & 1):
            raise GpioSafetyError(f"GPIO{bit} output verify failed "
                                  f"(dir={d:02X} data={v:02X})")
        return {"gpio": bit, "dir": "out", "level": level & 1,
                **({"partner_forced_input": partner} if partner is not None else {})}

    def write(self, bit: int, level: int) -> dict:
        """Change output level of a pin already configured as output."""
        self._check_usable(bit)
        d, _ = self._get()
        if not (d >> bit) & 1:
            raise GpioSafetyError(f"GPIO{bit} is input; call set_output first")
        partner = self.pairs.get(bit)
        if partner is not None:
            d, v = self._get()
            if (d >> partner) & 1 and ((v >> partner) & 1) != (level & 1):
                raise GpioSafetyError(
                    f"short avoided: GPIO{partner} is output at opposite level")
        self._apply(bit, out=True, level=level)
        return {"gpio": bit, "level": level & 1}

    def all_inputs(self) -> None:
        """Release every usable non-reserved GPIO to input (safe idle state).

        Reserved pins (e.g. GPIO0 = VOUT_EN) stay driven — releasing VOUT_EN
        lets it float to ~2.2V through the gate divider, which is neither a
        clean on nor off.
        """
        d, _ = self._get()
        for bit in range(8):
            if bit in self.reserved:
                continue
            if GPIO_MAP[bit]["net"] != "NC" and (d >> bit) & 1:
                self._apply(bit, out=False, level=0)

    def pulse(self, bit: int, level: int, ms: int, idle_level: int = None) -> dict:
        """Drive `level` for `ms` then return to idle_level (default inverted)."""
        idle = (1 - (level & 1)) if idle_level is None else idle_level & 1
        self.set_output(bit, idle)
        self.write(bit, level & 1)
        time.sleep(ms / 1000.0)
        self.write(bit, idle)
        return {"gpio": bit, "pulsed": level & 1, "ms": ms, "idle": idle}

    def _check_usable(self, bit: int) -> None:
        if bit not in GPIO_MAP:
            raise GpioSafetyError(f"GPIO{bit} does not exist (0-7 only)")
        if GPIO_MAP[bit]["net"] == "NC":
            raise GpioSafetyError(f"GPIO{bit} is not connected on this board")
