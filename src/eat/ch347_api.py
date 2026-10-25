"""CH347DLL ctypes binding (Windows).

Binds the WCH user-mode runtime DLL (installed by the CH341PAR driver package as
C:\\Windows\\System32\\CH347DLLA64.DLL on x64) for the CH347F vendor interface
(USB MI_04), plus the SPI/I2C/GPIO/JTAG function set declared in
docs/EVT/TOOLS/CH347Demo/ExternalLib/CH347DLL.H (V1.5).

All structures use #pragma pack(1) — mirrored here with _pack_ = 1.
"""
from __future__ import annotations

import ctypes
from ctypes import (POINTER, Structure, c_char, c_ubyte, c_uint, c_ushort,
                    c_void_p, wintypes)
from pathlib import Path

MAX_PATH_ = 260

# --- constants from CH347DLL.H -------------------------------------------------
CHIP_TYPE_CH341 = 0
CHIP_TYPE_CH347 = 1          # CH347T
CHIP_TYPE_CH347F = 2
CHIP_TYPE_CH339W = 3

CH347_FUNC_UART = 0
CH347_FUNC_SPI_IIC = 1
CH347_FUNC_JTAG_IIC = 2
CH347_FUNC_JTAG_IIC_SPI = 3  # CH347F

DEFAULT_READ_TIMEOUT = 500
DEFAULT_WRITE_TIMEOUT = 500
MCH347_PACKET_LENGTH = 512

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# SPI iClock codes (struct init); actual frequency via CH347SPI_SetFrequency
SPI_CLOCK_60M = 0
SPI_CLOCK_30M = 1
SPI_CLOCK_15M = 2
SPI_CLOCK_7_5M = 3
SPI_CLOCK_3_75M = 4
SPI_CLOCK_1_875M = 5
SPI_CLOCK_937K5 = 6
SPI_CLOCK_468K75 = 7

# I2C speed codes for CH347I2C_Set
I2C_SPEED_20K = 0
I2C_SPEED_100K = 1
I2C_SPEED_400K = 2
I2C_SPEED_750K = 3
I2C_SPEED_50K = 4
I2C_SPEED_200K = 5
I2C_SPEED_1M = 6

# EEPROM ids for CH347Read/WriteEEPROM
EEPROM_IDS = {
    "24C01": 0, "24C02": 1, "24C04": 2, "24C08": 3, "24C16": 4, "24C32": 5,
    "24C64": 6, "24C128": 7, "24C256": 8, "24C512": 9, "24C1024": 10,
    "24C2048": 11, "24C4096": 12,
}

# JTAG clock rate codes for CH347Jtag_INIT
JTAG_CLOCKS_HZ = [468_750, 937_500, 1_875_000, 3_750_000, 7_500_000,
                  15_000_000, 30_000_000, 60_000_000]


class CH347Error(RuntimeError):
    """CH347 DLL call failure."""


class mSpiCfgS(Structure):
    _pack_ = 1
    _fields_ = [
        ("iMode", c_ubyte),                  # SPI mode 0-3
        ("iClock", c_ubyte),                 # legacy clock code (use SetFrequency)
        ("iByteOrder", c_ubyte),             # 0=LSB first, 1=MSB first
        ("iSpiWriteReadInterval", c_ushort), # us between read/write commands
        ("iSpiOutDefaultData", c_ubyte),     # default MOSI data during reads
        ("iChipSelect", c_uint),             # bit7=1 enable CS, bit1:0 00=CS1,01=CS2
        ("CS1Polarity", c_ubyte),            # 0=active low
        ("CS2Polarity", c_ubyte),
        ("iIsAutoDeativeCS", c_ushort),
        ("iActiveDelay", c_ushort),          # us after CS assert
        ("iDelayDeactive", c_uint),          # us after CS deassert
    ]


