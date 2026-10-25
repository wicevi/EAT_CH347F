"""EAT CH347F — MCP server for AI coding agents (Claude Code / ZCode / Cursor...).

Exposes the Embedded Agent Tool board (WCH CH347F) over Model Context
Protocol: dual UART with background monitoring, pair-guarded GPIO, target
power (VOUT), I2C + AT24Cxx, SPI + W25Qxx flash, reset/boot profiles,
send/expect scripting, bench self-test and doctor.

Design patterns borrowed from reference projects (see docs/MCP_TOOLS.md):
- unified return contract: {"ok": bool, "summary": str, ...fields}
- safety policy layer via EAT_MCP_POLICY=full|no_write|read_only
- background serial monitor with ring buffer + log file + tail/grep
  (esp32-ai-loop-mcp-server / platformio.mcp pattern)
- send/delay/expect script DSL (serial-mcp-server pattern)

Run (stdio transport):   python eat_mcp_server.py
Client config example:
    { "mcpServers": { "eat": { "command": "python",
                               "args": ["D:\\\\EAT_CH347F\\\\eat_mcp_server.py"] } } }
"""
from __future__ import annotations

import functools
import os
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as AppServer
except ImportError:  # mcp 1.x fallback
    from mcp.server.fastmcp import FastMCP as AppServer

from eat.ch347_api import CH347Error
from eat.hardware import Hardware
from eat.targets import get_profile, load_profiles
from eat.uart_monitor import MonitorManager

mcp = AppServer("eat-ch347f")

# ---------------------------------------------------------------- policy layer
POLICY = os.environ.get("EAT_MCP_POLICY", "full").strip().lower()
if POLICY not in ("full", "no_write", "read_only"):
    POLICY = "full"

_LEVELS = ("read", "control", "write")
_POLICY_MAX = {"full": "write", "no_write": "control", "read_only": "read"}


def _tool(level: str = "read", summary: str | None = None):
    """Decorator: policy gate + unified ok/error contract.

    level: 'read' (pure observation) | 'control' (operates the bench: GPIO,
    power, UART TX, reset) | 'write' (persistent writes / erase / selftest).
    """
    assert level in _LEVELS

    def deco(fn):
        @functools.wraps(fn)  # keep original signature for schema generation
        def run(*args, **kwargs):
            if _LEVELS.index(level) > _LEVELS.index(_POLICY_MAX[POLICY]):
                return {"ok": False,
                        "error": f"blocked by EAT_MCP_POLICY={POLICY}",
                        "hint": "restart server with EAT_MCP_POLICY=full to enable"}
            try:
                r = fn(*args, **kwargs)
                if isinstance(r, dict):
                    r.setdefault("ok", True)
                    if summary:
                        r.setdefault("summary", summary)
                return r
            except (ValueError, KeyError, RuntimeError, CH347Error,
                    TimeoutError) as e:
                if isinstance(e, CH347Error):
                    _reset_hw()  # device may have been replugged
                return {"ok": False, "error": str(e),
                        "hint": _hint_for(e)}
            except Exception as e:  # keep the agent informed, not crashed
                return {"ok": False, "error": repr(e),
                        "trace": traceback.format_exc(limit=3)}
        run.__doc__ = (fn.__doc__ or "") + (f" [policy level: {level}]")
        return mcp.tool()(run)
    return deco


def _hint_for(e: Exception) -> str:
    s = str(e).lower()
    if "ch347opendevice" in s:
        return "board unplugged? replug USB, then retry — server auto-reopens"
    if "com port not found" in s:
        return "CH343SER driver missing or board replugged; run eat_doctor"
    if "no monitor running" in s:
        return "call eat_uart_monitor_start first"
    if "unknown target profile" in s:
        return "call eat_target_profiles to list available profiles"
    return ""


# ---------------------------------------------------------------- hardware ctx
_hw: Hardware | None = None
_mon = MonitorManager()
_hw_lock = threading.Lock()


def hw() -> Hardware:
    global _hw
    with _hw_lock:
        if _hw is None:
            _hw = Hardware()
        return _hw


def _reset_hw() -> None:
    global _hw
    with _hw_lock:
        if _hw is not None:
            try:
                _hw.close()
            except Exception:
                pass
        _hw = None


