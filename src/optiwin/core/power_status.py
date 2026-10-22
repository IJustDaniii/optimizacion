"""Estado de energía en tiempo real (barato: una llamada a la API de Windows, sin PowerShell)."""

from __future__ import annotations

import ctypes
import re
from dataclasses import dataclass

from optiwin.core.winutil import run


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


@dataclass(frozen=True)
class PowerStatus:
    plugged_in: bool | None  # None = desconocido
    has_battery: bool
    charging: bool
    battery_percent: int | None
    seconds_left: int | None  # solo con batería
    battery_saver_on: bool

    @property
    def source(self) -> str:
        if self.plugged_in is None:
            return "desconocido"
        return "corriente (AC)" if self.plugged_in else "batería (DC)"


def read_power_status() -> PowerStatus:
    status = _SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return PowerStatus(None, False, False, None, None, False)

    ac = {0: False, 1: True}.get(status.ACLineStatus)  # 255 = desconocido
    flag = status.BatteryFlag
    has_battery = flag != 255 and not (flag & 128)  # 128 = sin batería de sistema
    percent = status.BatteryLifePercent if status.BatteryLifePercent <= 100 else None
    seconds = status.BatteryLifeTime if status.BatteryLifeTime != 0xFFFFFFFF else None
    return PowerStatus(
        plugged_in=ac,
        has_battery=has_battery,
        charging=bool(flag & 8),
        battery_percent=percent if has_battery else None,
        seconds_left=seconds if has_battery else None,
        battery_saver_on=bool(status.SystemStatusFlag),
    )


# --- Plan de energía activo -------------------------------------------------

_GUID_RE = re.compile(r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})\s*\(([^)]*)\)")

# GUIDs estándar de Windows (los nombres visibles dependen del idioma, los GUID no).
KNOWN_SCHEMES = {
    "381b4222-f694-41f0-9685-ff5bb260df2e": "Equilibrado",
    "a1841308-3541-4fab-bc81-f71556f20b4a": "Economizador",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "Alto rendimiento",
    "e9a42b02-d5df-448d-aa00-03f14749eb61": "Máximo rendimiento",
}


def parse_scheme_line(line: str) -> tuple[str, str] | None:
    """Extrae (guid, nombre) de una línea de powercfg, en cualquier idioma."""
    m = _GUID_RE.search(line)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip()


def active_power_scheme() -> tuple[str, str] | None:
    try:
        return parse_scheme_line(run(["powercfg", "/getactivescheme"], timeout=10))
    except Exception:
        return None
