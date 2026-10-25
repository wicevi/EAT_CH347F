# EAT MCP 工具参考手册（v0.3，37 个工具）

> 服务端：`python eat_mcp_server.py`（stdio）。本文是 AI 客户端（Claude Code/ZCode/Cursor/Codex）使用本工具的完整参考。
> 接入配置见 [README.md](../README.md)；硬件事实见 [HARDWARE.md](HARDWARE.md)。

## 通用约定

- **统一返回契约**：每个工具返回 JSON `{"ok": bool, ...字段}`，失败时含 `error` 与可操作的 `hint`。判断成败只看 `ok`。
- **安全策略**（环境变量 `EAT_MCP_POLICY`，默认 `full`）：
  - `full`：全部可用
  - `no_write`：禁止持久写入/擦除（flash/EEPROM 写、自检），允许 GPIO/电源/串口操作
  - `read_only`：只允许纯读取（信息/扫描/读/tail/grep）
  - 每个工具文档末尾标注其级别 `[policy level: read|control|write]`
- **GPIO 引脚位置**：UART0 连接器 GPIO2(pin1)/GPIO3(pin2)，UART1 连接器 GPIO5(pin1)/GPIO6(pin2)。
- **已知硬件限制**：本版 VOUT 开关电路有缺陷（待改版），`eat_power_*` API 正常但电源轨可能不实际切换。

## 工具分组

### 1. 设备与诊断（read）

| 工具 | 说明 |
|---|---|
| `eat_device_info` | USB 设备信息（芯片/固件/驱动版本）、COM 口映射、GPIO 引脚位置、当前策略 |
| `eat_doctor` | 一键体检：python/pyserial/DLL/设备/COM/I2C/SPI/日志目录，返回逐项 checks |
| `eat_bench_selftest` | 完整回环自检（18 项，**需自检接线**：UART0↔UART1 交叉对接 + AT24C02 + W25Q80，见 README/脚本头部；运行期间临时启用对脚互锁），`[write]` |

### 2. 电源（VOUT 目标供电）

| 工具 | 参数 | 说明 |
|---|---|---|
| `eat_power_set` | action: on/off/cycle, off_ms | `[control]` cycle = 下电复位 |
| `eat_power_status` | — | `[read]` 读 VOUT_EN 驱动状态 |

### 3. GPIO

| 工具 | 参数 | 说明 |
|---|---|---|
| `eat_gpio_read_all` | — | `[read]` 全部 GPIO 方向+电平+引脚/位置元数据 |
| `eat_gpio_read` | pin | `[read]` 读单脚电平 |
| `eat_gpio_set` | pin, mode: in/out/pulse, level, pulse_ms | `[control]` 配置（pulse 自动回归闲置电平） |
| `eat_gpio_write` | pin, level | `[control]` 修改已输出脚电平 |

可用 GPIO：2/3（UART0 侧）、5/6（UART1 侧）、4/7（SWD 引脚，与 SWD 冲突）；GPIO0=电源保留，GPIO1 未引出。
GPIO 相互独立；仅回环自检（`eat_bench_selftest`，需专用接线）内部临时启用对脚互锁保护。

### 4. UART 基础

| 工具 | 关键参数 | 说明 |
|---|---|---|
| `eat_uart_list` | — | `[read]` UART0/1 → COM 映射 |
| `eat_uart_config` | channel, baud, databits, parity, stopbits, dtr?, rts? | `[control]` 打开/配置（如 STM32 bootloader 需 8E1）。**打开串口默认释放 DTR/RTS**——CH347F 将 DTR0 复用为 GPIO2（UART0 pin1，常见 BOOT 脚）、RTS1 复用为 SDA（I2C 总线），默认断言会拉低这些网络；仅 DTR/RTS 复位时序流程才显式传 `dtr=True/rts=True` |
| `eat_uart_send` | channel, data, hex_data, newline | `[control]` 发文本或 hex |
| `eat_uart_receive` | channel, timeout_ms, max_bytes | `[read]` 一次性读到空闲 |
| `eat_uart_exchange` | channel, data, timeout_ms | `[control]` 发送并捕获应答（AT 式请求/响应） |

### 5. UART 后台监视器（推荐用于持续观察）

| 工具 | 关键参数 | 说明 |
|---|---|---|
| `eat_uart_monitor_start` | channel, baud, ring_kb, truncate | `[control]` 启动后台监视线程：字节进环形缓冲（默认 256KB）+ 带时间戳日志文件（`logs/UARTx_时间戳.log`） |
| `eat_uart_monitor_stop` | channel | `[control]` 停止（日志保留） |
| `eat_uart_monitor_status` | channel? | `[read]` 缓冲/总量/日志路径/运行状态（不传 channel 返回全部） |
| `eat_uart_monitor_tail` | channel, lines | `[read]` 取最后 N 行 |
| `eat_uart_monitor_grep` | channel, pattern, last_n_lines, context | `[read]` 正则搜索缓冲（找启动横幅/错误/pass 令牌） |
| `eat_uart_wait_for` | channel, pattern, timeout_ms, monitor | `[read]` 阻塞等待正则出现（测试判定利器）；monitor=true 走后台缓冲 |

### 6. UART 脚本（send/delay/expect DSL）

`eat_uart_script(channel, steps, listen_channel?)` `[control]`

