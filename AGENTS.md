# AGENTS.md — EAT_CH347F 项目必读（Agent/开发者必读）

本项目是**嵌入式 AI 开发工具（Embedded Agent Tool）**：基于 WCH CH347F 的 USB 多协议工具板，
目标是提供一套 **MCP server**，让 AI 编码工具（Claude Code / Codex / ZCode / Cursor 等）能够
**自主完成嵌入式产品的烧录、调试、测试闭环**。

**当前状态（2026-10-18）**：MCP server **v0.3**（37 个工具）实机验证：自检 **18/18**、MCP 冒烟 **ALL OK**
（含后台串口监视器、send/expect 脚本 DSL、doctor、目标模板、安全策略层、I2C/SPI 速率与模式配置）。
工具完整参考见 [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)；Agent 操作规程见 `skills/eat-embedded-tool/SKILL.md`。

**v0.2 借鉴的开源模式**（调研：embedded-debugger-mcp / serial-mcp-server / esp32-ai-loop-mcp-server /
platformio.mcp / STM32_AutoDebug_Universal_Kit）：统一 ok/summary 返回契约、EAT_MCP_POLICY 策略层
（full/no_write/read_only）、监视器环形缓冲+日志文件+tail/grep、pass-token 机器判定闭环、skill 分发。

## 当前台架接线（实测确认，软件安全逻辑依赖这些事实）

- 本机插着 1 块 EAT 板：COM16=UART0(MI_00)、COM17=UART1(MI_02)、MI_04=厂商接口（CH341PAR 驱动，DLL=`C:\Windows\System32\CH347DLLA64.DLL`）。
- **UART0↔UART1 端子对接，TX/RX 交叉**：UART0 发送会在 UART1 收到，反之亦然。
- **UART0↔UART1 对接（仅回环自检接线）**：转接线只有 TX/RX 交叉（pin3↔pin4），**其余按 pin 顺序
  一一对应**（用户确认 + 原理图复核）。连接器对应 UART0 pin1=GPIO2/pin2=GPIO3、
  UART1 pin1=GPIO5/pin2=GPIO6，直连即 `GPIO2↔GPIO5`、`GPIO3↔GPIO6`（与实测矩阵一致）。
  ⚠ 历史教训：首版 HARDWARE.md §3 芯片表把 pin24/25 的"连接去向"列写反（传导到 board.py），
  一度误推出"DLL bit5/6 与头文件相反"——实际是**原理图解析错误**，已修正；解析结论务必
  与用户/实测双重核对。
  **互锁只在 bench 模式生效**（`Hardware(bench=True)`，即自检脚本/MCP `eat_bench_selftest`）；
  **日常工具使用无互锁、GPIO 完全独立**。自定义短接接线需保护时设 `EAT_GPIO_PAIRS=2:5,3:6`。
  接线说明：自检脚本头部注释 + README"回环自检接线要求"。
- I2C 总线挂 AT24C02C（地址 0x50；0x58 是 A2 脚悬空造成的幻影 ACK）。
- SPI 总线挂 W25Q80（JEDEC `EF 40 14` 已验证；模块 MOSI/MISO 与 SPI1 连接器交叉，2026-10-18 用户调换后打通）。

## 实测结论（勿重复推导）

1. DLL `CH347GPIO_Get/Set` 的 dir/data 按 bit0-7 = GPIO0-7；CH347F 上电默认全输入。
   bit↔芯片引脚↔连接器位置与头文件表 4-7 一致（bit5=pin24=UART1 pin1、bit6=pin25=UART1 pin2，
   已由直连接线 + 实测对脚矩阵双向印证）。
2. GPIO0(VOUT_EN) 置输入时经 R2/R3(上拉 VIO)/R4(下拉 GND) 分压约 2.2V，读数为 1——
   因此 `Hardware.__init__` 会把 GPIO0 显式驱动为低（VOUT off 确定态），`all_inputs()` 跳过保留脚。
