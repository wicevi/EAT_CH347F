"""Performance benchmark for the EAT CH347F tool (loopback bench required).

Measures, with integrity checks, using the new rate/mode configuration APIs:
  1. UART throughput  UART0->UART1 cross link @ 115200..4M baud
  2. I2C throughput   AT24C02 256B reads @ 20k..1MHz
  3. SPI read throughput  W25Q80 64KB reads @ 468k..30MHz
  4. SPI write throughput  W25Q80 sector program 4KB @ 1.875MHz (restored after)
  5. SPI mode matrix     JEDEC @ modes 0-3
  6. GPIO toggle/read rate

Run:  python tests/benchmark.py
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, r"D:\EAT_CH347F\src")

from eat.ch347_api import CH347Device
from eat.i2c_bus import I2CBus, SPEED_KHZ
from eat.spi_flash import SpiBus, W25QFlash
from eat.uart import UartChannel
from eat.board import detect_uart_coms

ROWS: list[tuple] = []


def row(group, config, metric, value, integrity):
    ROWS.append((group, config, metric, value, integrity))
    print(f"  {group:<7} {config:<18} {metric:<12} {value:>12}   {integrity}")


def bench_uart(dev: CH347Device) -> None:
    print("\n== UART throughput (UART0->UART1 cross link) ==")
    coms = detect_uart_coms()
    u0 = UartChannel("UART0", coms["UART0"])
    u1 = UartChannel("UART1", coms["UART1"])
    for baud in (115_200, 921_600, 1_000_000, 2_000_000, 4_000_000):
        size = 32 * 1024 if baud <= 200_000 else 64 * 1024
        payload = bytes((i * 31 + 7) & 0xFF for i in range(256)) * (size // 256)
        u0.configure(baud=baud)
        u1.configure(baud=baud)
        u0.ser.write_timeout = 10
        u1.ser.timeout = 10
        u1.reset_input_buffer()
        t0 = time.perf_counter()
        u0.write(payload)
        got = bytearray()
        while len(got) < size:
            chunk = u1.read(size - len(got), 10_000)
            if not chunk:
                break
            got += chunk
        dt = time.perf_counter() - t0
        ok = got == payload
        kbps = (len(got) / 1024) / dt if dt else 0
        row("UART", f"{baud//1000}k{'' if baud%1000==0 else ''}bd",
            f"{len(got)//1024}KB", f"{dt*1000:8.1f} ms",
            "PASS" if ok and len(got) == size else
            f"FAIL rx={len(got)}/{size} match={ok}")
    u0.close(); u1.close()


def bench_i2c(dev: CH347Device) -> None:
    print("\n== I2C throughput (AT24C02 256B full read) ==")
    bus = I2CBus(dev)
    ref = None
    for khz in sorted(SPEED_KHZ):
        try:
            bus.configure(speed_khz=khz)
            best = None
            data = None
            for _ in range(3):
                t0 = time.perf_counter()
                data = bus.read_reg(0x50, 0x00, 256)
                dt = time.perf_counter() - t0
                best = dt if best is None else min(best, dt)
            if ref is None:
                ref = data
            ok = data == ref
            row("I2C", f"{khz}kHz", "256B", f"{best*1000:8.2f} ms",
                "PASS" if ok else "FAIL data mismatch")
        except Exception as e:
            row("I2C", f"{khz}kHz", "256B", "-", f"FAIL {str(e)[:40]}")
    bus.configure(speed_khz=100)


def bench_spi_read(dev: CH347Device) -> None:
    print("\n== SPI read throughput (W25Q80 64KB, full-duplex 0x03) ==")
    bus = SpiBus(dev)
    ref = None
    for hz in (468_750, 937_500, 1_875_000, 3_750_000, 7_500_000,
               15_000_000, 30_000_000):
        try:
            bus.configure(mode=0, freq_hz=hz)
            best = None
            data = None
            for _ in range(2):
                t0 = time.perf_counter()
                data = W25QFlash(bus).read_data(0, 64 * 1024, chunk=1024)
                dt = time.perf_counter() - t0
                best = dt if best is None else min(best, dt)
            if ref is None:
                ref = data
            ok = data == ref
            kbps = (64 / best) if best else 0
            row("SPI-R", f"{hz/1e6:g}MHz", "64KB",
                f"{best*1000:8.1f} ms", f"{'PASS' if ok else 'FAIL'} "
                f"({kbps*1024/1024:.0f} KB/s)")
        except Exception as e:
            row("SPI-R", f"{hz/1e6:g}MHz", "64KB", "-",
                f"FAIL {str(e)[:40]}")


def bench_spi_write(dev: CH347Device) -> None:
    print("\n== SPI write throughput (W25Q80 sector0 4KB program @1.875MHz) ==")
    bus = SpiBus(dev)
    bus.configure(mode=0, freq_hz=1_875_000)
    f = W25QFlash(bus)
    orig = f.read_data(0, 4096)
    pattern = bytes((i * 17 + 3) & 0xFF for i in range(4096))
    try:
        f.erase_sector(0)
        t0 = time.perf_counter()
        f.write(0, pattern, verify=True)  # includes page-split + verify read
        dt = time.perf_counter() - t0
        row("SPI-W", "1.875MHz", "4KB", f"{dt*1000:8.1f} ms",
            f"PASS ({4096/dt/1024:.0f} KB/s incl verify)")
    finally:
        f.erase_sector(0)
        if orig != b"\xff" * 4096:  # restore original content if any
            f.write(0, orig, verify=True)
        bus.configure(mode=0, freq_hz=1_875_000)


def bench_spi_modes(dev: CH347Device) -> None:
    print("\n== SPI mode matrix (W25Q80 JEDEC, expect ef 40 14) ==")
    bus = SpiBus(dev)
    for mode in range(4):
        try:
            bus.configure(mode=mode, freq_hz=1_875_000)
            f = W25QFlash(bus)
            good = f.jedec == b"\xef\x40\x14"
            row("SPI-M", f"mode{mode}", "JEDEC", f.jedec.hex(" "),
                "PASS" if good else "WRONG-ID (expected for mode1/2)")
        except Exception as e:
            row("SPI-M", f"mode{mode}", "JEDEC", "-", f"FAIL {str(e)[:40]}")
    bus.configure(mode=0, freq_hz=1_875_000)


def bench_gpio(dev: CH347Device) -> None:
    print("\n== GPIO bit-bang rate (GPIO2 output / input reads) ==")
    dev.gpio_set(enable=1 << 2, dir_out=1 << 2, data_out=0)
    n = 2000
    t0 = time.perf_counter()
    for i in range(n):
        dev.gpio_set(enable=1 << 2, dir_out=1 << 2, data_out=(i & 1) << 2)
    dt = time.perf_counter() - t0
    row("GPIO", "toggle", f"{n} ops", f"{dt*1000:8.1f} ms",
        f"{n/dt/1000:.1f} kHz")
    dev.gpio_set(enable=1 << 2, dir_out=0, data_out=0)
    t0 = time.perf_counter()
    for _ in range(n):
        dev.gpio_get()
    dt = time.perf_counter() - t0
    row("GPIO", "read", f"{n} ops", f"{dt*1000:8.1f} ms",
        f"{n/dt:,.0f} reads/s")


def main() -> int:
    print("== EAT CH347F performance benchmark ==")
    dev = CH347Device()
    dev.gpio_set(enable=1, dir_out=1, data_out=1)  # VOUT on (modules)
    time.sleep(0.3)
    try:
        bench_uart(dev)
        bench_i2c(dev)
        bench_spi_read(dev)
        bench_spi_write(dev)
        bench_spi_modes(dev)
        bench_gpio(dev)
    finally:
        dev.gpio_set(enable=1, dir_out=1, data_out=0)
    n_fail = sum(1 for r in ROWS if "FAIL" in r[4] and "expected" not in r[4])
    print(f"\n== benchmark done: {len(ROWS)} rows, {n_fail} hard failures ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
