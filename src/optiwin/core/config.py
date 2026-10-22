"""Configuración editable por el usuario (config.json). Local; nada se envía a ningún sitio."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "auto_switch": {
        "enabled": False,
        "on_ac": "colegio",
        "on_battery": "rendimiento_bateria",
    },
    # Procesos que se cierran al ACTIVAR (a mano) un perfil. Editable con `optiwin close ...`.
    "close_processes": {
        "juegos": ["OneDrive.exe", "Teams.exe", "ms-teams.exe", "Skype.exe", "PhoneExperienceHost.exe"],
        "colegio": ["Steam.exe", "EpicGamesLauncher.exe", "Discord.exe"],
    },
    # None = aún no se le ha preguntado al usuario; True/False = su respuesta
    "updates": {"check_on_start": None},
    "close_force": False,  # False = solo cierre amable (como pulsar la X); True = terminar a la fuerza
    "gpu_apps": [],  # rutas completas de .exe con GPU dedicada
}


class Config:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            os.replace(self.path, self.path.with_suffix(".corrupt.json"))
            return
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                self.data[key].update(value)
            else:
                self.data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- accesos ---------------------------------------------------------------------
    @property
    def auto_switch(self) -> dict[str, Any]:
        return self.data["auto_switch"]

    @property
    def gpu_apps(self) -> list[str]:
        return self.data["gpu_apps"]

    def close_list(self, profile_id: str) -> list[str]:
        return self.data["close_processes"].setdefault(profile_id, [])

    @property
    def close_force(self) -> bool:
        return bool(self.data["close_force"])