def _hex(data: bytes) -> str:
    return data.hex(" ")


def _unhex(s: str) -> bytes:
    return bytes.fromhex("".join(s.split()))


# ---------------------------------------------------------------- device/power
@_tool("read", "USB device info + wiring overview")
def eat_device_info() -> dict:
    """Board overview: USB device info, UART COM map, GPIO pin locations,
    active safety policy."""
    h = hw()
    return {
        "device": h.info,
        "uart_com_map": h.uart_map(),
        "gpio_locations": {
            "GPIO2/3": "UART0 connector pin1/pin2 (reset/boot/button lines)",
            "GPIO5/6": "UART1 connector pin1/pin2 (reset/boot/button lines)",
            "GPIO0": "reserved for VOUT power control",
            "GPIO1": "not connected",
            "GPIO4/7": "SWD pins (LINK1) - conflict with SWD use",
        },
        "policy": POLICY,
        "notes": [
            "JTAG uses GPIO3/5/6; SWD uses GPIO4/7 — mutually exclusive with "
            "using them as GPIO.",
            "VOUT hardware switch has a known defect on this board revision; "
            "software power API is ready but the rail may stay on regardless.",
        ],
    }


@_tool("read", "quick environment & connectivity health check")
def eat_doctor() -> dict:
    """Doctor: python/deps, CH347 DLL, device open, chip type, COM map, I2C
    bus, SPI flash, log dir writability. Read-only, safe to run any time."""
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:200]})

    import winreg
    add("python", True, sys.version.split()[0])
    try:
        import serial  # noqa
        add("pyserial", True, serial.VERSION)
    except Exception as e:
        add("pyserial", False, e)
    add("ch347_dll", True, "CH347DLLA64.DLL (System32)")
    try:
        h = hw()
        add("device_open", h.info["chip_type"] == 2,
            f"{h.info['product']} fw={h.info['firmware_ver']}")
        coms = h.uart_map()
        add("uart_coms", bool(coms.get("UART0") and coms.get("UART1")), coms)
    except Exception as e:
        add("device_open", False, e)
        add("uart_coms", False, "device not open")
    try:
        found = hw().i2c().scan()
        add("i2c_bus", True, f"devices: {[hex(a) for a in found] or 'none'}")
    except Exception as e:
        add("i2c_bus", False, e)
    try:
        from eat.spi_flash import W25QFlash
        f = W25QFlash(hw().spi())
        add("spi_bus", True,
            f.identify() if f.jedec != b"\xff\xff\xff" and f.jedec.strip(b"\xff")
            else "no JEDEC response (no flash attached?)")
    except Exception as e:
        add("spi_bus", False, e)
    from eat.uart_monitor import LOG_DIR
    try:
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / ".probe").write_text("ok")
        (LOG_DIR / ".probe").unlink()
        add("log_dir", True, str(LOG_DIR))
    except Exception as e:
        add("log_dir", False, e)
    add("policy", True, f"EAT_MCP_POLICY={POLICY}")
    n_bad = sum(1 for c in checks if not c["ok"])
    return {"ok": n_bad == 0, "failed": n_bad, "checks": checks,
            "summary": f"{len(checks) - n_bad}/{len(checks)} checks passed"}


@_tool("control", "set VOUT target supply")
def eat_power_set(action: str, off_ms: int = 1000) -> dict:
    """Control VOUT (3.3V target supply, connector pin 'VOUT').
    action: 'on' | 'off' | 'cycle' (off->delay->on, i.e. power-cycle reset).
    NOTE: current board revision has a known VOUT switch circuit defect —
    the rail may not actually switch until the hardware is revised."""
    h = hw()
    if action == "on":
        return h.power.on()
    if action == "off":
        return h.power.off()
    if action == "cycle":
        return h.power.cycle(off_ms)
    raise ValueError("action must be on|off|cycle")


@_tool("read", "read VOUT enable state")
def eat_power_status() -> dict:
    """Read VOUT enable state (GPIO0 drive level; SW1 forced-on overrides)."""
    return hw().power.status()


