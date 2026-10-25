"""Target board profiles: named reset/boot/flashing recipes per MCU family.

A profile maps the generic actions (reset, enter-bootloader, flash-via-uart)
onto this board's GPIOs and UART channels. Stored as JSON in config/targets/.
"""
from __future__ import annotations

import json
from pathlib import Path

TARGETS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "targets"

_REQUIRED = {"name", "uart", "baud", "reset_gpio", "boot_gpio"}


def load_profiles() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not TARGETS_DIR.exists():
        return out
    for f in sorted(TARGETS_DIR.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            missing = _REQUIRED - set(p)
            if missing:
                continue
            out[p["name"]] = p
        except Exception:
            continue
    return out


def get_profile(name: str) -> dict:
    profiles = load_profiles()
    if name not in profiles:
        raise KeyError(
            f"unknown target profile '{name}'; available: {sorted(profiles)}")
    return profiles[name]
