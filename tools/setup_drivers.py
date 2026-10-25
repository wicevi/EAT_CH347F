"""Driver setup helper: CHECK FIRST, install only what is missing.

Usage:
  python tools/setup_drivers.py              # check the whole driver stack
  python tools/setup_drivers.py --install vcp   # CH343SER serial driver (admin)
  python tools/setup_drivers.py --install par   # CH341PAR vendor driver (admin)
  python tools/setup_drivers.py --install all

The driver stack this board needs on Windows:
  CH343SER  -> UART0/UART1 appear as COM ports   (installer: docs/CH343SER)
  CH341PAR  -> vendor interface for CH347DLL     (installer: docs/CH341PAR.EXE,
              also provides C:\\Windows\\System32\\CH347DLLA64.DLL)
Installers are GUI-based and need elevation; --install just launches them.
"""
from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

DOCS = Path(__file__).resolve().parent.parent / "docs"
VCP_SETUP = DOCS / "CH343SER" / "Driver" / "SETUP.EXE"
PAR_SETUP = DOCS / "CH341PAR.EXE"
DLL = Path(r"C:\Windows\System32\CH347DLLA64.DLL")
USB_MATCH = "VID_1A86&PID_55DE"


def board_present() -> bool:
    """True if the CH347F composite device is currently on the bus."""
    ps = ("(Get-PnpDevice -PresentOnly | Where-Object "
          f"{{ $_.InstanceId -match '{USB_MATCH}' }}).Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True,
                             timeout=20).stdout.strip()
        return int(out or 0) > 0
    except Exception:
        return False


def check_vcp() -> tuple[bool, str]:
    from eat.board import detect_uart_coms
    coms = detect_uart_coms()
    if coms.get("UART0") and coms.get("UART1"):
        return True, f"UART0={coms['UART0']} UART1={coms['UART1']}"
    return False, f"COM ports not found ({coms}) — install CH343SER"


def check_par() -> tuple[bool, str]:
    from eat.ch347_api import CH347Device, CH347Error
    try:
        dev = CH347Device()
        info = dev.device_info()
        dev.close()
        return True, f"{info['product']}, fw={info['firmware_ver']}"
    except CH347Error as e:
        return False, f"vendor interface not usable — install CH341PAR ({e})"


def check_dll() -> tuple[bool, str]:
    if DLL.exists():
        return True, str(DLL)
    return False, f"{DLL} missing — install CH341PAR"


def run_elevated(exe: Path) -> bool:
    """Launch installer with UAC elevation; returns whether it started."""
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(exe), "", str(exe.parent), 1)
    return rc > 32


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--install", choices=["vcp", "par", "all"], default=None,
                    help="launch installer(s) for the missing component")
    args = ap.parse_args()

    present = board_present()
    vcp_ok, vcp_msg = check_vcp()
    par_ok, par_msg = check_par()
    dll_ok, dll_msg = check_dll()

    print("== EAT CH347F driver stack check ==")
    print(f"  board plugged      : {'yes' if present else 'NO — plug the board in via USB'}")
    print(f"  CH343SER (COM x2)  : {'OK' if vcp_ok else 'MISSING'} — {vcp_msg}")
    print(f"  CH341PAR (vendor)  : {'OK' if par_ok else 'MISSING'} — {par_msg}")
    print(f"  CH347DLLA64.DLL    : {'OK' if dll_ok else 'MISSING'} — {dll_msg}")

    if not args.install:
        if not (vcp_ok and par_ok and dll_ok):
            print("\nmissing components -> run:  python tools/setup_drivers.py "
                  "--install " +
                  ("vcp " if not vcp_ok else "") +
                  ("par" if not (par_ok and dll_ok) else ""))
        else:
            print("\nall drivers ready — nothing to install")
        return 0

    # --install: only launch installers for what's actually missing
    launched = False
    if args.install in ("vcp", "all") and not vcp_ok:
        print(f"launching CH343SER installer (admin): {VCP_SETUP}")
        if not VCP_SETUP.exists():
            print(f"  ERROR: {VCP_SETUP} not found")
            return 1
        launched = run_elevated(VCP_SETUP)
    if args.install in ("par", "all") and not (par_ok and dll_ok):
        print(f"launching CH341PAR installer (admin): {PAR_SETUP}")
        if not PAR_SETUP.exists():
            print(f"  ERROR: {PAR_SETUP} not found")
            return 1
        launched = launched or run_elevated(PAR_SETUP)
    if launched:
        print("\ncomplete the installer UI, then re-run:  "
              "python tools/setup_drivers.py")
    else:
        print("\nnothing missing — no installer launched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
