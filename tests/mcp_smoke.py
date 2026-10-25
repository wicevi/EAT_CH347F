"""Smoke-test the MCP server over stdio like a real client would.
Covers: tool listing, device info, doctor, GPIO, I2C, EEPROM, UART basics,
background monitor (tail/grep/wait_for), script DSL, target profiles, power."""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FAILS = []


async def main() -> int:
    params = StdioServerParameters(command=sys.executable,
                                   args=[r"D:\EAT_CH347F\eat_mcp_server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"tools ({len(names)})")
            assert len(names) >= 30, f"expected >=30 tools, got {len(names)}"

            async def call(name, args=None, expect_ok=True):
                r = await session.call_tool(name, args or {})
                text = r.content[0].text if r.content else ""
                data = None
                try:
                    import json
                    data = json.loads(text)
                except Exception:
                    pass
                ok = bool(data.get("ok", True)) if isinstance(data, dict) else True
                status = "ok" if ok == expect_ok else "UNEXPECTED"
                if ok != expect_ok:
                    FAILS.append(name)
                print(f"[{status}] {name} :: {text[:180].replace(chr(10), ' ')}")
                return data

            await call("eat_device_info")
            await call("eat_doctor")
            await call("eat_gpio_read_all")
            await call("eat_i2c_scan")

            # I2C/SPI rate & mode configuration
            await call("eat_i2c_config", {"speed_khz": 400})
            await call("eat_i2c_scan")
            await call("eat_eeprom_read", {"addr": 0, "length": 8})
            await call("eat_i2c_config", {"speed_khz": 100})
            await call("eat_spi_config", {"mode": 3, "freq_hz": 750_000})
            await call("eat_spi_jedec")
            await call("eat_spi_config", {"mode": 0, "freq_hz": 1_875_000})
            await call("eat_eeprom_read", {"addr": 0, "length": 8})
            await call("eat_uart_list")
            await call("eat_target_profiles")

            # monitor: start on UART1, send from UART0 (crossed bench), verify
            await call("eat_uart_monitor_start", {"channel": "UART1"})
            await call("eat_uart_send", {"channel": "UART0",
                                         "data": "BOOT OK token=42"})
            await asyncio.sleep(0.4)
            await call("eat_uart_monitor_tail", {"channel": "UART1", "lines": 5})
            await call("eat_uart_monitor_grep", {"channel": "UART1",
                                                 "pattern": r"token=\d+"})
            await call("eat_uart_send", {"channel": "UART0",
                                         "data": "ALL TESTS PASSED"})
            await call("eat_uart_wait_for",
                       {"channel": "UART1", "pattern": "ALL TESTS PASSED",
                        "timeout_ms": 2000, "monitor": True})
            await call("eat_uart_monitor_status")
            await call("eat_uart_monitor_stop", {"channel": "UART1"})

            # script DSL: send on UART0, expect on UART1 (crossed bench)
            await call("eat_uart_script", {
                "channel": "UART0", "listen_channel": "UART1",
                "steps": [
                    {"send": "hello-script"},
                    {"expect": "hello-script", "timeout_ms": 1500},
                    {"delay_ms": 10},
                    {"send": "done"},
                ]})
            # script with failing expect should report ok:false
            await call("eat_uart_script", {
                "channel": "UART0", "listen_channel": "UART1",
                "steps": [{"send": "x"}, {"expect": "never-appears",
                                          "timeout_ms": 300}]},
                expect_ok=False)

            # gpio via profile-based reset (uses pair -> interlock path)
            await call("eat_target_reset", {"profile": "stm32-uart0"})

            # power + policy note
            await call("eat_power_set", {"action": "on"})
            await call("eat_power_status")
            await call("eat_power_set", {"action": "off"})

    print(f"\n{'ALL OK' if not FAILS else 'FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
