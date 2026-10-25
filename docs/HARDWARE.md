# Embedded_Agent_Tool V1.0 硬件连接与 IO 分配

> 依据：`docs/SCH_Schematic1_2026-10-17.pdf`（嘉立创EDA，2页：Power + Main，2026-10-11），
> 并与 `docs/CH347DS1.PDF`（CH347 数据手册 V1.6）引脚定义逐脚核对一致。
> 本文是本项目**硬件事实的唯一权威来源**，PCB/驱动/MCP 软件开发均以此为准；如有出入以原理图 PDF 为最终依据并更新本文。

## 1. 板卡概述

- 定位：基于 **CH347F**（QFN-28，4×4mm，USB 2.0 高速 480Mbps）的嵌入式 AI 开发工具。
  PC/AI 工具通过 USB（Type-C 或 USB-A 公头）连接本板，即可使用：双串口 UART0/UART1（各带 2 路 GPIO）、
  I2C、SPI、JTAG/SWD，以及可程控的对外电源 VOUT，实现烧录/调试/复位/下电复位一条龙。
- CH347F **免配置工作模式**（出厂即五合一：双串口 + I2C + SPI + JTAG + SWD，默认 PID **0x55DE**），
  复用引脚功能由驱动切换。USB 接口分配：`0=UART0, 2=UART1, 4=SPI/I2C/JTAG/GPIO`。
- 信号电平：全部 **3.3V**（VCC_3V3 与 VIO 均为 3.3V；CH347F 的 VIO 支持 1.8~3.3V，本板固定 3.3V）。

## 2. 电源架构

```
USB1 Type-C 母座(VBUS) ─┐  (两个上游口 D+/D- 与 VBUS 均并联，二选一接 PC)
MH1 USB-A 公头 (VBUS)  ─┴─→ VBUS ─F1(1A保险丝)─→ VIN
                                          ├─ U2 XC6206P332MR (3.3V LDO, C1/C2 1uF) ─→ VCC_3V3
                                          └─ U3 TLV75733PDBVR  (3.3V LDO, EN由R1 100k常开) ─→ VIO
VIO ─→ [Q2+Q1 双AO3401A PMOS 串联负载开关] ─→ VOUT (3.3V，所有对外连接器的电源脚)
        栅极(并联) ← R2/R3 100k 上拉(默认关断)
        栅极 ← Q3 2N7002 (S=GND, D=栅极) ，Q3 栅极 ← VOUT_EN + R4 100k 下拉(默认低)
        栅极 ← SW1 拨动开关公共端(位1=GND 手动强制开；位3=NC；外壳=GND)
```

**VOUT 使能逻辑（软件控制电源的关键）**：

| VOUT_EN (CH347 pin17 / GPIO0) | SW1 位置 | VOUT |
|---|---|---|
| 低（默认，R4 下拉） | 断开/接 NC 位 | **关断**（上电默认不对外供电） |
| 高（GPIO0 置 1） | 断开/接 NC 位 | 导通，输出 3.3V |
| 任意 | 拨到 GND 位 | 强制导通（手动旁路，调试用） |

- VOUT_EN **高电平有效**；用 GPIO0 输出 1 打开、输出 0 关断。
- 实测注意：GPIO0 置为输入时，R2/R3(上拉 VIO) 与 R4(下拉 GND) 分压使 VOUT_EN 节点约 2.2V，
  GPIO 读数为高、Q3 处于半导通区——**软件必须保持 GPIO0 显式驱动**（驱动层 `Hardware` 已默认驱动为低）。
- 双 PMOS 背靠背串联，栅极并联，可**阻断反向电流**（目标板自供电时不会倒灌本板），也支持"下电复位"（VOUT off→delay→on）。
- ⚠️ **已知硬件问题（2026-10-18 用户确认待改良）**：该防盗灌负载开关电路当前工作异常，VOUT 似恒为导通（软件 VOUT_EN 控制无实际效果）。后续改版修复；软件栈（GPIO0 API/power cycle）已就绪，硬件修复后无需改动即可生效。
- VOUT 容量受 U3 (TLV75733, 500mA 级) 与 F1(1A) 限制，为目标板供电时注意总功耗。

## 3. CH347F (U1) 引脚分配总表

