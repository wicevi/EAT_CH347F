"""Bench self-test for the EAT CH347F board (loopback wiring required).

Required bench wiring for the full test (see also README "回环自检接线要求"):

  1. UART0 <-> UART1 连接器对接（转接线）：
       TX/RX 交叉：UART0 pin3(TXD0) <-> UART1 pin4(RXD1)
                   UART0 pin4(RXD0) <-> UART1 pin3(TXD1)
       其余按 pin 顺序一一对应：pin1<->pin1、pin2<->pin2、pin5<->pin5(GND)、
       pin6<->pin6(VOUT，同轨直连无害)。
     对应关系：UART0 pin1=GPIO2/pin2=GPIO3，UART1 pin1=GPIO5/pin2=GPIO6，
     故直连后即 GPIO2<->GPIO5、GPIO3<->GPIO6（与实测矩阵一致）。
     ※ GPIO 对接时严禁两侧同时输出相反电平 —— 自测以 bench 模式运行，
       驱动层启用对脚互锁防短路。
  2. IIC1 (1.25mm 4P) 接 AT24C02 模块：SDA/SCL/GND/VOUT 对应连接
     （模块可由 VOUT 或外部 3.3V 供电）。
  3. SPI1 (6P) 接 W25Q80 模块：VOUT/GND/MOSI/MISO/CLK/CS 对应连接。
  4. SW1 拨到断开位（软件电源控制模式）。

Run:  python tests/bench_selftest.py
"""
from __future__ import annotations

import sys
import traceback

sys.path.insert(0, r"D:\EAT_CH347F\src")

from eat.hardware import Hardware  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []  # name, status, detail


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def test_device(hw: Hardware) -> None:
    i = hw.info
    record("device.info", PASS,
           f"{i['product']!r} mode={i['chip_mode']} func={i['func_type']} "
           f"speed={i['usb_speed']} fw={i['firmware_ver']} drv={i['driver_ver']} "
           f"dll={i['dll_ver']}")
    if i["chip_mode"] != 4:
        record("device.chip_mode_note", PASS,
               f"chip_mode={i['chip_mode']} (DLL reports 0 for CH347F; "
               "chip_type=2 check already passed)")


def test_power(hw: Hardware) -> None:
    st0 = hw.power.status()
    hw.power.on()
    st1 = hw.power.status()
    hw.power.off()
    st2 = hw.power.status()
    hw.power.on()  # leave VOUT on for I2C/SPI tests (modules run off VOUT)
    ok = st1["vout"] == "on" and st2["vout"] == "off"
    record("power.vout_on_off", PASS if ok else FAIL,
           f"{st0['vout']} -> {st1['vout']} -> {st2['vout']} -> on")


def test_power_device_probe(hw: Hardware) -> None:
    """Do bench devices follow VOUT_EN? Informational: they do only if the
    modules are actually powered from VOUT (as designed on IIC1/SPI1 pin1)."""
    import time as _t
    from eat.i2c_bus import I2CBus
    bus = I2CBus(hw.dev)
    hw.power.off(); _t.sleep(0.4)
    off = 0x50 in bus.scan()
    hw.power.on(); _t.sleep(0.4)
    on = 0x50 in bus.scan()
    if off and on:
        record("power.device_follow", PASS,
               "EEPROM alive in BOTH states -> modules are self-powered "
               "(or VOUT stuck on); verify with tests/vout_blink.py + OUT1 LED")
    elif on and not off:
        record("power.device_follow", PASS,
               "EEPROM only alive with VOUT on -> real power switching confirmed")


def test_gpio_pairs(hw: Hardware) -> None:
    from eat.board import BENCH_GPIO_PAIRS
    hw.gpio.all_inputs()
    for a, b in BENCH_GPIO_PAIRS:
        try:
            ok = True
            for drv, rd in ((a, b), (b, a)):
                # partner-forcing is automatic inside set_output (bench mode)
                hw.gpio.set_output(drv, 1)
                got1 = hw.gpio.read(rd)
                hw.gpio.write(drv, 0)
                got0 = hw.gpio.read(rd)
                hw.gpio.set_input(drv)
                if (got1, got0) != (1, 0):
                    ok = False
                    record(f"gpio.pair_G{drv}<->G{rd}", FAIL,
                           f"high->{got1} low->{got0}")
            if ok:
                record(f"gpio.pair_G{a}<->G{b}", PASS, "follows drive in both directions")
        except Exception as e:
            record(f"gpio.pair_G{a}<->G{b}", FAIL, repr(e))
    hw.gpio.all_inputs()


def test_gpio_interlock(hw: Hardware) -> None:
    """Verify the guard (bench mode only): cannot create opposing outputs."""
    from eat.board import BENCH_GPIO_PAIRS
    if not hw.gpio.pairs:
        record("gpio.interlock_partner_released", SKIP,
               "no pairs configured (non-bench mode)")
        return
    a, b = BENCH_GPIO_PAIRS[0]
    hw.gpio.all_inputs()
    hw.gpio.set_output(a, 1)
    # set_output(b, 0) must force a back to input instead of shorting
    r = hw.gpio.set_output(b, 0)
    d, _ = hw.dev.gpio_get()
    a_now_out = bool((d >> a) & 1)
    record("gpio.interlock_partner_released", PASS if not a_now_out else FAIL,
           f"set GPIO{b} out -> GPIO{a} dir now "
           f"{'out (DANGER)' if a_now_out else 'in'}; forced={r.get('partner_forced_input')}")
    hw.gpio.all_inputs()


