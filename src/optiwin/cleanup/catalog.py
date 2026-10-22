"""Catálogo de categorías de limpieza. Solo rutas de caché/temporales de Windows y navegadores.

Jamás se incluyen: Documentos, Escritorio, Descargas, Imágenes, cookies, historial, contraseñas,
sesiones guardadas ni datos de aplicaciones.
"""

from __future__ import annotations

import os
from pathlib import Path

from optiwin.cleanup.categories import Category, FileCategory, RecycleBinCategory
from optiwin.tweaks.base import Risk


def _env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _local() -> Path:
    return _env("LOCALAPPDATA") or Path.home() / "AppData" / "Local"


def _roaming() -> Path:
    return _env("APPDATA") or Path.home() / "AppData" / "Roaming"


def _windir() -> Path:
    return _env("SystemRoot") or Path(r"C:\Windows")


def _programdata() -> Path:
    return _env("ProgramData") or Path(r"C:\ProgramData")


# -- navegadores ----------------------------------------------------------------------------------

_CHROMIUM_CACHE_DIRS = ("Cache", "Code Cache", "GPUCache")  # nunca Network/, Cookies, History, Login Data


def _chromium_roots(user_data: Path) -> list[Path]:
    if not user_data.is_dir():
        return []
    roots = []
    for profile in user_data.iterdir():
        if profile.is_dir() and (profile.name == "Default" or profile.name.startswith("Profile ")):
            roots += [profile / sub for sub in _CHROMIUM_CACHE_DIRS]
    return roots


def _firefox_roots() -> list[Path]:
    profiles = _local() / "Mozilla" / "Firefox" / "Profiles"
    return [p / "cache2" for p in profiles.iterdir() if p.is_dir()] if profiles.is_dir() else []


def _browser(id_: str, name: str, roots_fn, process: str) -> FileCategory:
    return FileCategory(
        id=id_,
        name=f"Caché de {name}",
        description=(
            f"Archivos de caché de {name} (imágenes y scripts de webs). No toca cookies, historial, "
            "contraseñas ni sesiones. Las webs cargarán algo más lento la primera vez."
        ),
        roots_fn=roots_fn,
        running_processes=(process,),
    )


# -- categorías ------------------------------------------------------------------------------------

def build_categories() -> list[Category]:
    local, roaming, windir, pdata = _local(), _roaming(), _windir(), _programdata()
    temp_user = Path(os.environ.get("TEMP") or local / "Temp")

    cats: list[Category] = [
        FileCategory(
            id="temp_usuario",
            name="Archivos temporales del usuario",
            description=(
                "Carpeta %TEMP%. Solo archivos con más de 7 días sin modificar (como el Liberador de espacio de "
                "Windows). Programas y herramientas guardan aquí trabajo en curso: revisa el desglose con "
                "'clean scan --detalle'. La carpeta 'claude' (espacio de trabajo de Claude) está protegida."
            ),
            roots_fn=lambda: [temp_user],
            risk=Risk.MEDIUM,
            min_age_hours=24 * 7,
            exclude_top_level=("claude",),
        ),
        FileCategory(
            id="temp_windows",
            name="Archivos temporales de Windows",
            description="C:\\Windows\\Temp. Solo archivos con más de 7 días sin modificar.",
            roots_fn=lambda: [windir / "Temp"],
            requires_admin=True,
            min_age_hours=24 * 7,
        ),
        FileCategory(
            id="windows_update",
            name="Caché de Windows Update",
            description=(
                "Paquetes ya descargados en SoftwareDistribution\\Download (más de 3 días). Windows Update "
                "seguirá funcionando y los volverá a descargar si hacen falta. No se desactiva ningún servicio."
            ),
            roots_fn=lambda: [windir / "SoftwareDistribution" / "Download"],
            requires_admin=True,
            risk=Risk.MEDIUM,
            min_age_hours=72,
        ),
        RecycleBinCategory(),
        FileCategory(
            id="miniaturas",
            name="Caché de miniaturas",
            description=(
                "thumbcache_*.db del Explorador. Windows las regenera solas. Algunas están abiertas por el "
                "Explorador y no se borrarán hasta reiniciar."
            ),
            roots_fn=lambda: [local / "Microsoft" / "Windows" / "Explorer"],
            include=lambda n: n.lower().startswith("thumbcache_") and n.lower().endswith(".db"),
            recursive=False,
        ),
        FileCategory(
            id="registros_usuario",
            name="Volcados e informes de error del usuario",
            description="CrashDumps y cola/archivo de informes de errores de Windows (WER) del usuario.",
            roots_fn=lambda: [
                local / "CrashDumps",
                local / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                local / "Microsoft" / "Windows" / "WER" / "ReportQueue",
            ],
        ),
        FileCategory(
            id="registros_sistema",
            name="Registros e informes de error del sistema",
            description="Minidump, informes WER del sistema y registros CBS con más de 14 días.",
            roots_fn=lambda: [
                windir / "Minidump",
                pdata / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                pdata / "Microsoft" / "Windows" / "WER" / "ReportQueue",
                windir / "Logs" / "CBS",
            ],
            requires_admin=True,
            min_age_hours=24 * 14,
        ),
        _browser("cache_chrome", "Google Chrome", lambda: _chromium_roots(local / "Google" / "Chrome" / "User Data"), "chrome.exe"),
        _browser("cache_edge", "Microsoft Edge", lambda: _chromium_roots(local / "Microsoft" / "Edge" / "User Data"), "msedge.exe"),
        _browser("cache_brave", "Brave", lambda: _chromium_roots(local / "BraveSoftware" / "Brave-Browser" / "User Data"), "brave.exe"),
        _browser("cache_firefox", "Firefox", _firefox_roots, "firefox.exe"),
        _browser(
            "cache_opera",
            "Opera",
            lambda: [roaming / "Opera Software" / "Opera Stable" / sub for sub in _CHROMIUM_CACHE_DIRS]
            + [roaming / "Opera Software" / "Opera GX Stable" / sub for sub in _CHROMIUM_CACHE_DIRS],
            "opera.exe",
        ),
    ]
    return cats