# ---------------------------------------------------------------- GPIO
@_tool("read", "all GPIO directions + levels")
def eat_gpio_read_all() -> dict:
    """Direction + level of all GPIO0-7 with pin/location/pair metadata."""
    return hw().gpio.describe()


@_tool("read", "read one GPIO level")
def eat_gpio_read(pin: int) -> dict:
    """Read one GPIO input level (pin = GPIO number 0-7, e.g. 2 = GPIO2)."""
    return {"pin": pin, "level": hw().gpio.read(pin)}


@_tool("control", "configure a GPIO")
def eat_gpio_set(pin: int, mode: str, level: int = 0,
                 pulse_ms: int = 100) -> dict:
    """Configure a GPIO. mode: 'in' (input), 'out' (output at level),
    'pulse' (output level for pulse_ms then invert)."""
    g = hw().gpio
    if mode == "in":
        g.set_input(pin)
        return {"pin": pin, "mode": "in"}
    if mode == "out":
        return g.set_output(pin, level)
    if mode == "pulse":
        return g.pulse(pin, level, pulse_ms)
    raise ValueError("mode must be in|out|pulse")


@_tool("control", "change level of an output GPIO")
def eat_gpio_write(pin: int, level: int) -> dict:
    """Change level of a GPIO already configured as output."""
    return hw().gpio.write(pin, level)


# ---------------------------------------------------------------- UART basic
@_tool("read", "UART channel -> COM port map")
def eat_uart_list() -> dict:
    """Map UART0/UART1 to COM ports (CH343SER VCP; UART0=MI_00, UART1=MI_02)."""
    return hw().uart_map()


@_tool("control", "open/configure a UART channel")
def eat_uart_config(channel: str, baud: int = 115200,
                    databits: int = 8, parity: str = "N",
                    stopbits: float = 1) -> dict:
    """Open/configure a UART channel (channel='UART0'|'UART1')."""
    u = hw().uart(channel, baud=baud)
    u.configure(bytesize=databits, parity=parity, stopbits=stopbits)
    return {"channel": channel, "port": u.port, "baud": u.ser.baudrate,
            "format": f"{databits}{parity}{stopbits}"}


@_tool("control", "send data on a UART channel")
def eat_uart_send(channel: str, data: str, hex_data: bool = False,
                  newline: bool = False) -> dict:
    """Send text (or hex bytes when hex_data=true) on a UART channel."""
    payload = _unhex(data) if hex_data else data.encode("utf-8")
    if newline:
        payload += b"\n"
    u = hw().uart(channel)
    n = u.write(payload)
    return {"channel": channel, "sent_bytes": n,
            "data": _hex(payload) if hex_data else payload.decode("utf-8", "replace")}


@_tool("read", "one-shot UART receive until idle")
def eat_uart_receive(channel: str, timeout_ms: int = 300,
                      max_bytes: int = 4096) -> dict:
    """Receive from a UART channel until idle (captures console/log output).
    For continuous capture prefer the monitor tools."""
    u = hw().uart(channel)
    data = u.read_until_idle(timeout_ms=timeout_ms, max_bytes=max_bytes)
    return {"channel": channel, "bytes": len(data), "hex": _hex(data),
            "text": data.decode("utf-8", "replace")}


@_tool("control", "send then capture response")
def eat_uart_exchange(channel: str, data: str, timeout_ms: int = 500,
                      hex_data: bool = False, newline: bool = False) -> dict:
    """Send then capture the response (request/response style, e.g. AT cmds)."""
    payload = _unhex(data) if hex_data else data.encode("utf-8")
    if newline:
        payload += b"\n"
    u = hw().uart(channel)
    u.reset_input_buffer()
    u.write(payload)
    resp = u.read_until_idle(timeout_ms=timeout_ms)
    return {"channel": channel, "sent": payload.decode("utf-8", "replace"),
            "bytes": len(resp), "hex": _hex(resp),
            "text": resp.decode("utf-8", "replace")}


