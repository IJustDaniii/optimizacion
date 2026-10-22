from __future__ import annotations

import hashlib
import winreg
from pathlib import PureWindowsPath

from optiwin.tweaks.base import Risk, Tweak
from optiwin.tweaks.registry_tweak import RegistryValueTweak

GPU_PREFS_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
GPU_ID_PREFIX = "juegos.gpu."


def gpu_tweak_id(exe_path: str) -> str:
    # El hash evita colisiones entre dos juegos con el mismo nombre de .exe en rutas distintas.
    digest = hashlib.sha1(exe_path.lower().encode("utf-8")).hexdigest()[:6]
    return f"{GPU_ID_PREFIX}{PureWindowsPath(exe_path).name.lower()}.{digest}"


def gpu_app_tweak(exe_path: str) -> RegistryValueTweak:
    """Prioridad de GPU de alto rendimiento para un ejecutable (equivale a Configuración > Gráficos)."""
    name = PureWindowsPath(exe_path).name
    return RegistryValueTweak(
        id=gpu_tweak_id(exe_path),
        name=f"GPU dedicada para {name}",
        category="juegos",
        description=(
            f"Indica a Windows que {name} use la GPU de alto rendimiento (la dedicada) en lugar de la "
            "integrada. En un portátil con gráficos híbridos evita jugar con la GPU equivocada. "
            "Es el mismo ajuste que Configuración > Sistema > Pantalla > Gráficos."
        ),
        risk=Risk.LOW,
        benefit="Notable en portátiles híbridos si el juego no elige la GPU dedicada solo; nulo si solo hay una GPU.",
        hive="HKCU",
        key=GPU_PREFS_KEY,
        value_name=exe_path,
        reg_type=winreg.REG_SZ,
        default_value="GpuPreference=2;",
    )


def tweaks() -> list[Tweak]:
    return [
        RegistryValueTweak(
            id="juegos.modo_juego",
            name="Modo Juego de Windows",
            category="juegos",
            description=(
                "Activa el Modo Juego: Windows prioriza el juego en primer plano y evita que "
                "Windows Update instale drivers o muestre avisos de reinicio mientras juegas."
            ),
            risk=Risk.LOW,
            benefit="Leve: menos tirones por tareas de fondo.",
            hive="HKCU",
            key=r"Software\Microsoft\GameBar",
            value_name="AutoGameModeEnabled",
            default_value=1,
        ),
        RegistryValueTweak(
            id="juegos.hags",
            name="Programación de GPU acelerada por hardware (HAGS)",
            category="juegos",
            description=(
                "Deja que la propia GPU gestione su memoria y planificación en vez de la CPU. "
                "2 = activado, 1 = desactivado. Requiere GPU y driver compatibles."
            ),
            risk=Risk.MEDIUM,
            benefit=(
                "Variable: mejora ligeramente la latencia en algunos juegos y empeora otros. "
                "Por eso no va en ningún perfil: pruébalo tú."
            ),
            hive="HKLM",
            key=r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
            value_name="HwSchMode",
            default_value=2,
            reboot_required=True,
        ),
    ]