| 脚 | 引脚名（复用功能） | 板上网络 | 连接去向 |
|---|---|---|---|
| 1 | XI | XI | X1 8MHz 晶振 + C6 22pF |
| 2 | XO | XO | X1 晶振 + C5 22pF |
| 3 | RST# | RST# | R5 4.7k 上拉到 VCC_3V3，C7 100nF 到 GND（外部复位输入） |
| 4 | TXD1 | TXD1 | UART1 连接器 pin3；TX1 指示灯 |
| 5 | RXD1 | RXD1 | UART1 连接器 pin4；RX1 指示灯 |
| 6 | VIO | VIO | U3 输出 3.3V |
| 7 | DTR1/TNOW1/SCS1 | **NC（未连接）** | — |
| 8 | ACT/SRST | ACT# | ACT1 绿色 LED（USB 配置完成后亮；JTAG 模式作 SRST 时仅驱动此 LED，未引出） |
| 9 | TRST/GPIO3 | GPIO3 | UART0 连接器 pin2 |
| 10 | DTR0/TNOW0/GPIO2 | GPIO2 | UART0 连接器 pin1 |
| 11 | CTS1/SCL | SCL | IIC1 pin2；R12 4.7k 上拉到 VIO |
| 12 | RTS1/SDA | SDA | IIC1 pin1；R13 4.7k 上拉到 VIO |
| 13 | SCS0 | SPI_CS | SPI1 pin6 |
| 14 | SCK | SPI_CLK | SPI1 pin5 |
| 15 | MISO | SPI_MISO | SPI1 pin4 |
| 16 | MOSI | SPI_MOSI | SPI1 pin3 |
| 17 | CTS0/**GPIO0** | **VOUT_EN** | Q3 栅极（电源使能，高=开）+ R4 100k 下拉；注意此脚电源域为 VCC，固定 3.3V |
| 18 | RTS0/GPIO1 | **NC（未连接）** | — |
| 19 | TXD0 | TXD0 | UART0 连接器 pin3；TX0 指示灯 |
| 20 | GND | GND | 地 |
| 21 | VCC | VCC_3V3 | U2 输出 3.3V；C8 100nF 退耦 |
| 22 | RXD0 | RXD0 | UART0 连接器 pin4；RX0 指示灯 |
| 23 | TCK/SWDCLK/GPIO4 | SWCLK | LINK1 pin2（SWD 时钟） |
| 24 | TDO/GPIO5 | GPIO5 | UART1 连接器 pin1 |
| 25 | TDI/GPIO6 | GPIO6 | UART1 连接器 pin2 |
| 26 | TMS/SWDIO/GPIO7 | SWDIO | LINK1 pin1（SWD 数据） |
| 27 | UD- | UD- | D2 USBLC6-2SC6 → USB_DN |
| 28 | UD+ | UD+ | D2 USBLC6-2SC6 → USB_DP |
| 0#（数据手册）/ **29#（原理图位号 PAD）** | QFN 底部裸盘 | 原理图未显式连接 | 数据手册建议接 GND，**PCB 布线时务必将裸盘接大地** |

### GPIO 编号 ↔ 物理引脚 ↔ 引出位置（`CH347GPIO_Set/Get` 的 bit0~bit7）

| DLL GPIO bit | CH347 脚 | 板上去处 | 备注 |
|---|---|---|---|
| GPIO0 | 17 | **VOUT_EN**（电源使能专用） | 高=VOUT 开；勿作它用 |
| GPIO1 | 18 | 未引出（NC） | 不可用 |
| GPIO2 | 10 | UART0 连接器 pin1 | 可作 BOOT/复位/按键 |
| GPIO3 | 9 | UART0 连接器 pin2 | 兼 JTAG TRST，用 JTAG 时不可作 GPIO |
| GPIO4 | 23 | SWCLK（LINK1 pin2） | 兼 SWD 时钟；作 GPIO 时与 SWD 冲突 |
| GPIO5 | 24 | UART1 连接器 pin1 | 兼 JTAG TDO，用 JTAG 时不可作 GPIO |
| GPIO6 | 25 | UART1 连接器 pin2 | 兼 JTAG TDI，用 JTAG 时不可作 GPIO |
| GPIO7 | 26 | SWDIO（LINK1 pin1） | 兼 SWD 数据；作 GPIO 时与 SWD 冲突 |

## 4. 对外连接器引脚定义

**UART0（6P 端子，串口0 + 2×GPIO；另有 2 个外壳固定焊盘 7/8 接 GND）**

| pin | 1 | 2 | 3 | 4 | 5 | 6 | 固定焊盘 7/8 |
|---|---|---|---|---|---|---|---|
| 信号 | GPIO2 | GPIO3 | TXD0 | RXD0 | GND | VOUT | GND（外壳） |

**UART1（6P 端子，串口1 + 2×GPIO；固定焊盘 7/8 接 GND）**

| pin | 1 | 2 | 3 | 4 | 5 | 6 | 固定焊盘 7/8 |
|---|---|---|---|---|---|---|---|
| 信号 | GPIO5 | GPIO6 | TXD1 | RXD1 | GND | VOUT | GND（外壳） |

**SPI1（6P 端子，pin1 有点标记；固定焊盘 7/8 接 GND）**

| pin | 1 | 2 | 3 | 4 | 5 | 6 | 固定焊盘 7/8 |
|---|---|---|---|---|---|---|---|
| 信号 | VOUT | GND | SPI_MOSI | SPI_MISO | SPI_CLK | SPI_CS | GND（外壳） |

**LINK1（SWD，HC-1.25-4PLT，1.25mm 4P）**

| pin | 1 | 2 | 3 | 4 | 外壳(5/6) |
|---|---|---|---|---|---|
| 信号 | SWDIO | SWCLK | GND | VOUT | GND |

**IIC1（I2C，HC-1.25-4PLT，1.25mm 4P）**

| pin | 1 | 2 | 3 | 4 | 外壳(5/6) |
|---|---|---|---|---|---|
| 信号 | SDA | SCL | GND | VOUT | GND |

> UART0/UART1/SPI1 的连接器实物型号未在原理图标注（均为 6P 端子 + 2 外壳固定焊盘，固定焊盘接 GND），具体封装以 PCB 为准。
> LINK1/IIC1 的固定焊盘为 5/6（接 GND）。SCL/SDA 已有 4.7k 上拉（R12/R13→VIO）。

## 5. USB 接口

- **双上游并联**：USB1（Type-C 16P 母座，2MD-073）与 MH1（USB-A 公头，USB2 AM90）的 VBUS、D+、D- 全部并联，**同一时间只能接一个**到 PC。
- Type-C CC1/CC2 各经 5.1kΩ（R16/R17）下拉到地 = UFP 设备角色，任意线序可插。
- D+/D- 经 D2（USBLC6-2SC6）ESD 保护后接 CH347F UD+/UD-（手册要求 UD+/UD- 直连，禁止串电阻——本板仅在 D2 前级做 ESD）。
- VID=0x1A86 (WCH)，PID=0x55DE（CH347F 五合一默认）。

## 6. LED 指示灯

| 位号 | 颜色/型号 | 连接 | 含义 |
|---|---|---|---|
| ACT1 | 绿 XL-1608UGC-04 | VCC_3V3 → R6 2.2k → LED → ACT#(pin8) | USB 枚举配置完成后亮（低有效） |
| OUT1 | 绿 XL-1608UGC-04 | VOUT → R7 2.2k → LED → GND | VOUT 电源输出指示 |
| TX0/TX1 | 黄 NCD0603Y2 | VIO → R8/R9 2.2k → LED → TXD0/TXD1 | 串口发送指示（数据线低电平亮） |
| RX0/RX1 | 蓝 XL-1608UBC-04 | VIO → R10/R11 2.2k → LED → RXD0/RXD1 | 串口接收指示（数据线低电平亮） |

## 7. 目标板控制模型（Boot/复位/按键/下电）

MCP 层应实现的通用动作（均可用现有硬件完成）：

1. **复位脉冲**：GPIO 输出低→延时(≥100ms)→高（或反向，视目标板）。UART0 用 GPIO2/GPIO3，UART1 用 GPIO5/GPIO6。
   - 例 STM32：GPIO2→NRST（低有效复位），GPIO3→BOOT0
   - 例 ESP32：GPIO2→EN（配合脉冲进 boot），GPIO3→IO0
   - 例 CH32/CH340 串口 ISP：参考 WCH 串口下载器的 DTR/RTS 时序
2. **进入 Bootloader**：先拉 BOOT 引脚，再复位，再释放。
3. **下电复位（极端恢复）**：`VOUT_EN=0` → 延时(≥1s) → `VOUT_EN=1`；若目标板自供电，改用复位脉冲。
4. **SW1 手动旁路**：现场调试可把 SW1 拨到 GND 位强制 VOUT 常开，与软件控制互斥（软件关断将失效）。

## 8. 功能复用冲突表（MCP 层必须处理）

| 同时使用 | 冲突引脚 | 结论 |
|---|---|---|
| JTAG + UART0 的 GPIO3 | pin9 = TRST/GPIO3 | 互斥 |
| JTAG + UART1 的 GPIO5/GPIO6 | pin24/25 = TDO/TDI | 互斥（JTAG 期间 UART1 仅剩 TXD/RXD） |
| SWD + GPIO4/GPIO7 | pin23/26 | 互斥 |
| SWD + JTAG | pin23/26 = SWCLK/SWDIO vs TCK/TMS | 标准SWJ-DP复用，二选一 |
| 任意功能 + 双串口数据线 TXD/RXD | 无共享 | **始终可用** |
| I2C + UART1 MODEM(CTS1/RTS1) | pin11/12 | I2C 占用时无 CTS1/RTS1 |
| GPIO0(VOUT_EN) | pin17 | 已被电源使能占用，禁止挪用 |

其它注意：
- **DLL V1.5（docs 内 CH347DLL.H）没有独立 SWD API**，SWD 需用 GPIO 位带（GPIO4=SWCLK/GPIO7=SWDIO）或 JTAG 原语（CH347Jtag_IoScan 等）自行实现 SWD 协议时序；关注 WCH 后续 DLL 更新。
- CH347F 上电时 pin8(ACT) 若检测到下拉电阻则 DTR1 切为 TNOW1——本板 pin8 仅接 LED（2.2k+LED 到 VCC，等效弱上拉），无影响；pin17/18 上电检测（RTS0 下拉禁用 EEPROM 参数）本板均未接下拉，使用芯片内部默认参数。
- CH347 内部已含 EEPROM（可用 CH34xSerCfg.exe 改 VID/PID），本板未外挂配置 EEPROM；I2C/SPI 总线纯对外。

## 9. 元器件 BOM 摘要（原理图位号）

| 位号 | 规格 | 作用 |
|---|---|---|
| U1 | CH347F (QFN-28) | 主控 |
| U2 | XC6206P332MR (SOT-89) | 3.3V LDO → VCC_3V3 |
| U3 | TLV75733PDBVR (SOT-23-5) | 3.3V LDO → VIO |
| Q1,Q2 | AO3401A (PMOS) | VOUT 负载开关（背靠背） |
| Q3 | 2N7002 (NMOS) | 栅极下拉驱动 |
| D2 | USBLC6-2SC6 | USB ESD |
| F1 | SMD0805-100-12 (1A) | USB 保险丝 |
| X1 | 8MHz 晶振 + C5/C6 22pF | CH347 时钟 |
| SW1 | MSK12C02 | VOUT 手动强制开 |
| USB1 | Type-C 16P 2MD(073) | 上游口1 |
| MH1 | USB2 AM90（A公90°，安装腿 MH1/MH2 接 GND） | 上游口2 |
| R5 | 4.7k | RST# 上拉 |
| R12,R13 | 4.7k | I2C 上拉 |
| R2,R3 | 100k | PMOS 栅极上拉 |
| R4 | 100k | VOUT_EN 下拉 |
| R1 | 100k | U3 EN 上拉 |
| R16,R17 | 5.1k | Type-C CC 下拉 |
| R6~R11 | 2.2k | LED 限流 |
| C7 | 100nF | RST# 滤波 |
| C8,C9 | 100nF | VCC_3V3 / VIO 退耦 |
| C1~C4 | 1uF | LDO 输入/输出 |
| UART0/UART1/SPI1 | 6P 连接器 + 2 外壳固定焊盘（GND，型号见 PCB） | 对外信号 |
| LINK1/IIC1 | HC-1.25-4PLT | SWD / I2C 对外 |

## 10. Windows 驱动与软件栈（MCP 开发依据）

- USB 复合设备：接口 0=UART0、2=UART1（VCP，装 `docs/CH343SER` 后呈现为 2 个 COM 口）、接口 4=SPI/I2C/JTAG/GPIO（厂商接口，装 `docs/CH341PAR.EXE` 后由 CH347DLL 访问）。
- 动态库：`docs/EVT/TOOLS/CH347Demo/ExternalLib/`（CH347DLL.H + i386/amd64/arm64 的 .lib；运行时需 CH347DLL64.DLL/CH347DLL.DLL，随驱动或 WCH 官网分发）。
- API 能力：`CH347Uart_*`（串口）、`CH347SPI_*`（≤60MHz）、`CH347I2C_Set/StreamI2C`（20kHz~1MHz）、`CH347Jtag_*`（≤60MHz）、`CH347GPIO_Get/Set`（GPIO0~7 批量读写 + 边沿中断）、`CH347ReadEEPROM/WriteEEPROM`（24Cxx 系列）、`CH347SetDeviceNotify`（热插拔）。
- 参考实现：`docs/EVT/TOOLS/CH347Demo/`（MFC C++ 示例：UartDebug/SpiIicDebug/JtagDebug/GpioDebug/EepromDebug/FlashDebug）。