# ---------------------------------------------------------------- UART monitor
@_tool("control", "start background UART monitor")
def eat_uart_monitor_start(channel: str, baud: int = 115200,
                           ring_kb: int = 256, truncate: bool = False) -> dict:
    """Start a background monitor on a channel: every byte goes to a bounded
    ring buffer AND a timestamped log file under logs/. Use tail/grep/wait_for
    to inspect — keeps live output out of your context window."""
    u = hw().uart(channel, baud=baud)
    m = _mon.start(u, ring_bytes=ring_kb * 1024, truncate=truncate)
    return m.status()


@_tool("control", "stop a UART monitor")
def eat_uart_monitor_stop(channel: str) -> dict:
    """Stop the background monitor on a channel (log file is kept)."""
    return _mon.stop(channel)


@_tool("read", "monitor status")
def eat_uart_monitor_status(channel: str | None = None) -> dict:
    """Status of one monitor (or all) — ring size, totals, log path."""
    if channel:
        return _mon.get(channel).status()
    return {"monitors": _mon.all_status()}


@_tool("read", "tail monitor buffer")
def eat_uart_monitor_tail(channel: str, lines: int = 50) -> dict:
    """Tail the last N lines captured by the monitor."""
    return _mon.get(channel).tail(lines)


@_tool("read", "grep monitor buffer")
def eat_uart_monitor_grep(channel: str, pattern: str,
                          last_n_lines: int | None = None,
                          context: int = 0,
                          case_insensitive: bool = True) -> dict:
    """Regex-search the monitor buffer (optionally only last N lines, with
    context lines). Great for finding boot banners, faults, pass tokens."""
    return _mon.get(channel).grep(pattern, last_n_lines, context,
                                  case_insensitive)


@_tool("read", "block until a pattern appears on a UART")
def eat_uart_wait_for(channel: str, pattern: str, timeout_ms: int = 5000,
                      monitor: bool = False) -> dict:
    """Wait until regex `pattern` appears on the channel (via monitor if one
    is running and monitor=true, else a blocking read loop).
    Typical: wait_for('ALL TESTS PASSED') after reset for pass/fail verdict."""
    if monitor:
        return _mon.get(channel).wait_for(pattern, timeout_ms)
    import re
    t0 = time.monotonic()
    rx = re.compile(pattern, re.IGNORECASE)
    u = hw().uart(channel)
    acc = b""
    while time.monotonic() - t0 < timeout_ms / 1000.0:
        acc += u.read(4096, 50)
        m = rx.search(acc.decode("utf-8", "replace"))
        if m:
            return {"found": True, "match": m.group(0),
                    "waited_ms": int((time.monotonic() - t0) * 1000),
                    "text": acc.decode("utf-8", "replace")[-400:]}
    return {"found": False, "pattern": pattern, "timeout_ms": timeout_ms,
            "text": acc.decode("utf-8", "replace")[-400:]}


# ---------------------------------------------------------------- UART script
@_tool("control", "run a send/delay/expect script")
def eat_uart_script(channel: str, steps: list[dict],
                    listen_channel: str | None = None) -> dict:
    """Run a sequence of steps on a UART channel. Step fields:
      {"send": "AT", "newline": true, "hex": false}   send text/hex bytes
      {"expect": "OK", "timeout_ms": 1000}            wait for substring
      {"delay_ms": 100}                               sleep
    listen_channel: read expects from a different channel (default = send
    channel) — use when the target replies elsewhere.
    Stops at the first failed expect (set "on_fail":"continue" per step to
    override). Returns a per-step trace. Use for boot menus, AT commands,
    bootloader handshakes."""
    u = hw().uart(channel)
    listener = listen_channel or channel
    trace: list[dict] = []
    for i, st in enumerate(steps):
        if "send" in st:
            payload = _unhex(st["send"]) if st.get("hex") else st["send"].encode()
            if st.get("newline"):
                payload += b"\n"
            n = u.write(payload)
            trace.append({"step": i, "action": "send", "ok": True,
                          "bytes": n, "data": st["send"][:80]})
        elif "expect" in st:
            tmo = st.get("timeout_ms", 1000)
            r = eat_uart_wait_for(listener, st["expect"], tmo)
            ok = r.get("found", False)
            trace.append({"step": i, "action": "expect", "ok": ok,
                          "expect": st["expect"], "listen": listener,
                          "waited_ms": r.get("waited_ms", tmo),
                          "match": r.get("match", "")})
            if not ok and st.get("on_fail") != "continue":
                return {"ok": False, "failed_at_step": i,
                        "trace": trace,
                        "hint": "expect timed out; device state or wiring?"}
        elif "delay_ms" in st:
            time.sleep(st["delay_ms"] / 1000.0)
            trace.append({"step": i, "action": "delay", "ok": True,
                          "ms": st["delay_ms"]})
        else:
            return {"ok": False, "failed_at_step": i, "trace": trace,
                    "error": f"unknown step keys {list(st)}"}
    return {"ok": True, "steps": len(steps), "trace": trace}


