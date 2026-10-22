"""Motor de ajustes reversibles.

Garantías:
  * Antes del PRIMER cambio real se crea un punto de restauración (o se aborta).
  * Se guarda el valor original antes de tocar nada; "Deshacer" lo devuelve tal cual.
  * Modo simulación (dry_run): no cambia ni guarda nada.
  * Todo queda en el log.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from optiwin.core.restore_point import RestorePointResult, create_restore_point
from optiwin.core.state import StateStore
from optiwin.core.winutil import is_admin
from optiwin.tweaks.base import Tweak


@dataclass(frozen=True)
class Result:
    tweak_id: str
    status: str  # applied | dry_run | reverted | skipped | error
    message: str
    reboot_required: bool = False
    needs_admin: bool = False  # el error se debe a que falta elevar

    @property
    def ok(self) -> bool:
        return self.status != "error"


@dataclass(frozen=True)
class TweakStatus:
    tweak: Tweak
    applied: bool
    applied_at: str | None
    current: str  # texto legible del estado actual (o el error al leerlo)
    available: bool
    unavailable_reason: str


class Engine:
    def __init__(
        self,
        catalog: dict[str, Tweak],
        store: StateStore,
        log: logging.Logger,
        *,
        admin_check: Callable[[], bool] = is_admin,
        restore_point_fn: Callable[[], RestorePointResult] = create_restore_point,
    ):
        self.catalog, self.store, self.log = catalog, store, log
        self._is_admin = admin_check
        self._create_restore_point = restore_point_fn

    # -- consulta ------------------------------------------------------------------
    def status(self) -> list[TweakStatus]:
        rows = []
        for tweak in self.catalog.values():
            ok, why = tweak.is_available()
            try:
                current = tweak.summarize(tweak.read()) if ok else "—"
            except Exception as exc:
                current = f"(error al leer: {exc})"
            entry = self.store.applied.get(tweak.id)
            rows.append(TweakStatus(tweak, entry is not None, entry["applied_at"] if entry else None, current, ok, why))
        return rows

    # -- aplicar ---------------------------------------------------------------------
    def apply(
        self, tweak_id: str, value: Any = None, *, dry_run: bool = False, skip_restore_point: bool = False
    ) -> Result:
        tweak = self.catalog.get(tweak_id)
        if tweak is None:
            return Result(tweak_id, "error", f"No existe el ajuste '{tweak_id}'.")
        value = tweak.default_value if value is None else value

        available, why = tweak.is_available()
        if not available:
            return Result(tweak_id, "error", why)
        try:
            before = tweak.read()
        except Exception as exc:
            return self._fail(tweak_id, f"No se pudo leer el estado actual: {exc}")

        change = f"{tweak.name}: {tweak.summarize(before)} → {value}"

        if dry_run:
            if tweak.matches(before, value):
                return Result(tweak_id, "skipped", f"Ya tiene ese valor, no cambiaría nada ({tweak.name}: {value}).")
            extra = []
            if tweak.requires_admin:
                extra.append(f"requeriría administrador ({tweak.admin_reason})")
            if tweak.reboot_required:
                extra.append("requiere reiniciar")
            suffix = f" [{'; '.join(extra)}]" if extra else ""
            self.log.info("SIMULACION %s | %s", tweak_id, change)
            return Result(tweak_id, "dry_run", f"Cambiaría {change}{suffix}")

        if tweak.matches(before, value):
            return Result(tweak_id, "skipped", f"Ya tiene ese valor, no hay nada que cambiar ({tweak.name}: {value}).")

        if tweak.requires_admin and not self._is_admin():
            return Result(
                tweak_id, "error", f"Necesita administrador: {tweak.admin_reason}", needs_admin=True
            )

        problem = self.ensure_restore_point(skip_restore_point)
        if problem:
            return problem

        try:
            tweak.apply(value)
            after = tweak.read()
        except Exception as exc:
            return self._fail(tweak_id, f"Falló al aplicar: {exc}")

        # El original se guarda aunque la verificación falle, para poder deshacer siempre.
        self.store.record(tweak_id, before, value)
        verified = tweak.matches(after, value)
        self.log.log(
            logging.INFO if verified else logging.WARNING,
            "APLICADO %s | %s | verificado=%s",
            tweak_id,
            change,
            verified,
        )
        note = "" if verified else " (aviso: el valor leído después no coincide; Windows u otro programa puede haberlo cambiado)"
        reboot = " Requiere reiniciar para surtir efecto." if tweak.reboot_required else ""
        return Result(tweak_id, "applied", f"Aplicado {change}.{note}{reboot}", tweak.reboot_required)

    def ensure_restore_point(self, skip: bool = False) -> Result | None:
        """None = todo en orden (ya existe, se acaba de crear u omitido a petición); Result = error."""
        if self.store.restore_point is not None:
            return None
        if skip:
            self.log.warning("PUNTO DE RESTAURACION OMITIDO por el usuario (primer cambio sin red de seguridad)")
            return None
        if not self._is_admin():
            return Result(
                "-",
                "error",
                "Antes del primer cambio hay que crear un punto de restauración, y Windows solo "
                "permite crearlo con permisos de administrador. Repite con --elevar, o con "
                "--sin-punto-restauracion asumiendo que no habrá copia de seguridad del sistema "
                "(los ajustes de OptiWin seguirán siendo reversibles).",
                needs_admin=True,
            )
        result = self._create_restore_point()
        self.log.info("PUNTO DE RESTAURACION | ok=%s creado=%s | %s", result.ok, result.created, result.message)
        if not result.ok:
            return Result("-", "error", result.message)
        self.store.set_restore_point({"created": result.created, "detail": result.message})
        return None

    # -- deshacer ----------------------------------------------------------------------
    def revert(self, tweak_id: str) -> Result:
        tweak = self.catalog.get(tweak_id)
        entry = self.store.applied.get(tweak_id)
        if tweak is None:
            return Result(tweak_id, "error", f"No existe el ajuste '{tweak_id}'.")
        if entry is None:
            return Result(tweak_id, "skipped", "OptiWin no había aplicado este ajuste; nada que deshacer.")
        if tweak.requires_admin and not self._is_admin():
            return Result(tweak_id, "error", f"Necesita administrador: {tweak.admin_reason}", needs_admin=True)

        try:
            drift = not tweak.matches(tweak.read(), entry["value"])
            tweak.restore(entry["original"])
            after = tweak.read()
        except Exception as exc:
            return self._fail(tweak_id, f"Falló al deshacer (el original sigue guardado): {exc}")

        if drift:
            self.log.warning("DESHACER %s | el valor había cambiado desde que se aplicó; se restaura igualmente", tweak_id)
        self.store.forget(tweak_id)
        self.log.info("REVERTIDO %s | %s | restaurado a %s", tweak_id, tweak.name, tweak.summarize(after))
        return Result(tweak_id, "reverted", f"Deshecho {tweak.name}: restaurado a {tweak.summarize(after)}.", tweak.reboot_required)

    def revert_all(self) -> list[Result]:
        """Deshace todo en orden inverso al de aplicación. Un fallo no detiene el resto."""
        order = sorted(self.store.applied, key=lambda i: self.store.applied[i]["seq"], reverse=True)
        self.log.info("RESTAURAR TODO | %d ajustes", len(order))
        return [self.revert(i) for i in order]

    def _fail(self, tweak_id: str, message: str) -> Result:
        self.log.error("ERROR %s | %s", tweak_id, message)
        return Result(tweak_id, "error", message)