```json
steps = [
  {"send": "AT", "newline": true},
  {"expect": "OK", "timeout_ms": 1000},
  {"delay_ms": 100},
  {"send": "01 A0 5F", "hex": true}
]
```
逐步返回 trace；expect 失败默认中止（步骤加 `"on_fail":"continue"` 可继续）。目标应答在不同通道时用 `listen_channel`。适用于引导菜单、AT 命令、bootloader 握手。

### 7. I2C / EEPROM

| 工具 | 关键参数 | 说明 |
|---|---|---|
| `eat_i2c_config` | speed_khz, push_pull, stretch | `[control]` 配置 I2C 主机：速率 20/50/100/200/400/750/1000 kHz（默认100），推挽/开漏，时钟延展；参数可选，只改给出的项；对后续所有 i2c/eeprom 调用生效 |
| `eat_i2c_scan` | — | `[read]` 扫描 0x08-0x77，返回应答的设备地址 |
| `eat_i2c_read` | addr7, reg, length | `[read]` 读寄存器 |
| `eat_i2c_write` | addr7, reg, hex_data | `[write]` 写寄存器 |
| `eat_eeprom_read` | addr, length, model | `[read]` 读 24Cxx |
| `eat_eeprom_write` | addr, hex_data, model | `[write]` 写 24Cxx（自动分页+校验） |

> 注：`push_pull`/`stretch` 属于 DLL 可选特性，当前固件/DLL 版本 `SetDriverMode` 不支持——
> 返回值里 `driver_mode_applied`/`stretch_applied` 会如实标注是否生效。

### 8. SPI / W25Q Flash

| 工具 | 关键参数 | 说明 |
|---|---|---|
| `eat_spi_config` | mode, freq_hz | `[control]` 配置 SPI 主机：模式 0-3、频率 1kHz~60MHz（就近取支持档，默认模式0/1.875MHz）；对后续所有 spi/flash 调用生效 |
| `eat_spi_jedec` | — | `[read]` 读 JEDEC ID（W25Q80 = `EF 40 14`） |
| `eat_spi_transfer` | hex_out, rx_len, mode?, freq_hz? | `[control]` 原始全双工传输（**读必须走此路径**）；mode/freq_hz 可单次覆盖当前配置 |
| `eat_spi_flash_read` | addr, length | `[read]` 读存储（0x03） |
| `eat_spi_flash_write` | addr, hex_data, erase_sector | `[write]` 页编程+校验；erase_sector=true 先擦含该地址的 4K 扇区 |
| `eat_spi_flash_erase` | addr 或 whole_chip | `[write]` 擦除（**破坏性**） |

> 实测：模式3/750kHz 下 W25Q80 通信正常；杜邦线较长时建议速率控制在几 MHz 内。

### 9. 目标板控制（复位 / Bootloader / 模板）

| 工具 | 关键参数 | 说明 |
|---|---|---|
| `eat_target_profiles` | — | `[read]` 列出 `config/targets/*.json` 模板（stm32/esp32/ch32，可自行添加） |
| `eat_target_reset` | profile 或 reset_gpio+active+pulse_ms | `[control]` 复位脉冲 |
| `eat_target_enter_bootloader` | profile 或 boot_gpio+reset_gpio+… | `[control]` 拉 BOOT → 复位 → （可选）释放 |
| `eat_target_power_cycle_reset` | off_ms | `[control]` 下电复位（受 VOUT 硬件问题影响暂不可靠） |

模板字段：`name/description/uart/baud/reset_gpio/reset_active/reset_pulse_ms/boot_gpio/boot_level/bootloader_baud/bootloader_format/notes`。

## 推荐工作流（Agent 秘诀）

**编译-烧录-观察闭环**（参考 esp32-ai-loop / platformio.mcp 模式）：
1. `eat_doctor` → 确认环境与连接
2. `eat_uart_monitor_start`（目标串口）→ 后台持续捕获
3. 构建/烧录固件（外部工具或 SWD/ISP）
4. `eat_target_reset`（或 profile）→ 让目标完整重启
5. `eat_uart_monitor_grep`（boot banner / fault）或 `eat_uart_wait_for`（pass 令牌如 `ALL TESTS PASSED`）→ 得出机器可判定的成败
6. 失败 → `eat_uart_monitor_tail` 取上下文 → 修代码 → 回到 3

**Flash 数据烧录**：`eat_spi_flash_erase(addr)` → `eat_spi_flash_write(addr, hex)`（自动校验）→ `eat_spi_flash_read` 复核。
**AT/命令式设备**：`eat_uart_script` 一步跑完握手序列。
**长输出**：永远用 monitor tail/grep，不要把原始流拉进上下文；完整日志在 `logs/` 下带时间戳的文件里。

## 设计模式来源（致谢）

- 后台监视器 + tail/grep + 日志文件：esp32-ai-loop-mcp-server、platformio.mcp
- send/delay/expect 脚本 DSL：serial-mcp-server
- 统一 ok/summary 返回契约 + 策略层（full/no_write/read_only）+ doctor：platformio.mcp
- pass-token 机器判定闭环：STM32_AutoDebug_Universal_Kit
- Skill 分发模式：embedded-debugger-mcp / STM32_AutoDebug_Universal_Kit
