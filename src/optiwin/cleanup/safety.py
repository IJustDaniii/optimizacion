"""Barreras de seguridad de la limpieza. Se aplican al DEFINIR una categoría y otra vez al BORRAR.

Reglas:
  * Solo se borra dentro de carpetas raíz explícitas de cada categoría.
  * Una raíz nunca puede ser una unidad, el perfil del usuario, Windows, Archivos de programa,
    ni estar dentro de Documentos, Escritorio, Descargas, Imágenes, Música, Vídeos u OneDrive.
  * Nunca se siguen enlaces simbólicos ni uniones (junctions): podrían apuntar fuera de la raíz.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

PERSONAL_NAMES = frozenset(
    {
        "documents", "documentos", "desktop", "escritorio", "downloads", "descargas",
        "pictures", "imágenes", "imagenes", "music", "música", "musica", "videos", "vídeos",
        "contacts", "contactos", "favorites", "favoritos", "saved games", "partidas guardadas",
    }
)


class UnsafePath(ValueError):
    pass


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(os.path.realpath(value)) if value else None


def _protected_exact() -> set[str]:
    paths = [
        _env_path("USERPROFILE"), _env_path("SystemRoot"), _env_path("ProgramFiles"),
        _env_path("ProgramFiles(x86)"), _env_path("ProgramData"), _env_path("PUBLIC"),
        _env_path("SystemRoot") and _env_path("SystemRoot") / "System32",
    ]
    return {os.path.normcase(str(p)) for p in paths if p}


def assert_safe_root(root: Path | str) -> Path:
    """Devuelve la ruta real de la raíz o lanza UnsafePath."""
    raw = Path(root)
    if not raw.is_absolute():
        raise UnsafePath(f"La raíz debe ser absoluta: {root}")
    real = Path(os.path.realpath(raw))
    if len(real.parts) < 3:  # C:\  o  C:\Users
        raise UnsafePath(f"Raíz demasiado general: {real}")
    if os.path.normcase(str(real)) in _protected_exact():
        raise UnsafePath(f"Raíz protegida: {real}")
    profile = _env_path("USERPROFILE")
    if profile and (real == profile or real in profile.parents):
        raise UnsafePath(f"La raíz es o contiene el perfil del usuario: {real}")
    for part in real.parts[1:]:
        lowered = part.lower()
        if lowered in PERSONAL_NAMES or lowered.startswith("onedrive"):
            raise UnsafePath(f"La raíz está en una carpeta personal ({part}): {real}")
    return real


def is_reparse_point(st: os.stat_result) -> bool:
    """Enlaces simbólicos, uniones y marcadores de OneDrive: nunca se atraviesan."""
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def is_within(path: str | Path, root_real: Path) -> bool:
    """¿`path` (resuelto) está estrictamente dentro de `root_real`?"""
    try:
        real = os.path.normcase(os.path.realpath(path))
        root = os.path.normcase(str(root_real))
        return real != root and os.path.commonpath([real, root]) == root
    except ValueError:
        return False