class mDeviceInforS(Structure):
    _pack_ = 1
    _fields_ = [
        ("iIndex", c_ubyte),
        ("DevicePath", c_ubyte * MAX_PATH_),
        ("UsbClass", c_ubyte),               # 0:vendor 2:HID 3:VCP
        ("FuncType", c_ubyte),               # CH347_FUNC_*
        ("DeviceID", c_char * 64),
        ("ChipMode", c_ubyte),               # 4 = CH347F five-in-one
        ("DevHandle", c_void_p),
        ("BulkOutEndpMaxSize", c_ushort),
        ("BulkInEndpMaxSize", c_ushort),
        ("UsbSpeedType", c_ubyte),           # 0:FS 1:HS 2:SS
        ("CH347IfNum", c_ubyte),
        ("DataUpEndp", c_ubyte),
        ("DataDnEndp", c_ubyte),
        ("ProductString", c_char * 64),
        ("ManufacturerString", c_char * 64),
        ("WriteTimeout", c_uint),
        ("ReadTimeout", c_uint),
        ("FuncDescStr", c_char * 64),
        ("FirewareVer", c_ubyte),
    ]


_DLL_CANDIDATES = [
    r"C:\Windows\System32\CH347DLLA64.DLL",  # x64, from CH341PAR package
    r"C:\Windows\System32\CH347DLL64.DLL",
    r"C:\Windows\SysWOW64\CH347DLL.DLL",     # x86 fallback
    "CH347DLLA64.DLL",                       # rely on PATH
]


def find_dll() -> str:
    for cand in _DLL_CANDIDATES:
        if Path(cand).exists() or not ("\\" in cand or "/" in cand):
            return cand
    raise CH347Error("CH347 runtime DLL not found (install CH341PAR driver package)")


