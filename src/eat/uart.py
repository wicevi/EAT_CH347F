"""UART0/UART1 via the CH343SER VCP COM ports (pyserial)."""
from __future__ import annotations

import serial  # pyserial

from .board import detect_uart_coms


class UartError(RuntimeError):
    pass


class UartChannel:
    """One CH347F UART channel (UART0=MI_00, UART1=MI_02).

    Control lines default to DEASSERTED (dtr=False, rts=False) — and are set
    BEFORE open so the driver never asserts them, not even briefly.

    Why: CH347F muxes the UART modem outputs with other functions:
        DTR0 -> GPIO2 net   (UART0 connector pin1; often a target BOOT strap)
        RTS0 -> GPIO1       (chip pin18)
        DTR1 -> SCS1        (chip pin7; SPI CS1)
        RTS1 -> SDA net     (chip pin12; the I2C bus!)
    pyserial defaults to dtr=rts=True, so a plain `serial.Serial('COMx')`
    holds those pins low for as long as the port is open (target stuck in
    bootloader, I2C bus dragged low). Only assert them explicitly for
    DTR/RTS reset-signalling flows, and never while the muxed function
    (GPIO2/SDA/...) is in use.
    """

    def __init__(self, name: str, port: str, baud: int = 115200,
                 bytesize: int = 8, parity: str = "N", stopbits: float = 1,
                 dtr: bool = False, rts: bool = False):
        self.name, self.port = name, port
        self.ser = serial.Serial()          # no auto-open
        self.ser.port = port
        self.ser.baudrate = baud
        self.ser.bytesize = bytesize
        self.ser.parity = parity
        self.ser.stopbits = stopbits
        self.ser.timeout = 0.1
        self.ser.write_timeout = 1.0
        # cached pre-open: ends up in the DCB (DTR_CONTROL_DISABLE etc.) so
        # the port opens with the lines already deasserted
        self.ser.dtr = bool(dtr)
        self.ser.rts = bool(rts)
        self.ser.open()

    def set_control_lines(self, dtr: bool | None = None,
                          rts: bool | None = None) -> dict:
        """Drive DTR/RTS explicitly. Asserted = pin LOW on the muxed net
        (DTR->GPIO2 on UART0, RTS->SDA on IIC1). Use deliberately."""
        if dtr is not None:
            self.ser.dtr = bool(dtr)
        if rts is not None:
            self.ser.rts = bool(rts)
        return {"dtr": bool(self.ser.dtr), "rts": bool(self.ser.rts)}

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