3. **SPI 读必须走全双工路径**（`CH347SPI_WriteRead` 帧式，封装为 `spi_transfer`/`SpiBus.transfer`）：
   台架上端点式 `CH347SPI_Read`（先发命令再读）恒返回 0xFF（与模块 MOSI/MISO 交叉接法有关）。
   写路径 `CH347SPI_Write` 正常（页编程/擦除已验证）。`CH347SPI_Init` 后需
   `CH347SPI_SetChipSelect(idx,0x0001,0,0,0,0)` 启用 CS1（已在 `spi_init` 流程内）。
4. DLL 上报 CH347F 的 `ChipMode=0`（非手册注释的 4）；判断芯片用 `CH347GetChipType()==2`。
5. 交叉串口台架下，发数据前需先打开对端 COM 口，否则在途字节会被 VCP 驱动丢弃
   （`Hardware.uart()` 已自动双开）。
6. mcp python SDK 2.x 用 `MCPServer`（非 FastMCP），server 已做兼容 import。
7. 给 MCP 工具函数包装饰器时**必须 `functools.wraps(fn)`**，否则 SDK 按 `*args/**kwargs`
   推断 schema，所有调用报 "rejected arguments: ['args','kwargs']"（v0.2 踩过）。
8. 交叉台架的"同通道自发自收"不通：`eat_uart_script` 需 `listen_channel` 指定对端通道。
9. 速率/模式配置（v0.3）：I2C 支持 20k~1MHz 七档（`eat_i2c_config`），SPI 支持模式 0-3、
   1kHz~60MHz 就近取档（`eat_spi_config`，实测模式3/750kHz 正常）。DLL 的
   `CH347I2C_SetDriverMode` 在当前固件/DLL 2.2 上**不支持**（调用返回失败），已在 I2CBus
   里降级为尽力而为并在返回值标注 `driver_mode_applied`；`SetStretch` 正常。

## 待办 / 待用户确认

- [x] ~~W25Q80 无响应~~ → 用户调换 SPI 输入输出后打通（2026-10-18），读写擦全验证。
- [ ] **硬件待改（用户确认 2026-10-18）：VOUT 防盗灌电路（Q1/Q2 背靠背 PMOS 负载开关）有问题，
      后续改良**。当前现象：VOUT_EN 0/1 时 VOUT 似恒为开（EEPROM/flash 全程在线、OUT1 灯判别待做）。
      软件侧（GPIO0/VOUT_EN API、power cycle 逻辑）已就绪，硬件修复后无需改代码即可生效。
      改良后复测：`python tests/vout_blink.py`（盯 OUT1 LED）+ `eat_bench_selftest` 的
      `power.device_follow` 项应变为 "only alive with VOUT on"。
- [ ] JTAG/SWD 工具（DLL 原语已绑定，协议层未实现）。
- [ ] 烧录流水线（target 模板：STM32/ESP32/CH32 ISP 等）。

## 硬件能力一览（详见 docs/HARDWARE.md，此处为速查）

- **双串口** UART0/UART1（3.3V，最高 9M 波特率），每串口配 2 根 GPIO 可控制目标芯片 BOOT/复位/按键（连接器均为 6P 端子 + 2 外壳固定焊盘接 GND）：
  - UART0 连接器：GPIO2(pin1)、GPIO3(pin2)、TXD0(pin3)、RXD0(pin4)、GND(pin5)、VOUT(pin6)
  - UART1 连接器：GPIO5(pin1)、GPIO6(pin2)、TXD1(pin3)、RXD1(pin4)、GND(pin5)、VOUT(pin6)
