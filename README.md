# EAT — Embedded Agent Tool (CH347F)

让 AI 编码工具（Claude Code / ZCode / Codex / Cursor …）通过 **MCP** 直接操作嵌入式目标硬件：
烧录、串口调试、复位/进 Bootloader、下电复位、I2C/SPI 外设读写，一条龙自主开发闭环。

- 硬件：Embedded_Agent_Tool V1.0（WCH **CH347F** USB2.0 高速五合一：双串口 + I2C + SPI + JTAG/SWD + 8×GPIO + 可控 VOUT）
- 硬件详情：[docs/HARDWARE.md](docs/HARDWARE.md)（引脚/连接器/电源/复用权威文档）、[AGENTS.md](AGENTS.md)（Agent 必读）
- 平台：Windows（CH343SER 串口驱动 + CH341PAR 厂商驱动，DLL: `CH347DLLA64.DLL`）

## 目录结构

```
eat_mcp_server.py        MCP server（stdio，35 个 eat_* 工具）
src/eat/
  ch347_api.py           CH347DLL ctypes 绑定（GPIO/I2C/SPI/JTAG/EEPROM）
  board.py               板级事实 + 台架接线 + UART COM 自动识别
  gpio_safe.py           ★ 安全 GPIO（对脚互锁，防短路）
  hardware.py            共享硬件上下文（资源生命周期）
  uart.py                UART0/1（pyserial + 注册表自动映射 COM 口）
  uart_monitor.py        ★ 后台串口监视器（环形缓冲+日志文件+tail/grep/wait_for）
  i2c_bus.py             I2C 主机 + AT24Cxx 驱动
  spi_flash.py           SPI + W25Qxx NOR flash 驱动
  power.py               VOUT 电源控制（GPIO0）
  targets.py             目标板模板加载（config/targets/*.json）
config/targets/          目标板模板（stm32/esp32/ch32，可自行添加）
skills/eat-embedded-tool Agent Skill（操作规程，tools/install_skill.py 可安装到各客户端）
tests/
  bench_selftest.py      硬件自检 18 项（python tests/bench_selftest.py）
  benchmark.py           性能基准（UART/I2C/SPI 多速率吞吐 + 完整性）
  mcp_smoke.py           MCP 协议冒烟测试（37 工具全链路）
  diag_wiring.py         接线核查（GPIO 连接矩阵 + COM 口映射）
  vout_blink.py          VOUT 开关观察脚本（配合 OUT1 LED）
logs/                    串口监视器日志（带时间戳，自动生成）
docs/                    原始资料 + 文档（见 docs/README.md、docs/MCP_TOOLS.md）
```

## 快速开始

```bash
# 0) 驱动（先检查，缺了再装；安装器需管理员）
python tools/setup_drivers.py              # 检查 CH343SER/CH341PAR/DLL 状态
python tools/setup_drivers.py --install all   # 仅对缺失项弹出对应安装器

# 1) 依赖 + 验证
pip install pyserial mcp
python tests/bench_selftest.py    # 硬件自检（需回环接线，见下）
python tests/mcp_smoke.py         # MCP 冒烟（列工具+实测调用）
python eat_mcp_server.py          # 以 stdio 启动 MCP server
```

## 接入 AI 客户端（MCP 配置）

Claude Code / ZCode / Cursor 通用 JSON（放入各自 mcpServers 配置）：

```json
{
  "mcpServers": {
    "eat": {
      "command": "python",
      "args": ["D:\\EAT_CH347F\\eat_mcp_server.py"]
    }
  }
}
```

Claude Code 亦可用命令行：`claude mcp add eat -- python D:\EAT_CH347F\eat_mcp_server.py`

## 工具面（v0.3，37 个；完整参考见 [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)）

| 类别 | 工具 |
|---|---|
| 设备/诊断 | `eat_device_info` `eat_doctor` `eat_bench_selftest` |
| 电源 | `eat_power_set(on/off/cycle)` `eat_power_status` |
| GPIO | `eat_gpio_read_all` `eat_gpio_read` `eat_gpio_set` `eat_gpio_write` |
| UART 基础 | `eat_uart_list` `eat_uart_config(baud/校验/停止位)` `eat_uart_send` `eat_uart_receive` `eat_uart_exchange` |
| UART 监视器 | `eat_uart_monitor_start/stop/status` `eat_uart_monitor_tail` `eat_uart_monitor_grep` `eat_uart_wait_for` |
| UART 脚本 | `eat_uart_script`（send/delay/expect DSL） |
| I2C | `eat_i2c_config(速率20k~1MHz/推挽/延展)` `eat_i2c_scan` `eat_i2c_read/write` `eat_eeprom_read/write` |
| SPI/Flash | `eat_spi_config(模式0-3/1kHz~60MHz)` `eat_spi_jedec` `eat_spi_transfer` `eat_spi_flash_read/write/erase` |
| 目标控制 | `eat_target_profiles` `eat_target_reset` `eat_target_enter_bootloader` `eat_target_power_cycle_reset` |