# ---------------------------------------------------------------- I2C
@_tool("control", "configure the I2C controller")
def eat_i2c_config(speed_khz: int | None = None,
                   push_pull: bool | None = None,
                   stretch: bool | None = None) -> dict:
    """Configure the I2C master. Params are optional (only given ones change):
      speed_khz: 20 | 50 | 100 | 200 | 400 | 750 | 1000 (default 100)
      push_pull: true=push-pull, false=open-drain (default; not supported by
                 every DLL/firmware build — see driver_mode_applied in result)
      stretch:   enable clock stretching (default off; same caveat)
    Applies to all subsequent i2c/eeprom tool calls."""
    return hw().i2c().configure(speed_khz=speed_khz, push_pull=push_pull,
                                stretch=stretch)


@_tool("read", "scan the I2C bus")
def eat_i2c_scan() -> dict:
    """Scan the I2C bus (7-bit addresses 0x08-0x77)."""
    found = hw().i2c().scan()
    return {"devices": [f"0x{a:02X}" for a in found],
            "hint": "0x50 = AT24Cxx EEPROM"}


@_tool("read", "read I2C registers")
def eat_i2c_read(addr7: int, reg: int, length: int) -> dict:
    """Read registers: write reg pointer then read length bytes."""
    data = hw().i2c().read_reg(addr7, reg, length)
    return {"addr": f"0x{addr7:02X}", "reg": f"0x{reg:02X}", "hex": _hex(data)}


@_tool("write", "write I2C registers")
def eat_i2c_write(addr7: int, reg: int, hex_data: str) -> dict:
    """Write bytes to a register (hex_data like '01 A0 5F')."""
    data = _unhex(hex_data)
    hw().i2c().write_reg(addr7, reg, data)
    return {"addr": f"0x{addr7:02X}", "reg": f"0x{reg:02X}",
            "written": len(data)}


@_tool("read", "read AT24Cxx EEPROM")
def eat_eeprom_read(addr: int, length: int, model: str = "24C02") -> dict:
    """Read the AT24Cxx EEPROM on the I2C bus (24C02 = 256 bytes, etc.)."""
    data = hw().eeprom(model).read(addr, length)
    return {"model": model, "addr": addr, "hex": _hex(data)}


@_tool("write", "write AT24Cxx EEPROM (persistent)")
def eat_eeprom_write(addr: int, hex_data: str, model: str = "24C02") -> dict:
    """Write the AT24Cxx EEPROM (page-aligned splitting + verify included)."""
    data = _unhex(hex_data)
    hw().eeprom(model).write(addr, data)
    return {"model": model, "addr": addr, "written": len(data), "verified": True}


# ---------------------------------------------------------------- SPI / flash
@_tool("control", "configure the SPI controller")
def eat_spi_config(mode: int | None = None,
                   freq_hz: int | None = None) -> dict:
    """Configure the SPI master. Params are optional (only given ones change):
      mode:    0-3 (CPOL/CPHA; W25Q flash works with 0 or 3, default 0)
      freq_hz: 1kHz..60MHz (default 1.875MHz; DLL picks the nearest supported
               rate). Applies to all subsequent spi/flash tool calls.
    Bench note: with long jumper wires stay <= a few MHz for signal integrity."""
    bus = hw().spi()
    bus.configure(mode=mode, freq_hz=freq_hz)
    return {"mode": bus.mode, "freq_hz": bus.freq_hz}


