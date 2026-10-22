"""Elevación bajo demanda: se pide administrador solo cuando un ajuste lo necesita."""

from __future__ import annotations

import ctypes
import subprocess
import sys


def relaunch_gui_elevated(extra_args: list[str] | None = None) -> bool:
    """Relanza la interfaz gráfica como administrador (sin consola). False si se rechaza el UAC."""
    extra = extra_args or []
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess.list2cmdline(extra)
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        params = subprocess.list2cmdline(["-m", "optiwin", "gui", *extra])
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32


def relaunch_elevated(args: list[str]) -> bool:
    """Relanza OptiWin con los mismos argumentos pidiendo permisos de administrador (UAC).

    Abre una consola nueva que espera una tecla al terminar para que se pueda leer el resultado.
    Devuelve False si el usuario rechaza el aviso de UAC.
    """
    exe = sys.executable
    cli_args = args if getattr(sys, "frozen", False) else ["-m", "optiwin", *args]
    command = f'/c ""{exe}" {subprocess.list2cmdline(cli_args)} & pause"'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", command, None, 1)
    return result > 32  # <= 32 son códigos de error (5 = el usuario canceló)
