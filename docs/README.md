# docs 资料索引与分类

> 本目录是项目原始资料库。**硬件连接结论请看 [HARDWARE.md](./HARDWARE.md)**（已核对原理图与数据手册，勿重复推导）。

## 一、本板设计文件

| 文件 | 说明 |
|---|---|
| `SCH_Schematic1_2026-10-17.pdf` | **本板原理图**（Embedded_Agent_Tool V1.0，嘉立创EDA，2页：Power/Main）。IO 分配、电源树、连接器定义的最终依据 |
| `HARDWARE.md` | 原理图解读结论：引脚分配表、连接器定义、电源/VOUT 逻辑、复用冲突（本文档为本目录唯一二次加工产物） |

## 二、CH347 芯片资料（WCH 官方 EVT 包）

| 文件 | 说明 |
|---|---|
| `CH347DS1.PDF` | CH347 数据手册 V1.6（中文）。引脚定义（第4章）、工作模式、电气参数、I2C/SPI/JTAG/SWD 时序 |
| `EVT/PUB/CH347应用开发手册.pdf` | **应用开发手册 V1.6**：CH347DLL 全部 API 说明（SPI/JTAG/I2C/UART/GPIO/EEPROM），MCP server 封装的主要参考 |
| `EVT/PUB/CH347ApplicationDevelopmentManual.pdf` | 同上英文版 |
| `EVT/PUB/CH347EVT.pdf` / `CH347EVT_EN.pdf` | WCH 官方评估板说明（含 EEPROM/FLASH 编程应用参考、CH34xSerCfg 配置工具说明） |
| `EVT/PCB/CH347SCH.pdf` | 官方评估板原理图（CH347F 最小系统参考，可对照本板） |

## 三、驱动与库（Windows）

| 文件 | 说明 |
|---|---|
| `CH343SER/` | CH343/CH347 系列 **VCP 串口驱动**（本板 UART0/UART1 → 2 个 COM 口；含 Driver/ 安装包与 LIB/ 编程接口） |
| `CH341PAR.EXE` | **厂商接口驱动安装包**（自解压；装后 CH347DLL 可访问接口4：SPI/I2C/JTAG/GPIO） |
| `EVT/TOOLS/CH347Demo/` | 官方 C++(MFC) Demo：UART/SPI/I2C/JTAG/GPIO/EEPROM/Flash 调试面板完整源码 |
| `EVT/TOOLS/CH347Demo/ExternalLib/` | **CH347DLL.H V1.5** + i386/amd64/arm64 导入库（MCP server 直接链接） |

注意：CH347DLL.H V1.5 **无独立 SWD API**（SWD 需 GPIO 位带或 JTAG 原语实现，详见 HARDWARE.md §8）。

## 四、目标器件数据手册（供烧录/读写功能参考）

| 文件 | 说明 |
|---|---|
| `C6203_EEPROM_AT24C02C-SSHM-T_规格书_WJ96523.PDF` | I2C EEPROM（CH347DLL 的 `CH347ReadEEPROM/WriteEEPROM` 原生支持 24Cxx 全系） |
| `C98163_NOR+FLASH_W25Q80DVSSIG_规格书_WJ288327.PDF` | SPI NOR Flash（Demo 的 `SPI_Flash.cpp` 有 W25Q 系列读写/擦除实现可复用） |

这两颗是**目标板侧常用器件**的参考手册——本板本身未焊接 EEPROM/Flash，I2C/SPI 总线通过连接器纯对外。

## 阅读优先级（新会话冷启动建议）

1. 仓库根 `AGENTS.md`（项目必读）
2. `HARDWARE.md`（硬件事实）
3. `EVT/PUB/CH347应用开发手册.pdf`（API 细节，按需查阅）
4. `CH347DS1.PDF`（芯片细节，按需查阅）