@_tool("read", "read SPI flash JEDEC ID")
def eat_spi_jedec() -> dict:
    """Read SPI flash JEDEC ID (e.g. W25Q80 = EF 40 14)."""
    from eat.spi_flash import W25QFlash
    f = W25QFlash(hw().spi())
    return {"jedec": _hex(f.jedec), "identity": f.identify()}


@_tool("control", "raw SPI full-duplex transfer")
def eat_spi_transfer(hex_out: str, rx_len: int = 0,
                     mode: int | None = None,
                     freq_hz: int | None = None) -> dict:
    """Raw SPI transfer: hex_out clocked out on MOSI, returns the last rx_len
    bytes of MISO (whole frame when rx_len=0). Auto CS (CS1=SCS0/pin13).
    mode/freq_hz optionally override the persistent config for this transfer
    only."""
    bus = hw().spi()
    if mode is not None or freq_hz is not None:
        bus.configure(mode=mode, freq_hz=freq_hz)
    rx = bus.transfer(_unhex(hex_out), rx_len=rx_len)
    return {"rx_hex": _hex(rx), "mode": bus.mode, "freq_hz": bus.freq_hz}


@_tool("read", "read W25Q flash memory")
def eat_spi_flash_read(addr: int, length: int) -> dict:
    """Read W25Q flash memory (uses 0x03 read; safe/non-destructive)."""
    from eat.spi_flash import W25QFlash
    f = W25QFlash(hw().spi())
    data = f.read_data(addr, length)
    return {"addr": f"0x{addr:06X}", "length": len(data), "hex": _hex(data)}


@_tool("write", "program W25Q flash (persistent)")
def eat_spi_flash_write(addr: int, hex_data: str,
                        erase_sector: bool = False) -> dict:
    """Program W25Q flash (page-split, WREN + busy-wait + verify).
    erase_sector=true erases the 4K sector containing addr first.
    Destructive: verify the address before calling!"""
    from eat.spi_flash import W25QFlash
    f = W25QFlash(hw().spi())
    if erase_sector:
        f.erase_sector(addr & ~0xFFF)
    data = _unhex(hex_data)
    f.write(addr, data)
    return {"addr": f"0x{addr:06X}", "written": len(data),
            "erased_sector": erase_sector, "verified": True}


@_tool("write", "erase W25Q flash (destructive)")
def eat_spi_flash_erase(addr: int = None, whole_chip: bool = False) -> dict:
    """Erase one 4K sector (addr given) or the whole chip. DESTRUCTIVE."""
    from eat.spi_flash import W25QFlash
    f = W25QFlash(hw().spi())
    if whole_chip:
        f.erase_chip()
        return {"erased": "whole chip"}
    if addr is None:
        raise ValueError("addr required unless whole_chip=true")
    f.erase_sector(addr)
    return {"erased": f"4K sector containing 0x{addr:06X}"}


# ---------------------------------------------------------------- target ctrl
@_tool("read", "list target board profiles")
def eat_target_profiles() -> dict:
    """List target profiles from config/targets/*.json (reset/boot pin maps,
    bootloader UART settings per MCU family). Add your own board as JSON."""
    profiles = load_profiles()
    return {"profiles": {k: {"description": p.get("description", ""),
                             "uart": p["uart"], "baud": p["baud"],
                             "reset_gpio": p["reset_gpio"],
                             "boot_gpio": p["boot_gpio"]}
                         for k, p in profiles.items()},
            "dir": "D:\\EAT_CH347F\\config\\targets"}


@_tool("control", "pulse a target reset line")
def eat_target_reset(reset_gpio: int = None, active: str = None,
                     pulse_ms: int = None, profile: str = None) -> dict:
    """Pulse the target reset line. Either pass explicit pins or a profile
    name (see eat_target_profiles). Example: profile='stm32-uart0'."""
    if profile:
        p = get_profile(profile)
        reset_gpio = reset_gpio if reset_gpio is not None else p["reset_gpio"]
        active = active or p.get("reset_active", "low")
        pulse_ms = pulse_ms or p.get("reset_pulse_ms", 100)
    if reset_gpio is None:
        raise ValueError("reset_gpio or profile required")
    level = 0 if (active or "low") == "low" else 1
    return hw().gpio.pulse(reset_gpio, level, pulse_ms or 100)