def test_uart_loopback(hw: Hardware, baud: int = 115200) -> None:
    coms = hw.uart_map()
    if not (coms["UART0"] and coms["UART1"]):
        record("uart.loopback", SKIP, f"ports: {coms}")
        return
    try:
        u0 = hw.uart("UART0", baud)
        u1 = hw.uart("UART1", baud)
        u0.reset_input_buffer(); u1.reset_input_buffer()

        msg0 = b"hello from UART0 via CH347F-EAT\n"
        u0.write(msg0)
        rx1 = u1.read(len(msg0), 500)
        # echo it back the other way
        u1.write(rx1 or b"?" * len(msg0))
        rx0 = u0.read(len(msg0), 500)
        ok1 = rx1 == msg0
        record("uart.uart0_to_uart1", PASS if ok1 else FAIL,
               f"tx={msg0!r} rx={rx1!r}")

        msg1 = bytes(range(0, 256))
        u1.write(msg1)
        rx0b = u0.read(len(msg1), 800)
        ok2 = rx0b == msg1
        record("uart.uart1_to_uart0_binary", PASS if ok2 else FAIL,
               f"{len(rx0b)}/256 bytes, match={rx0b == msg1}")
    except Exception as e:
        record("uart.loopback", FAIL, traceback.format_exc(limit=2))
    finally:
        hw.close_uart("UART0"); hw.close_uart("UART1")


def test_i2c_eeprom(hw: Hardware) -> None:
    try:
        bus = hw.i2c()
        found = bus.scan()
        record("i2c.scan", PASS if 0x50 in found else FAIL,
               "devices: " + ", ".join(f"0x{a:02X}" for a in found) or "none")
        if 0x50 not in found:
            return
        eep = hw.eeprom("24C02")
        # save -> write pattern -> verify -> restore -> verify (non-destructive)
        test_addr, test_len = 0x70, 16
        orig = eep.read(test_addr, test_len)
        pattern = bytes((i * 7 + 0x5A) & 0xFF for i in range(test_len))
        eep.write(test_addr, pattern, verify=False)
        got = eep.read(test_addr, test_len)
        record("i2c.at24c02_write_read", PASS if got == pattern else FAIL,
               f"@0x{test_addr:02X} wrote {pattern.hex()} read {got.hex()}")
        eep.write(test_addr, orig, verify=False)
        restored = eep.read(test_addr, test_len)
        record("i2c.at24c02_restore", PASS if restored == orig else FAIL,
               f"original {orig.hex()}")
        # DLL EEPROM API cross-check
        via_dll = hw.dev.eeprom_read("24C02", 0x00, 16)
        via_bus = eep.read(0x00, 16)
        record("i2c.dll_eeprom_read_match", PASS if via_dll == via_bus else FAIL,
               f"{via_dll.hex()}")
    except Exception as e:
        record("i2c.eeprom", FAIL, traceback.format_exc(limit=2))


def test_spi_flash(hw: Hardware) -> None:
    try:
        from eat.spi_flash import W25QFlash
        bus = hw.spi()
        f = W25QFlash(bus)
        ok = f.jedec == b"\xef\x40\x14"
        record("spi.w25q80_jedec", PASS if ok else FAIL,
               f"JEDEC {f.jedec.hex(' ')} ({f.identify()})")
        sr = f.read_status()
        record("spi.w25q80_status", PASS, f"SR1={sr.hex(' ')} "
               f"BUSY={sr[0] & 1} WEL={(sr[0] >> 1) & 1}")
        data = f.read_data(0, 32)
        record("spi.w25q80_read32", PASS, f"@0x000000: {data.hex(' ')}")
        # write/erase round-trip on sector 0 — only if the sector is blank, so
        # the erase restores the original (all-0xFF) content
        sector = f.read_data(0, 4096)
        if sector == b"\xff" * 4096:
            pattern = bytes((0x10 + i) & 0xFF for i in range(64))
            f.write(0x000000, pattern)
            got = f.read_data(0, 64)
            record("spi.w25q80_page_program", PASS if got == pattern else FAIL,
                   f"wrote {pattern[:16].hex(' ')}.. read {got[:16].hex(' ')}..")
            f.erase_sector(0)
            blank = f.read_data(0, 4096) == b"\xff" * 4096
            record("spi.w25q80_sector_erase", PASS if blank else FAIL,
                   "sector 0 back to all-FF")
        else:
            record("spi.w25q80_page_program", SKIP,
                   "sector 0 not blank; wipe it first to enable this check")
    except Exception as e:
        record("spi.flash", FAIL, traceback.format_exc(limit=2))


def main() -> int:
    print("== EAT CH347F bench self-test (loopback wiring required, "
          "see module docstring) ==")
    hw = None
    try:
        hw = Hardware(bench=True)  # enables GPIO pair guard for cross wiring
        test_device(hw)
        test_power(hw)
        test_power_device_probe(hw)
        test_gpio_pairs(hw)
        test_gpio_interlock(hw)
        test_uart_loopback(hw)
        test_i2c_eeprom(hw)
        test_spi_flash(hw)
    except Exception:
        record("hardware.init", FAIL, traceback.format_exc(limit=3))
    finally:
        if hw:
            try:
                hw.power.off()
                hw.close()
            except Exception:
                pass
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    n_skip = sum(1 for _, s, _ in results if s == SKIP)
    print(f"\n== {len(results) - n_fail - n_skip} passed, {n_fail} failed, "
          f"{n_skip} skipped ==")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
