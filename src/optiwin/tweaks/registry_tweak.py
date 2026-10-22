"""Ajuste genérico basado en un valor del registro (DWORD o cadena)."""

from __future__ import annotations

import winreg
from typing import Any

from optiwin.tweaks.base import Risk, Tweak

_HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
_SUPPORTED_TYPES = (winreg.REG_DWORD, winreg.REG_SZ)


class RegistryValueTweak(Tweak):
    def __init__(
        self,
        *,
        id: str,
        name: str,
        category: str,
        description: str,
        risk: Risk,
        benefit: str,
        hive: str,
        key: str,
        value_name: str,
        default_value: int | str,
        reg_type: int = winreg.REG_DWORD,
        reboot_required: bool = False,
    ):
        if hive not in _HIVES:
            raise ValueError(f"Hive no soportado: {hive}")
        if reg_type not in _SUPPORTED_TYPES:
            raise ValueError("Solo REG_DWORD y REG_SZ (para que el original sea serializable)")
        self.id, self.name, self.category = id, name, category
        self.description, self.risk, self.benefit = description, risk, benefit
        self.hive, self.key, self.value_name = hive, key, value_name
        self.default_value, self.reg_type = default_value, reg_type
        self.reboot_required = reboot_required
        self.requires_admin = hive == "HKLM"
        self.admin_reason = "Modifica una clave de todo el equipo (HKLM)." if self.requires_admin else ""

    @property
    def location(self) -> str:
        return f"{self.hive}\\{self.key}\\{self.value_name}"

    def read(self) -> dict[str, Any]:
        try:
            with winreg.OpenKey(_HIVES[self.hive], self.key, 0, winreg.KEY_READ) as k:
                data, typ = winreg.QueryValueEx(k, self.value_name)
        except FileNotFoundError:
            return {"exists": False}
        if typ not in _SUPPORTED_TYPES:
            raise RuntimeError(f"{self.location} tiene un tipo de dato no soportado ({typ}); no se toca.")
        return {"exists": True, "type": typ, "data": data}

    def apply(self, value: Any) -> None:
        with winreg.CreateKeyEx(_HIVES[self.hive], self.key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, self.value_name, 0, self.reg_type, value)

    def restore(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("exists"):
            with winreg.CreateKeyEx(_HIVES[self.hive], self.key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, self.value_name, 0, snapshot["type"], snapshot["data"])
            return
        # No existía: lo correcto es borrarlo, no ponerlo a 0.
        try:
            with winreg.OpenKey(_HIVES[self.hive], self.key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, self.value_name)
        except FileNotFoundError:
            pass

    def matches(self, snapshot: dict[str, Any], value: Any) -> bool:
        return bool(snapshot.get("exists")) and snapshot.get("data") == value

    def summarize(self, snapshot: dict[str, Any]) -> str:
        return str(snapshot["data"]) if snapshot.get("exists") else "(sin definir)"
