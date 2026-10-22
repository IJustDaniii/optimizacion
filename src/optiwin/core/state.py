"""Estado persistente: valor original de cada ajuste aplicado (base de "Deshacer")."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"version": STATE_VERSION, "restore_point": None, "applied": {}}
        self._load()

    # -- E/S ---------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("applied"), dict):
                self.data.update(loaded)
        except (OSError, json.JSONDecodeError):
            # Estado corrupto: lo apartamos en vez de perderlo en silencio.
            backup = self.path.with_suffix(".corrupt.json")
            os.replace(self.path, backup)

    def save(self) -> None:
        """Escritura atómica: si se corta la luz a mitad no se pierden los originales."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- Ajustes aplicados -----------------------------------------------------
    @property
    def applied(self) -> dict[str, dict[str, Any]]:
        return self.data["applied"]

    def record(self, tweak_id: str, original: Any, value: Any) -> None:
        """Guarda el original SOLO la primera vez; reaplicar con otro valor no lo pisa."""
        previous = self.applied.get(tweak_id)
        if previous:
            seq = previous["seq"]
        else:
            seq = self.data.get("next_seq", 1)
            self.data["next_seq"] = seq + 1
        self.applied[tweak_id] = {
            "seq": seq,  # orden de aplicación fiable (el reloj tiene resolución de 1 s)
            "original": previous["original"] if previous else original,
            "value": value,
            "applied_at": previous["applied_at"] if previous else _now(),
            "updated_at": _now(),
        }
        self.save()

    def forget(self, tweak_id: str) -> None:
        self.applied.pop(tweak_id, None)
        self.save()

    # -- Perfil activo -----------------------------------------------------------
    @property
    def active_profile(self) -> dict[str, Any] | None:
        """{'id': perfil, 'owned': [ids de ajustes que el perfil aplicó], 'closed_exes': [rutas]}"""
        return self.data.get("active_profile")

    def set_active_profile(self, info: dict[str, Any] | None) -> None:
        self.data["active_profile"] = info
        self.save()

    # -- Punto de restauración -------------------------------------------------
    @property
    def restore_point(self) -> dict[str, Any] | None:
        return self.data.get("restore_point")

    def set_restore_point(self, info: dict[str, Any]) -> None:
        self.data["restore_point"] = {**info, "recorded_at": _now()}
        self.save()
