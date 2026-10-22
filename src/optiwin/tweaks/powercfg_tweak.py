"""Ajuste genérico de un valor de plan de energía (powercfg), distinto para AC y DC."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from optiwin.core.power_status import active_power_scheme
from optiwin.core.winutil import run
from optiwin.tweaks.base import Risk, Tweak

_HEX_RE = re.compile(r"0x[0-9a-fA-F]{8}")


class SettingUnavailable(RuntimeError):
    """El plan activo no expone este ajuste (p. ej. oculto por el fabricante)."""


def parse_current_values(text: str) -> tuple[int, int]:
    """Devuelve (ac, dc) de la salida de `powercfg /query`.

    Es independiente del idioma: los dos ÚLTIMOS valores hexadecimales de la salida son siempre
    el índice actual de corriente alterna y continua, en ese orden.
    """
    values = _HEX_RE.findall(text)
    if len(values) < 2:
        raise SettingUnavailable("powercfg no devolvió valores para este ajuste")
    return int(values[-2], 16), int(values[-1], 16)


def _powercfg(*args: str) -> str:
    return run(["powercfg", *args], timeout=15)


class PowerCfgSettingTweak(Tweak):
    def __init__(
        self,
        *,
        id: str,
        name: str,
        category: str,
        description: str,
        risk: Risk,
        benefit: str,
        subgroup: str,
        setting: str,
        source: str,  # "ac" | "dc"
        default_value: int,
        unit: str = "",
        min_value: int = 0,
        max_value: int = 100,
        labels: dict[int, str] | None = None,
    ):
        if source not in ("ac", "dc"):
            raise ValueError("source debe ser 'ac' o 'dc'")
        self.id, self.name, self.category = id, name, category
        self.description, self.risk, self.benefit = description, risk, benefit
        self.subgroup, self.setting, self.source = subgroup, setting, source
        self.default_value, self.unit = default_value, unit
        self.min_value, self.max_value = min_value, max_value
        self.labels = labels or {}
        # Comprobado: powercfg modifica los planes del equipo sin necesidad de administrador.
        self.requires_admin = False

    # -- helpers ---------------------------------------------------------------
    def _active_guid(self) -> str:
        scheme = active_power_scheme()
        if not scheme:
            raise RuntimeError("No se pudo determinar el plan de energía activo.")
        return scheme[0]

    def _read_scheme(self, guid: str) -> dict[str, Any]:
        try:
            # /qh (y no /q) también lee los ajustes ocultos, p. ej. el modo de boost de la CPU.
            out = _powercfg("/qh", guid, self.subgroup, self.setting)
        except subprocess.CalledProcessError as exc:
            raise SettingUnavailable(f"powercfg falló (código {exc.returncode})") from exc
        ac, dc = parse_current_values(out)
        return {"scheme": guid, "ac": ac, "dc": dc}

    def _refresh(self, guid: str) -> None:
        """Windows solo aplica el cambio si se reactiva el plan; solo lo hacemos si ya era el activo."""
        if self._active_guid() == guid:
            _powercfg("/setactive", guid)

    # -- contrato ----------------------------------------------------------------
    def read(self) -> dict[str, Any]:
        return self._read_scheme(self._active_guid())

    def is_available(self) -> tuple[bool, str]:
        try:
            self.read()
            return True, ""
        except SettingUnavailable as exc:
            return False, f"Este equipo no expone el ajuste ({exc})."

    def apply(self, value: Any) -> None:
        value = int(value)
        if not self.min_value <= value <= self.max_value:
            raise ValueError(f"Valor fuera de rango ({self.min_value}-{self.max_value}{self.unit})")
        guid = self._active_guid()
        _powercfg(f"/set{self.source}valueindex", guid, self.subgroup, self.setting, str(value))
        self._refresh(guid)

    def restore(self, snapshot: dict[str, Any]) -> None:
        guid = snapshot["scheme"]
        _powercfg(f"/set{self.source}valueindex", guid, self.subgroup, self.setting, str(snapshot[self.source]))
        self._refresh(guid)

    def matches(self, snapshot: dict[str, Any], value: Any) -> bool:
        return snapshot.get(self.source) == int(value)

    def summarize(self, snapshot: dict[str, Any]) -> str:
        value = snapshot[self.source]
        label = f" «{self.labels[value]}»" if value in self.labels else ""
        return f"{value}{self.unit}{label} ({self.source.upper()}, plan {snapshot['scheme'][:8]})"
