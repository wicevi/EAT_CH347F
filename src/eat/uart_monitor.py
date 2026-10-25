"""Background UART monitor: ring buffer + timestamped log file + tail/grep.

Borrowed pattern from esp32-ai-loop-mcp-server / platformio.mcp: a background
thread owns the port and streams every byte into (a) a bounded ring buffer and
(b) a persistent log file; agents then use tail/grep instead of pulling a live
TTY into their context window.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .uart import UartChannel

DEFAULT_RING_BYTES = 256 * 1024
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


class UartMonitor:
    """One background monitor bound to a UART channel."""

    def __init__(self, channel: UartChannel, ring_bytes: int = DEFAULT_RING_BYTES,
                 log_path: Path | None = None, truncate: bool = False):
        self.channel = channel
        self.ring = bytearray()
        self.ring_bytes = ring_bytes
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.total = 0
        self.started_at = time.time()
        LOG_DIR.mkdir(exist_ok=True)
        if log_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = LOG_DIR / f"{channel.name}_{ts}.log"
        self.log_path = Path(log_path)
        self._fh = open(self.log_path, "a" if not truncate else "w",
                        encoding="utf-8", errors="replace")
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name=f"eat-monitor-{channel.name}")
        self.thread.start()

    # -- background loop --------------------------------------------------------
    def _run(self) -> None:
        ser = self.channel.ser
        ser.timeout = 0.05
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = ser.read(4096)
            except Exception as e:  # port died (replug, claim by flasher)
                self._fh.write(f"\n[monitor] read error: {e}\n")
                self._fh.flush()
                time.sleep(0.5)
                continue
            if not chunk:
                continue
            with self._lock:
                self.ring += chunk
                if len(self.ring) > self.ring_bytes:
                    del self.ring[:len(self.ring) - self.ring_bytes]
                self.total += len(chunk)
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                try:
                    self._fh.write(f"{ts} {line.decode('utf-8', 'replace')}\n")
                except Exception:
                    pass
            if buf and len(buf) > 8192:  # flush oversized unterminated chunk
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._fh.write(f"{ts} {buf.decode('utf-8', 'replace')}\\n")
                buf = b""

    # -- public API ---------------------------------------------------------------
    def send(self, data: bytes) -> int:
        with self._lock:  # serialize against reader only loosely; pyserial is thread-safe per op
            return self.channel.write(data)

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self.ring)

    def tail(self, lines: int = 50, as_text: bool = True) -> dict:
        data = self.snapshot()
        all_lines = data.split(b"\n")
        tail_lines = all_lines[-lines:] if lines else all_lines
        text = b"\n".join(tail_lines).decode("utf-8", "replace")
        return {"channel": self.channel.name, "lines": len(tail_lines),
                "text": text if as_text else text}

    def grep(self, pattern: str, last_n_lines: int | None = None,
             context: int = 0, case_insensitive: bool = True) -> dict:
        data = self.snapshot().decode("utf-8", "replace")
        all_lines = data.splitlines()
        scope = all_lines[-last_n_lines:] if last_n_lines else all_lines
        flags = re.IGNORECASE if case_insensitive else 0
        rx = re.compile(pattern, flags)
        hits: list[str] = []
        for i, line in enumerate(scope):
            if rx.search(line):
                lo = max(0, i - context)
                hi = min(len(scope), i + context + 1)
                seg = scope[lo:hi]
                hits.append("\n".join(seg))
        return {"channel": self.channel.name, "pattern": pattern,
                "matches": len(hits), "lines": hits[:50],
                "note": "showing up to 50 matching blocks"}

    def wait_for(self, pattern: str, timeout_ms: int = 5000,
                 from_start: bool = False) -> dict:
        """Block until `pattern` (regex) appears after the call (or from ring
        start when from_start). Returns matched line + waited time."""
        flags = re.IGNORECASE
        rx = re.compile(pattern, flags)
        t0 = time.monotonic()
        offset = 0 if from_start else len(self.snapshot())
        while True:
            data = self.snapshot()[offset:]
            text = data.decode("utf-8", "replace")
            m = rx.search(text)
            if m:
                line = text[max(0, m.start() - 80):m.end() + 80].splitlines()
                return {"found": True, "waited_ms": int((time.monotonic() - t0) * 1000),
                        "match": m.group(0),
                        "context": (line[-1] if line else "")[:300]}
            if (time.monotonic() - t0) * 1000 >= timeout_ms:
                return {"found": False, "waited_ms": timeout_ms, "pattern": pattern}
            time.sleep(0.05)

    def status(self) -> dict:
        return {"channel": self.channel.name, "port": self.channel.port,
                "running": self.thread is not None and self.thread.is_alive(),
                "ring_bytes": len(self.ring), "total_bytes": self.total,
                "log_path": str(self.log_path),
                "uptime_s": round(time.time() - self.started_at, 1)}

    def stop(self) -> dict:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        try:
            self._fh.close()
        except Exception:
            pass
        self.thread = None
        return self.status()


class MonitorManager:
    """Owns at most one UartMonitor per channel (UART0/UART1)."""

    def __init__(self):
        self._monitors: dict[str, UartMonitor] = {}

    def start(self, channel: UartChannel, **kw) -> UartMonitor:
        name = channel.name
        if name in self._monitors:
            raise RuntimeError(f"monitor already running on {name}; stop first")
        m = UartMonitor(channel, **kw)
        self._monitors[name] = m
        return m

    def get(self, channel: str) -> UartMonitor:
        m = self._monitors.get(channel.upper())
        if m is None:
            raise RuntimeError(f"no monitor running on {channel}")
        return m

    def stop(self, channel: str) -> dict:
        m = self._monitors.pop(channel.upper(), None)
        if m is None:
            raise RuntimeError(f"no monitor running on {channel}")
        return m.stop()

    def stop_all(self) -> None:
        for ch in list(self._monitors):
            self._monitors.pop(ch).stop()

    def all_status(self) -> list[dict]:
        return [m.status() for m in self._monitors.values()]