- **I2C**（IIC1，1.25mm-4P：SDA/SCL/GND/VOUT，固定焊盘5/6接GND，4.7k 上拉已带，≤1MHz）
- **SPI**（SPI1，6P：VOUT/GND/MOSI/MISO/CLK/CS，固定焊盘7/8接GND，≤60MHz）
- **SWD/JTAG**（LINK1，1.25mm-4P：SWDIO/SWCLK/GND/VOUT；JTAG 的 TDI/TDO/TRST 复用 UART1 的 GPIO）
- **可程控电源 VOUT（3.3V）**：`GPIO0(pin17)=VOUT_EN`，**高=开、低=关，上电默认关**；支持目标板下电复位；SW1 拨到 GND 位为手动强制开
- USB 上游：Type-C 与 USB-A 公头并联二选一；PID 0x55DE

## 关键硬约束（写代码前必须知道）

1. **GPIO0 已被 VOUT_EN 占用，GPIO1 未引出（NC）**。可用 GPIO 只有 GPIO2/3（UART0 侧）、GPIO5/6（UART1 侧）、GPIO4/7（=SWCLK/SWDIO，与 SWD 冲突）。
2. **复用互斥**：使用 JTAG 时 GPIO3/5/6 不可作 GPIO；使用 SWD 时 GPIO4/7 不可作 GPIO；双串口 TXD/RXD 永远可用。
3. **CH347DLL V1.5 没有独立 SWD API** —— SWD 需用 GPIO 位带或 JTAG 原语实现。
4. 所有信号电平 **3.3V**；VOUT 亦为 3.3V（负载开关为双 PMOS 背靠背，防倒灌）。
5. Windows 驱动：`docs/CH343SER`（串口 VCP）+ `docs/CH341PAR.EXE`（厂商接口，CH347DLL 需要）。库与 API 参考 `docs/EVT/TOOLS/CH347Demo/ExternalLib/CH347DLL.H` 和 `docs/EVT/PUB/CH347应用开发手册.pdf`。

## 资料导航

- `docs/HARDWARE.md` —— **硬件连接/IO 分配/电源逻辑/复用冲突的唯一权威文档**（已逐脚核对原理图与数据手册）
- `docs/README.md` —— docs 资料分类索引与阅读优先级
- `docs/SCH_Schematic1_2026-10-17.pdf` —— 本板原理图（最终依据）
- `docs/CH347DS1.PDF` —— 芯片数据手册

## MCP server 使用（v0.2）

- 启动：`python eat_mcp_server.py`（stdio）；可选 `EAT_MCP_POLICY=full|no_write|read_only`。
- 代码结构：`src/eat/`（驱动层）+ `eat_mcp_server.py`（35 个 `eat_*` 工具层）。
  改硬件相关结论必须同步 `src/eat/board.py`（代码事实源）与 `docs/HARDWARE.md`（文档事实源）。
- 自检：`python tests/bench_selftest.py`（18 项）；MCP 冒烟：`python tests/mcp_smoke.py`；
  性能基准：`python tests/benchmark.py`（UART/I2C/SPI 多速率吞吐 + 完整性，结果见 README"性能实测"）；
  环境/连接体检：MCP 调 `eat_doctor`。
- 目标板模板：`config/targets/*.json`（stm32/esp32/ch32 示例，可自行添加），工具层
  `eat_target_profiles`/`eat_target_reset`/`eat_target_enter_bootloader`。
- Agent Skill：`skills/eat-embedded-tool/SKILL.md` + `python tools/install_skill.py`（装到
  Claude/Codex/ZCode/Cursor 的 skills 目录）。
- 未完待建：JTAG/SWD 协议层（DLL 原语已绑定）、UART ISP 烧录器实现（stm32/esptool 桥接）。

## 工作纪律

- 每次工作结束时：新结论/新约定落到文档（docs/ 或本文），避免下次会话重新推导。
- 原理图相关结论以 `docs/SCH_Schematic1_2026-10-17.pdf` 为准；文档与图纸冲突时改文档并注明。
- 后续若形成可复用流程（如"STM32 一键烧录流程"），用 skill 固化到 `.zcode/skills/` 或项目 skills 目录。
