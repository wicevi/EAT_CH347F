"""SPI bus helpers + W25Qxx NOR flash driver (read path verified on bench)."""
from __future__ import annotations

import time

from .ch347_api import CH347Device

# W25Q standard commands
W25X_WREN = 0x06
W25X_WRDI = 0x04
W25X_RDSR1 = 0x05
W25X_RDSR2 = 0x35
W25X_WRSR1 = 0x01
W25X_READ = 0x03
W25X_FAST_READ = 0x0B
W25X_PAGE_PROGRAM = 0x02
W25X_SECTOR_ERASE = 0x20
W25X_BLOCK_ERASE_32K = 0x52
W25X_BLOCK_ERASE_64K = 0xD8
W25X_CHIP_ERASE = 0xC7
W25X_JEDEC_ID = 0x9F
W25X_RELEASE_PD = 0xAB
W25X_POWER_DOWN = 0xB9

JEDEC_NAMES = {
    b"\xef\x40\x14": "W25Q80 (Winbond, 1MB)",
    b"\xef\x40\x13": "W25Q40 (512KB)",
    b"\xef\x40\x12": "W25Q20 (256KB)",
    b"\xef\x40\x11": "W25Q10 (128KB)",
    b"\xef\x40\x16": "W25Q16 (2MB)",
    b"\xef\x40\x17": "W25Q32 (4MB)",
    b"\xef\x40\x18": "W25Q64 (8MB)",
}


class SpiBus:
    """SPI bus with persistent, re-configurable mode/frequency."""

    def __init__(self, dev: CH347Device, mode: int = 0, freq_hz: int = 1_875_000):
        self.dev = dev
        self.mode = mode
        self.freq_hz = freq_hz
        self._apply()

    def configure(self, mode: int | None = None, freq_hz: int | None = None) -> None:
        if mode is not None:
            if not 0 <= mode <= 3:
                raise ValueError("SPI mode must be 0-3")
            self.mode = mode
        if freq_hz is not None:
            if not 1_000 <= freq_hz <= 60_000_000:
                raise ValueError("SPI frequency must be 1kHz..60MHz")
            self.freq_hz = freq_hz
        self._apply()

    def _apply(self) -> None:
        self.dev.spi_init(mode=self.mode, freq_hz=self.freq_hz)

    def transfer(self, data: bytes, rx_len: int = 0) -> bytes:
        return self.dev.spi_transfer(data, rx_len=rx_len)


class W25QFlash:
    PAGE = 256
    SECTOR = 4096

    def __init__(self, bus: SpiBus):
        self.bus = bus
        self.jedec = self.read_jedec_id()

    # -- registers ---------------------------------------------------------------
    # bench note: all reads go through the FULL-DUPLEX path (CH347SPI_WriteRead).
    # The endpoint CH347SPI_Read ("send cmd then read") returns 0xFF on this
    # bench wiring; full-duplex frames capture MISO correctly.
    def read_jedec_id(self) -> bytes:
        return self.bus.transfer(bytes([W25X_JEDEC_ID, 0xFF, 0xFF, 0xFF]),
                                 rx_len=3)

    def read_status(self, n: int = 1) -> bytes:
        return self.bus.transfer(bytes([W25X_RDSR1] + [0xFF] * n), rx_len=n)

    def _wren(self) -> None:
        self.bus.dev.spi_write(bytes([W25X_WREN]))

    def _wait_busy(self, timeout_ms: int = 3000) -> None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_ms / 1000.0:
            sr = self.read_status()
            if not (sr[0] & 0x01):
                return
            time.sleep(0.002)
        raise TimeoutError("flash busy timeout")

    # -- read --------------------------------------------------------------------
    def read_data(self, addr: int, n: int, chunk: int = 1024) -> bytes:
        out = bytearray()
        pos = 0
        while pos < n:
            m = min(chunk, n - pos)
            a = addr + pos
            out += self.bus.transfer(
                bytes([W25X_READ, (a >> 16) & 0xFF, (a >> 8) & 0xFF, a & 0xFF])
                + b"\xFF" * m, rx_len=m)
            pos += m
        return bytes(out)

    # -- write/erase (page program bounded, auto WREN + busy-wait) ---------------
    def page_program(self, addr: int, data: bytes) -> None:
        if len(data) > self.PAGE:
            raise ValueError("page program limited to 256 bytes")
        if addr // self.PAGE != (addr + len(data) - 1) // self.PAGE:
            raise ValueError("page-crossing write; split at caller")
        self._wren()
        self.bus.dev.spi_write(bytes([W25X_PAGE_PROGRAM,
                                      (addr >> 16) & 0xFF, (addr >> 8) & 0xFF,
                                      addr & 0xFF]) + data)
        self._wait_busy()

    def write(self, addr: int, data: bytes, verify: bool = True) -> None:
        for pos in range(0, len(data), self.PAGE):
            self.page_program(addr + pos, data[pos:pos + self.PAGE])
        if verify:
            got = self.read_data(addr, len(data))
            if got != data:
                raise RuntimeError(f"flash verify failed @{addr:#06x}")

    def erase_sector(self, addr: int) -> None:
        self._wren()
        self.bus.dev.spi_write(bytes([W25X_SECTOR_ERASE, (addr >> 16) & 0xFF,
                                      (addr >> 8) & 0xFF, addr & 0xFF]))
        self._wait_busy(timeout_ms=5000)

    def erase_chip(self) -> None:
        self._wren()
        self.bus.dev.spi_write(bytes([W25X_CHIP_ERASE]))
        self._wait_busy(timeout_ms=120_000)

    def identify(self) -> str:
        return JEDEC_NAMES.get(self.jedec,
                               f"unknown JEDEC {self.jedec.hex(' ')}")