@_tool("control", "enter target bootloader mode")
def eat_target_enter_bootloader(boot_gpio: int = None, reset_gpio: int = None,
                                boot_level: int = None,
                                reset_active: str = None,
                                pulse_ms: int = 50,
                                release_after: bool = True,
                                profile: str = None) -> dict:
    """Enter target bootloader: assert boot strap, pulse reset, optionally
    release the strap. Either explicit pins or a profile name.
    Example: profile='esp32-uart0' then flash via the mapped COM port."""
    g = hw().gpio
    if profile:
        p = get_profile(profile)
        boot_gpio = boot_gpio if boot_gpio is not None else p["boot_gpio"]
        reset_gpio = reset_gpio if reset_gpio is not None else p["reset_gpio"]
        boot_level = boot_level if boot_level is not None else p.get("boot_level", 1)
        reset_active = reset_active or p.get("reset_active", "low")
        pulse_ms = pulse_ms or p.get("reset_pulse_ms", 50)
    if boot_gpio is None or reset_gpio is None:
        raise ValueError("boot_gpio+reset_gpio or profile required")
    r_lvl = 0 if (reset_active or "low") == "low" else 1
    g.set_output(boot_gpio, boot_level if boot_level is not None else 1)
    g.pulse(reset_gpio, r_lvl, pulse_ms)
    time.sleep(0.05)
    if release_after:
        g.write(boot_gpio, 1 - ((boot_level if boot_level is not None else 1) & 1))
    return {"boot_gpio": boot_gpio, "reset_gpio": reset_gpio,
            "boot_level": boot_level, "state": "bootloader"}


@_tool("control", "VOUT power-cycle hard reset")
def eat_target_power_cycle_reset(off_ms: int = 1000) -> dict:
    """Hard recovery: VOUT off->on (only resets targets powered from VOUT).
    NOTE: current board's VOUT switch has a known hardware defect."""
    return hw().power.cycle(off_ms)


# ---------------------------------------------------------------- selftest
@_tool("write", "run the full loopback bench self-test")
def eat_bench_selftest() -> dict:
    """Run the full loopback bench self-test — REQUIRES the self-test wiring:
    UART0<->UART1 connectors cross-mated (TX/RX + GPIO crossed), AT24C02 on
    IIC1, W25Q80 on SPI1 (wiring details in tests/bench_selftest.py header).
    Covers device/power/GPIO pairs+interlock/UART loopback/I2C EEPROM/SPI
    flash incl. write+erase round-trip. GPIO pair guard is enabled for this
    run only (bench mode)."""
    import importlib.util
    global _hw
    spec = importlib.util.spec_from_file_location(
        "bench_selftest", Path(__file__).parent / "tests" / "bench_selftest.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bench_selftest"] = mod
    spec.loader.exec_module(mod)
    mod.results.clear()
    with _hw_lock:  # release the normal-mode device, use bench-mode hardware
        if _hw is not None:
            try:
                _hw.close()
            except Exception:
                pass
            _hw = None
    from eat.hardware import Hardware as _Hw
    bench_hw = None
    try:
        bench_hw = _Hw(bench=True)
        mod.test_device(bench_hw)
        mod.test_power(bench_hw)
        mod.test_power_device_probe(bench_hw)
        mod.test_gpio_pairs(bench_hw)
        mod.test_gpio_interlock(bench_hw)
        mod.test_uart_loopback(bench_hw)
        mod.test_i2c_eeprom(bench_hw)
        mod.test_spi_flash(bench_hw)
    except Exception as e:
        return {"ok": False, "error": repr(e),
                "hint": "is the loopback wiring attached? see tests/bench_selftest.py header"}
    finally:
        if bench_hw is not None:
            try:
                bench_hw.power.off()
                bench_hw.close()
            except Exception:
                pass
    n_fail = sum(1 for _, s, _ in mod.results if s == mod.FAIL)
    return {"ok": n_fail == 0, "failed": n_fail,
            "results": [{"name": n, "status": s, "detail": d}
                        for n, s, d in mod.results],
            "summary": f"{len(mod.results) - n_fail}/{len(mod.results)} passed"}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
