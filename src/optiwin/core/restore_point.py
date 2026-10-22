"""Punto de restauración de Windows (necesita administrador y Protección del sistema activa)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from optiwin.core.winutil import powershell_json

DESCRIPTION = "OptiWin - antes de aplicar cambios"

# Windows crea como máximo un punto cada 24 h; si hay uno más reciente, Checkpoint-Computer
# lo omite sin error. Por eso comparamos números de secuencia antes y después.
_SCRIPT = r"""
$ErrorActionPreference='Stop'
function Last-Rp { Get-ComputerRestorePoint -ErrorAction SilentlyContinue | Sort-Object SequenceNumber | Select-Object -Last 1 }
$err = $null
$before = Last-Rp
try { Checkpoint-Computer -Description '__DESC__' -RestorePointType MODIFY_SETTINGS -WarningAction SilentlyContinue }
catch { $err = $_.Exception.Message }
$after = Last-Rp
function Iso($rp) { if ($rp) { [Management.ManagementDateTimeConverter]::ToDateTime($rp.CreationTime).ToString('s') } else { $null } }
[pscustomobject]@{
  before_seq = if ($before) { [int]$before.SequenceNumber } else { 0 }
  after_seq  = if ($after)  { [int]$after.SequenceNumber }  else { 0 }
  latest_time = Iso $after
  error = $err
} | ConvertTo-Json -Compress
"""


@dataclass(frozen=True)
class RestorePointResult:
    ok: bool
    created: bool  # True = lo creamos ahora; False + ok = ya había uno reciente
    message: str


def interpret_result(
    before_seq: int, after_seq: int, latest_time: str | None, error: str | None, now: datetime | None = None
) -> RestorePointResult:
    """Decide qué pasó a partir de lo que devolvió PowerShell (lógica pura, testeable)."""
    if after_seq > before_seq:
        return RestorePointResult(True, True, "Punto de restauración creado.")
    if latest_time:
        age = (now or datetime.now()) - datetime.fromisoformat(latest_time)
        if age < timedelta(hours=24):
            return RestorePointResult(
                True,
                False,
                "Windows no crea más de un punto cada 24 h; se usa el existente "
                f"(creado hace {int(age.total_seconds() // 3600)} h).",
            )
    reason = error or "causa desconocida"
    return RestorePointResult(
        False,
        False,
        f"No se pudo crear el punto de restauración ({reason}). "
        "Comprueba que la Protección del sistema está activada para la unidad C:.",
    )


def create_restore_point(description: str = DESCRIPTION) -> RestorePointResult:
    try:
        raw = powershell_json(_SCRIPT.replace("__DESC__", description.replace("'", "")), timeout=180) or {}
    except Exception as exc:  # PowerShell no disponible, timeout...
        return RestorePointResult(False, False, f"No se pudo ejecutar PowerShell: {exc}")
    return interpret_result(
        int(raw.get("before_seq") or 0),
        int(raw.get("after_seq") or 0),
        raw.get("latest_time"),
        raw.get("error"),
    )
