---
name: eat-embedded-tool
description: Control real embedded hardware through the EAT CH347F tool board via the eat MCP tools - UART console/monitor, GPIO for reset/boot/buttons, I2C and SPI peripherals, NOR flash programming, target power. Use when the task involves talking to a physical target board, flashing firmware data, driving control pins, or debugging over serial.
---

# EAT 嵌入式工具使用技能（CH347F 工具板）

通过 `eat` MCP 工具集（`eat_*`）控制目标硬件：双串口、GPIO、I2C、SPI、NOR Flash、目标电源。
完整工具参考：`docs/MCP_TOOLS.md`。所有工具返回 `{"ok": bool, ...}`，失败带 `error` + `hint`。

## 上手

```
eat_doctor          # 环境/连接体检（驱动、COM 口、总线）
eat_device_info     # 设备信息 + UART↔COM 口映射
```

## 串口（调试口 / 日志 / 烧录口）

```
eat_uart_config(channel, baud, parity...)     # 打开并配置，如 8E1
eat_uart_send(channel, data, hex_data?)       # 发文本或 hex
eat_uart_exchange(channel, "AT")              # 发送并取应答（命令式设备）
```

**持续观察目标输出**（推荐，不占上下文）：
```
eat_uart_monitor_start(channel)               # 后台捕获 → 环形缓冲 + 时间戳日志文件
eat_target_reset(...)                         # 让目标重启，完整抓启动日志
eat_uart_monitor_tail(channel, lines=50)      # 看尾部
eat_uart_monitor_grep(channel, pattern="ERROR|Fault|PASSED")
eat_uart_wait_for(channel, pattern="READY", timeout_ms=10000)   # 阻塞等关键输出
eat_uart_monitor_stop(channel)
```

**命令序列**（boot 菜单/AT/握手）：
```
eat_uart_script(channel, steps=[{"send":"AT","newline":true},{"expect":"OK","timeout_ms":1000},{"delay_ms":100}])
# 应答在不同通道时加 listen_channel 参数
```

## GPIO（复位 / BOOT / 按键 / 通用控制）

引脚位置：UART0 连接器 GPIO2(pin1)/GPIO3(pin2)，UART1 连接器 GPIO5(pin1)/GPIO6(pin2)。
GPIO0=电源使能保留，GPIO1 未引出，GPIO4/7=SWD 复用。

```
eat_gpio_set(pin, mode="out", level=1)        # 输出高/低
eat_gpio_set(pin, mode="pulse", level=0, pulse_ms=100)   # 复位脉冲
eat_gpio_read(pin) / eat_gpio_read_all()      # 读输入
```

**目标控制**（支持模板，`eat_target_profiles` 列出，可在 config/targets/ 自定义）：
```
eat_target_reset(profile="stm32-uart0")                    # 复位脉冲
eat_target_enter_bootloader(profile="esp32-uart0")          # 拉 BOOT→复位→释放
eat_target_power_cycle_reset()                              # 下电复位（VOUT 供电时）
```

## I2C

```
eat_i2c_config(speed_khz=400)                 # 速率 20k~1MHz（默认 100k）
eat_i2c_scan()                                # 扫描设备地址
eat_i2c_read(addr7, reg, length) / eat_i2c_write(addr7, reg, hex_data)   # 寄存器型外设
eat_eeprom_read/write(addr, hex_data)         # 24Cxx EEPROM（自动分页+校验）
```

## SPI

```
eat_spi_config(mode=0, freq_hz=1875000)       # 模式 0-3，1kHz~60MHz
eat_spi_transfer(hex_out, rx_len)             # 原始全双工（自定义 SPI 外设）
eat_spi_flash_read(addr, length)              # W25Q 系列 NOR flash
eat_spi_flash_write(addr, hex_data, erase_sector?)   # 页编程+自动校验
eat_spi_flash_erase(addr | whole_chip)        # 破坏性，先核对地址
```

## 电源（VOUT 3.3V）

```
eat_power_set(action="on" | "off" | "cycle")
```

## 注意事项

- 破坏性操作（flash/EEPROM 写、擦除）先核对地址。
- JTAG 用 GPIO3/5/6、SWD 用 GPIO4/7，与 GPIO 用途互斥。
- 安全策略 `EAT_MCP_POLICY=full|no_write|read_only` 可限制破坏性操作。
- 当前板版本 VOUT 开关电路有已知硬件缺陷，`eat_power_*` 可调用但电源轨可能不实际切换（修版后自动恢复有效）。
- 长引线时 SPI 速率建议控制在几 MHz 内（30MHz 短线实测稳定）。

## 排障

- 任何 `ok:false` 先看 `hint`；设备类错误服务端自动重开，重试一次即可。
- 驱动问题（COM 口消失/厂商接口打不开）：`python tools/setup_drivers.py` 先检查，缺什么装什么（需管理员）。
- 串口收不到：核对波特率/校验位（`eat_uart_config`）；确认监视器已 start。
- 未知 profile：`eat_target_profiles` 列表，或直接用显式 GPIO 参数。
