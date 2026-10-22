"""Activación de perfiles sobre el motor de ajustes.

Cambiar de perfil devuelve a su valor ORIGINAL los ajustes que el perfil anterior tocaba y el
nuevo no, para que cambiar entre perfiles nunca deje restos.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from optiwin.core import process_closer
from optiwin.core.config import Config
from optiwin.core.engine import Engine, Result
from optiwin.profiles.definitions import PROFILES, Profile
from optiwin.tweaks.gaming import gpu_tweak_id


@dataclass
class ActivationReport:
    profile_id: str
    results: list[Result] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def needs_admin(self) -> bool:
        return any(r.needs_admin for r in self.results)


class ProfileManager:
    def __init__(
        self,
        engine: Engine,
        config: Config,
        profiles: dict[str, Profile] = PROFILES,
        *,
        find_running: Callable = process_closer.find_running,
        close_fn: Callable = process_closer.close_processes,
        reopen_fn: Callable = process_closer.reopen,
    ):
        self.engine, self.config, self.profiles = engine, config, profiles
        self._find_running, self._close, self._reopen = find_running, close_fn, reopen_fn

    @property
    def store(self):
        return self.engine.store

    def current(self) -> dict[str, Any] | None:
        return self.store.active_profile

    def steps_for(self, profile: Profile) -> dict[str, Any]:
        steps: dict[str, Any] = dict(profile.steps)
        if profile.include_gpu_apps:
            for exe in self.config.gpu_apps:
                steps[gpu_tweak_id(exe)] = self.engine.catalog[gpu_tweak_id(exe)].default_value
        return steps

    # -- activar -------------------------------------------------------------------------
    def activate(
        self, profile_id: str, *, dry_run: bool = False, close: bool = False, skip_restore_point: bool = False
    ) -> ActivationReport:
        report = ActivationReport(profile_id)
        profile = self.profiles.get(profile_id)
        if profile is None:
            report.results.append(Result(profile_id, "error", f"No existe el perfil '{profile_id}'."))
            return report

        steps = self.steps_for(profile)
        previous = self.current() or {}
        leftovers = [i for i in previous.get("owned", []) if i not in steps]

        if dry_run:
            if self.store.restore_point is None:
                report.notes.append("Antes de aplicar se creará un punto de restauración (requiere administrador).")
        else:
            problem = self.engine.ensure_restore_point(skip_restore_point)
            if problem:
                report.results.append(problem)
                return report

        for tweak_id in leftovers:
            if dry_run:
                report.results.append(Result(tweak_id, "dry_run", f"Se devolvería a su valor original (lo tocaba el perfil '{previous.get('id')}')."))
            else:
                report.results.append(self.engine.revert(tweak_id))

        for tweak_id, value in steps.items():
            tweak = self.engine.catalog.get(tweak_id)
            if tweak is None:
                report.results.append(Result(tweak_id, "error", "El perfil usa un ajuste que no existe."))
                continue
            available, why = tweak.is_available()
            if not available:
                report.results.append(Result(tweak_id, "skipped", f"No disponible en este equipo: {why}"))
                continue
            report.results.append(self.engine.apply(tweak_id, value, dry_run=dry_run, skip_restore_point=True))

        closed_exes = self._handle_closing(profile, report, close=close, dry_run=dry_run)

        if not dry_run:
            applied = self.store.applied
            owned = [i for i in list(steps) + leftovers if i in applied]
            self.store.set_active_profile(
                {
                    "id": profile.id,
                    "owned": owned,
                    "closed_exes": closed_exes,
                    "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
            self.engine.log.info("PERFIL ACTIVADO %s | ajustes propios=%d", profile.id, len(owned))
        return report

    def _handle_closing(self, profile: Profile, report: ActivationReport, *, close: bool, dry_run: bool) -> list[str]:
        if not (close and profile.closes_processes):
            if profile.closes_processes:
                report.notes.append("No se cerró ningún proceso (usa --cerrar para hacerlo; el cambio automático nunca cierra nada).")
            return []
        names = self.config.close_list(profile.id)
        running = self._find_running(names)
        if not running:
            report.notes.append("Ningún proceso de la lista estaba en ejecución.")
            return []
        listing = ", ".join(sorted({p.name for p in running}))
        if dry_run:
            report.notes.append(f"Se cerrarían: {listing}")
            return []
        outcome = self._close(running, force=self.config.close_force)
        report.notes.append(f"Cerrados: {', '.join(sorted({p.name for p in outcome.closed})) or 'ninguno'}")
        if outcome.survivors:
            report.notes.append(
                "No se cerraron sin forzar: " + ", ".join(sorted({p.name for p in outcome.survivors}))
                + " (puedes activar close_force en la configuración)."
            )
        self.engine.log.info("PROCESOS CERRADOS | %s", listing)
        return sorted({p.exe for p in outcome.closed if p.exe})

    # -- desactivar ------------------------------------------------------------------------
    def deactivate(self, *, dry_run: bool = False, reopen: bool = False) -> ActivationReport:
        current = self.current()
        report = ActivationReport(current["id"] if current else "-")
        if not current:
            report.notes.append("No hay ningún perfil activo.")
            return report
        for tweak_id in sorted(current["owned"], key=lambda i: self.store.applied.get(i, {}).get("seq", 0), reverse=True):
            report.results.append(Result(tweak_id, "dry_run", "Se deshará.") if dry_run else self.engine.revert(tweak_id))
        exes = current.get("closed_exes", [])
        if exes:
            if reopen and not dry_run:
                failed = self._reopen(exes)
                report.notes.append(f"Reabiertos {len(exes) - len(failed)} de {len(exes)} programas cerrados.")
            else:
                report.notes.append(f"Se habían cerrado {len(exes)} programas; usa --reabrir para volver a abrirlos.")
        if not dry_run:
            self.store.set_active_profile(None)
            self.engine.log.info("PERFIL DESACTIVADO %s", report.profile_id)
        return report
