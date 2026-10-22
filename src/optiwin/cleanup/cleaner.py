"""Orquestador de limpieza: analizar (vista previa) y borrar solo lo analizado y confirmado."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from optiwin.cleanup.categories import Category, CleanReport, ScanResult
from optiwin.core.winutil import is_admin


@dataclass
class Plan:
    """Vista previa: lo que hay en cada categoría en el momento del análisis."""

    scans: dict[str, ScanResult] = field(default_factory=dict)
    blocked: dict[str, str] = field(default_factory=dict)  # categoría -> motivo por el que no se puede limpiar
    warnings: dict[str, str] = field(default_factory=dict)

    @property
    def total_bytes(self) -> int:
        return sum(s.total_bytes for s in self.scans.values())


class ConfirmationRequired(RuntimeError):
    pass


class Cleaner:
    def __init__(
        self,
        categories: list[Category],
        home: Path,
        log: logging.Logger,
        *,
        admin_check: Callable[[], bool] = is_admin,
        running_names: Callable[[], set[str]] | None = None,
    ):
        self.categories = {c.id: c for c in categories}
        self.home, self.log = home, log
        self._is_admin = admin_check
        self._running_names = running_names or self._default_running

    @staticmethod
    def _default_running() -> set[str]:
        return {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}

    # -- 1. vista previa ------------------------------------------------------------------
    def scan(self, ids: list[str] | None = None, progress: Callable[[str], None] | None = None) -> Plan:
        plan = Plan()
        running = self._running_names()
        for cat in self._select(ids):
            if not cat.is_available():
                continue  # p. ej. un navegador que no está instalado
            if progress:
                progress(cat.name)
            plan.scans[cat.id] = cat.scan()
            if cat.requires_admin and not self._is_admin():
                plan.blocked[cat.id] = "requiere administrador"
            procs = getattr(cat, "running_processes", ())
            if any(p.lower() in running for p in procs):
                plan.warnings[cat.id] = "el navegador está abierto: se omitirán los archivos en uso"
        self.log.info(
            "LIMPIEZA ANALISIS | %s | total=%d bytes",
            ", ".join(f"{i}={s.total_bytes}" for i, s in plan.scans.items()),
            plan.total_bytes,
        )
        return plan

    # -- 2. borrado (solo tras confirmación) -----------------------------------------------------
    def clean(self, plan: Plan, ids: list[str], *, confirmed: bool) -> list[CleanReport]:
        if confirmed is not True:
            raise ConfirmationRequired("El borrado exige confirmación explícita del usuario.")
        reports = []
        manifest_lines: list[str] = []
        for cid in ids:
            cat, scan = self.categories.get(cid), plan.scans.get(cid)
            if cat is None or scan is None:
                continue  # solo se limpia lo que se mostró en la vista previa
            if cid in plan.blocked:
                report = CleanReport(cid, notes=[f"Omitida: {plan.blocked[cid]}"])
            else:
                report = cat.clean(scan)
            reports.append(report)
            manifest_lines += report.deleted_paths
            self.log.info(
                "LIMPIEZA %s | borrados=%d liberado=%d omitidos=%d",
                cid, report.deleted_files, report.freed_bytes, report.skipped,
            )
        self._write_manifest(manifest_lines)
        self.log.info(
            "LIMPIEZA TOTAL | archivos=%d liberado=%d bytes",
            sum(r.deleted_files for r in reports), sum(r.freed_bytes for r in reports),
        )
        return reports

    def _write_manifest(self, paths: list[str]) -> None:
        """Lista de todo lo borrado, para auditoría (solo rutas, ningún contenido)."""
        if not paths:
            return
        folder = self.home / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"limpieza-{time.strftime('%Y%m%d-%H%M%S')}.txt").write_text("\n".join(paths), encoding="utf-8")

    def _select(self, ids: list[str] | None) -> list[Category]:
        if ids is None:
            return list(self.categories.values())
        unknown = [i for i in ids if i not in self.categories]
        if unknown:
            raise KeyError(f"Categorías desconocidas: {', '.join(unknown)}")
        return [self.categories[i] for i in ids]


def format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"