class CH347Device:
    """One opened CH347 vendor-interface device (index-based, like the DLL)."""

    def __init__(self, index: int = 0, dll_path: str | None = None):
        self.index = index
        self.dll_path = dll_path or find_dll()
        self.dll = ctypes.WinDLL(self.dll_path)
        self._opened = False
        self._bind()
        self.open()

    # -- binding ---------------------------------------------------------------
    def _bind(self) -> None:
        d = self.dll
        ULONG, UCHAR, BOOL = c_uint, c_ubyte, ctypes.c_int  # BOOL is 4-byte

        d.CH347OpenDevice.argtypes = [ULONG]
        d.CH347OpenDevice.restype = c_void_p
        d.CH347CloseDevice.argtypes = [ULONG]
        d.CH347CloseDevice.restype = BOOL
        d.CH347GetDeviceInfor.argtypes = [ULONG, POINTER(mDeviceInforS)]
        d.CH347GetDeviceInfor.restype = BOOL
        d.CH347GetChipType.argtypes = [ULONG]
        d.CH347GetChipType.restype = UCHAR
        d.CH347GetVersion.argtypes = [ULONG] + [POINTER(UCHAR)] * 4
        d.CH347GetVersion.restype = BOOL
        d.CH347SetTimeout.argtypes = [ULONG, ULONG, ULONG]
        d.CH347SetTimeout.restype = BOOL

        d.CH347GPIO_Get.argtypes = [ULONG, POINTER(UCHAR), POINTER(UCHAR)]
        d.CH347GPIO_Get.restype = BOOL
        d.CH347GPIO_Set.argtypes = [ULONG, UCHAR, UCHAR, UCHAR]
        d.CH347GPIO_Set.restype = BOOL

        d.CH347I2C_Set.argtypes = [ULONG, ULONG]
        d.CH347I2C_Set.restype = BOOL
        d.CH347I2C_SetStretch.argtypes = [ULONG, BOOL]
        d.CH347I2C_SetStretch.restype = BOOL
        d.CH347I2C_SetDriverMode.argtypes = [ULONG, UCHAR]
        d.CH347I2C_SetDriverMode.restype = BOOL
        d.CH347StreamI2C.argtypes = [ULONG, ULONG, c_void_p, ULONG, c_void_p]
        d.CH347StreamI2C.restype = BOOL
        d.CH347StreamI2C_RetACK.argtypes = [ULONG, ULONG, c_void_p, ULONG,
                                            c_void_p, POINTER(c_uint)]
        d.CH347StreamI2C_RetACK.restype = BOOL

        d.CH347ReadEEPROM.argtypes = [ULONG, ULONG, ULONG, ULONG, c_void_p]
        d.CH347ReadEEPROM.restype = BOOL
        d.CH347WriteEEPROM.argtypes = [ULONG, ULONG, ULONG, ULONG, c_void_p]
        d.CH347WriteEEPROM.restype = BOOL

        d.CH347SPI_Init.argtypes = [ULONG, POINTER(mSpiCfgS)]
        d.CH347SPI_Init.restype = BOOL
        d.CH347SPI_SetFrequency.argtypes = [ULONG, ULONG]
        d.CH347SPI_SetFrequency.restype = BOOL
        d.CH347SPI_SetDataBits.argtypes = [ULONG, UCHAR]
        d.CH347SPI_SetDataBits.restype = BOOL
        d.CH347SPI_GetCfg.argtypes = [ULONG, POINTER(mSpiCfgS)]
        d.CH347SPI_GetCfg.restype = BOOL
        d.CH347SPI_Write.argtypes = [ULONG, ULONG, ULONG, ULONG, c_void_p]
        d.CH347SPI_Write.restype = BOOL
        d.CH347SPI_Read.argtypes = [ULONG, ULONG, ULONG, POINTER(ULONG), c_void_p]
        d.CH347SPI_Read.restype = BOOL
        d.CH347SPI_WriteRead.argtypes = [ULONG, ULONG, ULONG, c_void_p]
        d.CH347SPI_WriteRead.restype = BOOL
        d.CH347SPI_SetChipSelect.argtypes = [ULONG, c_ushort, c_ushort,
                                             c_uint, c_uint, c_uint]
        d.CH347SPI_SetChipSelect.restype = BOOL

        d.CH347Jtag_INIT.argtypes = [ULONG, UCHAR]
        d.CH347Jtag_INIT.restype = BOOL
        d.CH347Jtag_GetCfg.argtypes = [ULONG, POINTER(UCHAR)]
        d.CH347Jtag_GetCfg.restype = BOOL
        d.CH347Jtag_ResetTrst.argtypes = [ULONG, BOOL]
        d.CH347Jtag_ResetTrst.restype = BOOL

    # -- helpers ---------------------------------------------------------------
    @staticmethod
    def _buf(data: bytes | None, min_len: int = 0):
        n = max(len(data or b""), min_len)
        buf = ctypes.create_string_buffer(n if n else 1)
        if data:
            ctypes.memmove(buf, data, len(data))
        return buf

    def _chk(self, ok: int, what: str) -> None:
        if not ok:
            raise CH347Error(f"{what} failed (device {self.index})")

    # -- device ----------------------------------------------------------------
    def open(self) -> None:
        if self._opened:
            return
        h = self.dll.CH347OpenDevice(self.index)
        if h in (None, INVALID_HANDLE_VALUE, 0):
            raise CH347Error(
                f"CH347OpenDevice({self.index}) failed — is the CH341PAR "
                "vendor driver installed and the board plugged in?")
        self._opened = True
        self.dll.CH347SetTimeout(self.index, DEFAULT_WRITE_TIMEOUT,
                                 DEFAULT_READ_TIMEOUT)

    def close(self) -> None:
        if self._opened:
            self.dll.CH347CloseDevice(self.index)
            self._opened = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def device_info(self) -> dict:
        info = mDeviceInforS()
        self._chk(self.dll.CH347GetDeviceInfor(self.index, ctypes.byref(info)),
                  "CH347GetDeviceInfor")
        drv = c_ubyte(); dllv = c_ubyte(); bcd = c_ubyte(); chip = c_ubyte()
        self.dll.CH347GetVersion(self.index, ctypes.byref(drv), ctypes.byref(dllv),
                                 ctypes.byref(bcd), ctypes.byref(chip))
        return {
            "index": info.iIndex,
            "chip_type": int(chip.value),
            "chip_mode": info.ChipMode,
            "func_type": info.FuncType,
            "usb_class": info.UsbClass,
            "usb_speed": ["full", "high", "super"][info.UsbSpeedType]
                         if info.UsbSpeedType < 3 else info.UsbSpeedType,
            "usb_if_num": info.CH347IfNum,
            "device_id": info.DeviceID.decode(errors="replace"),
            "product": info.ProductString.decode(errors="replace"),
            "manufacturer": info.ManufacturerString.decode(errors="replace"),
            "func_desc": info.FuncDescStr.decode(errors="replace"),
            "firmware_ver": f"{info.FirewareVer >> 4}.{info.FirewareVer & 0xF}",
            "driver_ver": f"{drv.value >> 4}.{drv.value & 0xF}",
            "dll_ver": f"{dllv.value >> 4}.{dllv.value & 0xF}",
            "bcd_device": hex(bcd.value),
            "endpoints": {"up": hex(info.DataUpEndp), "dn": hex(info.DataDnEndp),
                          "up_size": info.BulkInEndpMaxSize,
                          "dn_size": info.BulkOutEndpMaxSize},
        }

    # -- GPIO ------------------------------------------------------------------
    def gpio_get(self) -> tuple[int, int]:
        """Return (dir_byte, data_byte); bit n = GPION, dir 1=output."""
        d = c_ubyte(); v = c_ubyte()
        self._chk(self.dll.CH347GPIO_Get(self.index, ctypes.byref(d),
                                         ctypes.byref(v)), "CH347GPIO_Get")
        return d.value, v.value

    def gpio_set(self, enable: int, dir_out: int, data_out: int) -> None:
        self._chk(self.dll.CH347GPIO_Set(self.index, enable, dir_out, data_out),
                  "CH347GPIO_Set")

    # -- I2C -------------------------------------------------------------------
    def i2c_set_speed(self, speed: int = I2C_SPEED_100K) -> None:
        self._chk(self.dll.CH347I2C_Set(self.index, speed), "CH347I2C_Set")

    def i2c_set_stretch(self, enable: bool) -> None:
        self._chk(self.dll.CH347I2C_SetStretch(self.index, enable),
                  "CH347I2C_SetStretch")

    def i2c_set_driver_mode(self, push_pull: bool) -> None:
        self._chk(self.dll.CH347I2C_SetDriverMode(self.index, push_pull),
                  "CH347I2C_SetDriverMode")

    def i2c_transfer(self, write: bytes, read_len: int) -> bytes:
        """CH347StreamI2C: write bytes (first = 8-bit device address), then read."""
        wb = self._buf(write)
        rb = self._buf(None, read_len)
        ok = self.dll.CH347StreamI2C(self.index, len(write), wb, read_len, rb)
        self._chk(ok, "CH347StreamI2C")
        return rb.raw[:read_len]

    def i2c_transfer_ack(self, write: bytes, read_len: int) -> tuple[bytes, int]:
        """CH347StreamI2C_RetACK: also returns host-side ACK count."""
        wb = self._buf(write)
        rb = self._buf(None, read_len)
        acks = c_uint()
        ok = self.dll.CH347StreamI2C_RetACK(self.index, len(write), wb, read_len,
                                            rb, ctypes.byref(acks))
        self._chk(ok, "CH347StreamI2C_RetACK")
        return rb.raw[:read_len], acks.value

    def eeprom_read(self, model: str, addr: int, length: int) -> bytes:
        buf = self._buf(None, length)
        self._chk(self.dll.CH347ReadEEPROM(self.index, EEPROM_IDS[model.upper()],
                                           addr, length, buf),
                  "CH347ReadEEPROM")
        return buf.raw[:length]

    def eeprom_write(self, model: str, addr: int, data: bytes) -> None:
        buf = self._buf(data)
        self._chk(self.dll.CH347WriteEEPROM(self.index, EEPROM_IDS[model.upper()],
                                            addr, len(data), buf),
                  "CH347WriteEEPROM")

    # -- SPI -------------------------------------------------------------------
    def spi_init(self, mode: int = 0, freq_hz: int = 1_875_000,
                 cs: int = 0, cs_polarity_low: bool = True,
                 msb_first: bool = True) -> None:
        self._chk(self.dll.CH347SPI_SetFrequency(self.index, freq_hz),
                  "CH347SPI_SetFrequency")
        self._chk(self.dll.CH347SPI_SetDataBits(self.index, 0),  # 8-bit
                  "CH347SPI_SetDataBits")
        cfg = mSpiCfgS()
        cfg.iMode = mode & 3
        cfg.iClock = SPI_CLOCK_1_875M
        cfg.iByteOrder = 1 if msb_first else 0
        cfg.iSpiWriteReadInterval = 0
        cfg.iSpiOutDefaultData = 0xFF
        cfg.iChipSelect = 0x80 | (cs & 1)
        cfg.CS1Polarity = 0 if cs_polarity_low else 1
        cfg.CS2Polarity = 0
        cfg.iIsAutoDeativeCS = 1
        cfg.iActiveDelay = 0
        cfg.iDelayDeactive = 0
        self._chk(self.dll.CH347SPI_Init(self.index, ctypes.byref(cfg)),
                  "CH347SPI_Init")

    def spi_transfer(self, data: bytes, rx_len: int = 0,
                     total_len: int | None = None) -> bytes:
        """Full-duplex transfer with auto CS (CS1 = SCS0/pin13 on this board).

        data: bytes shifted out on MOSI; returns the last rx_len bytes shifted
        in on MISO over the whole frame (frame length = max(len(data),
        total_len, rx_len)). rx_len=0 → return full frame.
        """
        n = total_len if total_len is not None else max(len(data), rx_len)
        if n == 0:
            return b""
        frame = bytes(data) + b"\xFF" * max(0, n - len(data))
        buf = self._buf(frame)
        self._chk(self.dll.CH347SPI_WriteRead(self.index, 0x80 | 0, n, buf),
                  "CH347SPI_WriteRead")
        raw = buf.raw[:n]
        return raw if rx_len == 0 else raw[-rx_len:]

    def spi_write(self, data: bytes, step: int = 512) -> None:
        buf = self._buf(data)
        self._chk(self.dll.CH347SPI_Write(self.index, 0x80 | 0, len(data),
                                          step, buf), "CH347SPI_Write")

    def spi_read(self, send: bytes, read_len: int) -> bytes:
        """Endpoint read (CH347SPI_Read): one CS frame — clock out `send`
        (command + address bytes), then clock in `read_len` bytes."""
        wb = self._buf(send)
        rb = self._buf(None, read_len)
        got = c_uint(read_len)
        self._chk(self.dll.CH347SPI_Read(self.index, 0x80 | 0, len(send),
                                         ctypes.byref(got), rb), "CH347SPI_Read")
        return rb.raw[:got.value]

    # -- JTAG (primitives; protocol layers come later) ---------------------------
    def jtag_init(self, rate_code: int = 4) -> None:
        self._chk(self.dll.CH347Jtag_INIT(self.index, rate_code), "CH347Jtag_INIT")

    def jtag_trst(self, high: bool) -> None:
        self._chk(self.dll.CH347Jtag_ResetTrst(self.index, high),
                  "CH347Jtag_ResetTrst")
