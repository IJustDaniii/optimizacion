"""Rutas de datos de la aplicación (estado, logs, copias)."""

from __future__ import annotations

import os
from pathlib import Path


def app_home() -> Path:
    """Carpeta de datos de OptiWin. Se puede cambiar con OPTIWIN_HOME (usado en tests)."""
    override = os.environ.get("OPTIWIN_HOME")
    if override:
        base = Path(override)
    else:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(local) / "OptiWin"
    base.mkdir(parents=True, exist_ok=True)
    return base
