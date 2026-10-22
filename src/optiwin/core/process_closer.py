"""Cierre de procesos en segundo plano (lista editable).

Seguridad:
  * Solo procesos del usuario actual; nunca procesos de sistema, Defender ni el propio OptiWin.
  * Cierre amable por defecto (equivale a pulsar la X). Terminar a la fuerza es opcional.
  * No es "deshacible" como un ajuste, pero se guarda la ruta del .exe para poder reabrirlo.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

# Nunca se cierran, aunque estén en la lista. (minúsculas, sin .exe)
PROTECTED = frozenset(
    {
        "system", "registry", "smss", "csrss", "wininit", "services", "lsass", "lsaiso", "winlogon",
        "svchost", "dwm", "explorer", "fontdrvhost", "sihost", "taskhostw", "ctfmon", "runtimebroker",
        "shellexperiencehost", "startmenuexperiencehost", "searchhost", "searchindexer", "textinputhost",
        "msmpeng", "nissrv", "securityhealthservice", "securityhealthsystray", "mpdefendercoreservice",
        "wudfhost", "audiodg", "spoolsv", "dllhost", "conhost", "cmd", "powershell", "pwsh",
        "python", "pythonw", "optiwin", "windowsterminal", "taskmgr", "msedgewebview2",
        "nvdisplay.container", "nvcontainer", "amdrsserv", "radeonsoftware",
    }
)


class InvalidProcessName(ValueError):
    pass


def normalize_name(name: str) -> str:
    """Valida y devuelve 'Nombre.exe'. Rechaza rutas, comodines y procesos protegidos."""
    name = name.strip()
    if not name or any(c in name for c in '\\/:*?"<>|'):
        raise InvalidProcessName("Indica solo el nombre del proceso, por ejemplo: Discord.exe")
    if not name.lower().endswith(".exe"):
        name += ".exe"
    if Path(name).stem.lower() in PROTECTED:
        raise InvalidProcessName(f"{name} es un proceso protegido y no se puede añadir.")
    return name


@dataclass(frozen=True)
class RunningProcess:
    pid: int
    name: str
    exe: str | None


def find_running(names: list[str]) -> list[RunningProcess]:
    wanted = {n.lower() for n in names if Path(n).stem.lower() not in PROTECTED}
    me = os.getpid()
    user = getpass.getuser().lower()
    found = []
    for proc in psutil.process_iter(["pid", "name", "exe", "username"]):
        info = proc.info
        if info["pid"] == me or not info["name"] or info["name"].lower() not in wanted:
            continue
        owner = (info["username"] or "").split("\\")[-1].lower()
        if owner != user:  # nunca procesos de otros usuarios ni del sistema
            continue
        found.append(RunningProcess(info["pid"], info["name"], info["exe"]))
    return found


@dataclass(frozen=True)
class CloseReport:
    closed: list[RunningProcess]
    survivors: list[RunningProcess]


def close_processes(procs: list[RunningProcess], *, force: bool = False, wait: float = 4.0) -> CloseReport:
    for p in procs:
        cmd = ["taskkill", "/PID", str(p.pid)] + (["/F"] if force else [])
        subprocess.run(cmd, capture_output=True, creationflags=0x08000000)
    deadline = time.monotonic() + wait
    alive = {p.pid for p in procs}
    while alive and time.monotonic() < deadline:
        alive = {pid for pid in alive if psutil.pid_exists(pid)}
        if alive:
            time.sleep(0.25)
    return CloseReport(
        closed=[p for p in procs if p.pid not in alive],
        survivors=[p for p in procs if p.pid in alive],
    )


def reopen(exe_paths: list[str]) -> list[str]:
    """Vuelve a lanzar los programas (solo el .exe, sin argumentos). Devuelve los que fallaron."""
    failed = []
    for exe in exe_paths:
        try:
            subprocess.Popen([exe], close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS
        except OSError:
            failed.append(exe)
    return failed