- **统一返回契约**：所有工具返回 `{"ok": bool, ...}`，失败带 `error` + `hint`。
- **安全策略**：`EAT_MCP_POLICY=full|no_write|read_only`（分级管控破坏性操作）。
- **监视器日志**：`logs/UARTx_*.log` 带时间戳，tail/grep 避免长输出刷爆上下文。
- **Agent Skill**：`skills/eat-embedded-tool/SKILL.md`（操作规程），`python tools/install_skill.py` 安装到 Claude/Codex/ZCode/Cursor。

## 台架验证状态（2026-10-18，自检 18/18 + MCP 冒烟 35 工具 ALL OK）

| 项目 | 结果 |
|---|---|
| 设备/驱动/DLL | ✅ CH347F 高速枚举，fw2.0 drv2.5 dll2.2 |
| VOUT 控制 API | ✅（物理轨待 SW1/供电确认，见 AGENTS.md 待办） |
| GPIO 对脚 GPIO2↔GPIO5、GPIO3↔GPIO6 | ✅ 双向跟随 + 互锁保护有效 |
| UART0↔UART1 交叉环回 | ✅ 文本+256 字节二进制，115200 |
| I2C AT24C02 | ✅ 扫描/读/写/恢复/DLL 双通道一致（0x50，0x58 为 A2 悬空幻影地址） |
| SPI W25Q80 | ✅ JEDEC `EF 40 14`、状态读、页编程+校验、扇区擦除恢复（模块 MOSI/MISO 与连接器交叉，读须走全双工路径） |
| MCP 全链路 | ✅ 35 工具注册，doctor/GPIO/I2C/EEPROM/UART/监视器 tail·grep·wait_for/脚本 DSL/模板复位/电源 全部实调通过 |

> ⚠️ VOUT 防盗灌电路已知硬件缺陷（待改版）：`eat_power_*` API 正常，但电源轨可能不实际切换。

## 性能实测（2026-10-18，`tests/benchmark.py`，回环接线，26 项全部完整性校验通过）

| 接口 | 配置 | 吞吐 | 说明 |
|---|---|---|---|
| UART | 115200 ~ 4M baud | 11.5 KB/s ~ 390 KB/s | 64KB 环回，各档均达线路理论速率、零丢包 |
| I2C | 20k ~ 1MHz 七档 | 2.1 ~ 117 KB/s | AT24C02 256B 整读，七档全过（含 750k/1M 超规格也能跑） |
| SPI 读 | 468k ~ 30MHz | 56 KB/s ~ 1.93 MB/s | W25Q80 64KB 读，杜邦线 30MHz 仍稳定；1KB 帧 + USB 开销约占带宽一半 |
| SPI 写 | 1.875MHz | 46 KB/s（含校验） | 4KB 页编程 + busy 等待 + 回读校验 |
| SPI 模式 | mode 0-3 | — | 0/3 正确识别 JEDEC；1/2 错误 ID（符合 W25Q 规格，验证配置生效） |
| GPIO | 单次 USB 往返 | 翻转 4.3 kHz / 读 7.8k 次/s | 位带操作上限，由 USB 往返延迟决定 |

## 注意事项

- **打开串口默认释放 DTR/RTS**：CH347F 将 DTR0 复用为 GPIO2（UART0 pin1，常接目标 BOOT 脚）、
  RTS1 复用为 SDA（I2C 总线）。pyserial 默认断言 DTR/RTS 会把这些网络拉低（目标卡在
  bootloader / I2C 失效）；本工具默认释放，需要 DTR/RTS 复位时序时在 `eat_uart_config`
  显式指定。**用 pyserial 直接操作 COM 口的代码也请注意**：`serial.Serial('COMx')` 前先
  `s = serial.Serial(); s.port=...; s.dtr=False; s.rts=False; s.open()`。
- 破坏性操作（flash/EEPROM 写入、擦除）注意核对地址；当前台架 SPI flash 为 W25Q80（1MB）。
- GPIO0 保留给 VOUT_EN（电源控制），GPIO1 板上未引出；GPIO4/7 与 SWD 复用。
- GPIO 默认完全独立；仅当两脚被物理短接的接线下才需要互锁保护（`EAT_GPIO_PAIRS`，见 AGENTS.md）。

## 回环自检接线要求（`tests/bench_selftest.py`）

完整自检需要以下对接（细节见脚本头部注释）：

| 连接 | 接法 |
|---|---|
| UART0 ↔ UART1 | 转接线对接：TX/RX 交叉（pin3↔pin4），其余按 pin 顺序一一对应（1↔1、2↔2、5↔5 GND、6↔6 VOUT） |
| IIC1 | AT24C02 模块（SDA/SCL/GND/VOUT 对应） |
| SPI1 | W25Q80 模块（VOUT/GND/MOSI/MISO/CLK/CS 对应） |
| SW1 | 断开位（软件电源控制） |

> 连接器对应：UART0 pin1=GPIO2/pin2=GPIO3，UART1 pin1=GPIO5/pin2=GPIO6，直连后即
> GPIO2↔GPIO5、GPIO3↔GPIO6（实测一致）。自检以 bench 模式运行（按该映射启用对脚互锁
> 防短路）；日常工具使用不涉及互锁。
