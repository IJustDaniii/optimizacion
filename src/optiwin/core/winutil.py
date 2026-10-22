"""Utilidades de bajo nivel: ejecutar comandos, PowerShell y comprobar admin."""

from __future__ import annotations

import ctypes
import json
import subprocess
from typing import Any

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no abrir consolas al empaquetar como .exe


def run(cmd: list[str], timeout: int = 30) -> str:
    """Ejecuta un comando y devuelve su salida (texto). Lanza CalledProcessError si falla.

    Las herramientas de consola de Windows (powercfg...) usan la página de códigos OEM,
    por eso se decodifica con 'oem' y no con utf-8.
    """
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
        check=True,
    )
    return proc.stdout.decode("oem", errors="replace")


def powershell_json(script: str, timeout: int = 60) -> Any:
    """Ejecuta un script de PowerShell y parsea su salida JSON (UTF-8)."""
    prefix = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';"
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", prefix + script],
        capture_output=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
        check=True,
    )
    text = proc.stdout.decode("utf-8", errors="replace").strip()
    return json.loads(text) if text else None


def as_list(value: Any) -> list:
    """ConvertTo-Json devuelve un objeto suelto si solo hay un elemento; lo normaliza."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
