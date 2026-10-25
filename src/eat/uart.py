"""UART0/UART1 via the CH343SER VCP COM ports (pyserial)."""
from __future__ import annotations

import serial  # pyserial

from .board import detect_uart_coms


class UartError(RuntimeError):
    pass


class UartChannel:
    """One CH347F UART channel (UART0=MI_00, UART1=MI_02)."""

    def __init__(self, name: str, port: str, baud: int = 115200,
                 bytesize: int = 8, parity: str = "N", stopbits: float = 1):
        self.name, self.port = name, port
        self.ser = serial.Serial(port, baudrate=baud, bytesize=bytesize,
                                 parity=parity, stopbits=stopbits,
                                 timeout=0.1, write_timeout=1.0)

    def configure(self, baud: int = None, bytesize: int = None,
                  parity: str = None, stopbits: float = None,
                  read_timeout_ms: int = None) -> None:
        if baud: self.ser.baudrate = baud
        if bytesize: self.ser.bytesize = bytesize
        if parity: self.ser.parity = parity
        if stopbits: self.ser.stopbits = stopbits
        if read_timeout_ms is not None:
            self.ser.timeout = read_timeout_ms / 1000.0

    def write(self, data: bytes) -> int:
        return self.ser.write(data)

    def read(self, n: int, timeout_ms: int) -> bytes:
        self.ser.timeout = timeout_ms / 1000.0
        return self.ser.read(n)

    def read_until_idle(self, timeout_ms: int = 200, idle_ms: int = 30,
                        max_bytes: int = 65536) -> bytes:
        """Read until the line goes idle (good for log/console capture)."""
        import time
        self.ser.timeout = idle_ms / 1000.0
        end = time.monotonic() + timeout_ms / 1000.0
        out = bytearray()
        while time.monotonic() < end and len(out) < max_bytes:
            chunk = self.ser.read(max(1, min(4096, max_bytes - len(out))))
            if chunk:
                out += chunk
                continue
            if out:
                break
        return bytes(out)

    def reset_input_buffer(self) -> None:
        self.ser.reset_input_buffer()

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_uarts(baud: int = 115200) -> dict[str, UartChannel]:
    """Open whichever of UART0/UART1 are present as COM ports."""
    coms = detect_uart_coms()
    chans: dict[str, UartChannel] = {}
    for name, port in coms.items():
        if port:
            try:
                chans[name] = UartChannel(name, port, baud=baud)
            except serial.SerialException as e:
                raise UartError(f"cannot open {name} on {port}: {e}") from e
    return chans
