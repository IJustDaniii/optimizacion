"""Categorías de limpieza: qué se puede borrar, dónde y con qué condiciones."""

from __future__ import annotations

import ctypes
import os
import stat
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from optiwin.cleanup.safety import assert_safe_root, is_reparse_point, is_within
from optiwin.tweaks.base import Risk


@dataclass
class ScanResult:
    category_id: str
    files: list[tuple[str, int]] = field(default_factory=list)  # (ruta, tamaño)
    dirs: list[str] = field(default_factory=list)  # subcarpetas candidatas a quedar vacías
    scanned_at: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)
    extra_bytes: int = 0  # categorías sin lista de archivos (papelera)
    extra_items: int = 0
    roots: list[str] = field(default_factory=list)

    def breakdown(self, n: int = 5) -> list[tuple[str, int]]:
        """Tamaño por carpeta de primer nivel: para ver QUÉ hay dentro antes de borrar."""
        sizes: dict[str, int] = {}
        for path, size in self.files:
            root = next((r for r in self.roots if os.path.normcase(path).startswith(os.path.normcase(r) + os.sep)), None)
            if root is None:
                continue
            first = os.path.relpath(path, root).split(os.sep)[0]
            sizes[first] = sizes.get(first, 0) + size
        return sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:n]

    @property
    def total_bytes(self) -> int:
        return sum(size for _, size in self.files) + self.extra_bytes

    @property
    def item_count(self) -> int:
        return len(self.files) + self.extra_items

    def largest(self, n: int = 5) -> list[tuple[str, int]]:
        return sorted(self.files, key=lambda f: f[1], reverse=True)[:n]


@dataclass
class CleanReport:
    category_id: str
    deleted_files: int = 0
    freed_bytes: int = 0
    skipped: int = 0  # en uso, modificados desde el análisis o fuera de la raíz
    deleted_paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Category(ABC):
    id: str
    name: str
    description: str
    risk: Risk = Risk.LOW
    requires_admin: bool = False
    permanent: bool = True  # todo lo que borra OptiWin es definitivo (no va a la papelera)

    @abstractmethod
    def scan(self) -> ScanResult: ...

    @abstractmethod
    def clean(self, scan: ScanResult) -> CleanReport: ...

    def is_available(self) -> bool:
        return True


class FileCategory(Category):
    """Borra archivos dentro de carpetas raíz explícitas.

    - `roots_fn` devuelve las raíces en el momento de analizar (los perfiles de navegador varían).
    - `include(nombre)` filtra por nombre de archivo (p. ej. solo *.dmp).
    - `min_age_hours`: ignora archivos modificados hace menos de ese tiempo (pueden estar en uso).
    """

    def __init__(
        self,
        *,
        id: str,
        name: str,
        description: str,
        roots_fn: Callable[[], list[Path]],
        risk: Risk = Risk.LOW,
        requires_admin: bool = False,
        include: Callable[[str], bool] | None = None,
        min_age_hours: float = 0,
        recursive: bool = True,
        prune_dirs: bool = True,
        running_processes: tuple[str, ...] = (),
        exclude_top_level: tuple[str, ...] = (),
    ):
        self.exclude_top_level = {n.lower() for n in exclude_top_level}
        self.id, self.name, self.description = id, name, description
        self.risk, self.requires_admin = risk, requires_admin
        self._roots_fn, self._include = roots_fn, include
        self.min_age_hours, self.recursive, self.prune_dirs = min_age_hours, recursive, prune_dirs
        self.running_processes = running_processes

    def roots(self) -> list[Path]:
        out = []
        for root in self._roots_fn():
            if root.is_dir():
                out.append(assert_safe_root(root))  # valida SIEMPRE, también las raíces dinámicas
        return out

    def is_available(self) -> bool:
        return bool(self.roots())

    # -- análisis ------------------------------------------------------------------
    def scan(self) -> ScanResult:
        result = ScanResult(self.id)
        cutoff = time.time() - self.min_age_hours * 3600
        too_recent = reparse = denied = 0
        excluded: list[str] = []
        for root in self.roots():
            result.roots.append(str(root))
            stack = [root]
            while stack:
                current = stack.pop()
                try:
                    with os.scandir(current) as it:
                        entries = list(it)
                except OSError:
                    denied += 1
                    continue
                for entry in entries:
                    if current == root and entry.name.lower() in self.exclude_top_level:
                        excluded.append(entry.name)
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        denied += 1
                        continue
                    if is_reparse_point(st):
                        reparse += 1
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if self.recursive:
                            stack.append(Path(entry.path))
                            if self.prune_dirs:
                                result.dirs.append(entry.path)
                        continue
                    if self._include and not self._include(entry.name):
                        continue
                    if st.st_mtime > cutoff:
                        too_recent += 1
                        continue
                    result.files.append((entry.path, st.st_size))
        if too_recent:
            result.notes.append(f"{too_recent} archivos recientes (<{self.min_age_hours:g} h) se conservan por si están en uso")
        if excluded:
            result.notes.append(f"carpetas protegidas, no se tocan: {', '.join(sorted(set(excluded)))}")
        if reparse:
            result.notes.append(f"{reparse} enlaces/uniones omitidos por seguridad")
        if denied:
            result.notes.append(f"{denied} elementos sin acceso (permisos)")
        return result

    # -- borrado -----------------------------------------------------------------------
    def clean(self, scan: ScanResult) -> CleanReport:
        report = CleanReport(self.id)
        roots = self.roots()
        cutoff = scan.scanned_at - self.min_age_hours * 3600
        for path, size in scan.files:
            root = next((r for r in roots if is_within(path, r)), None)
            if root is None:  # fuera de las raíces (plan manipulado o carpeta cambiada): jamás se toca
                report.skipped += 1
                continue
            try:
                st = os.lstat(path)
                # cutoff = scanned_at - edad mínima: también descarta lo modificado DESPUÉS del análisis
                if is_reparse_point(st) or stat.S_ISDIR(st.st_mode) or st.st_mtime > cutoff:
                    report.skipped += 1
                    continue
                try:
                    os.remove(path)
                except PermissionError:
                    os.chmod(path, stat.S_IWRITE)  # archivo de solo lectura
                    os.remove(path)
            except FileNotFoundError:
                continue
            except OSError:
                report.skipped += 1  # en uso por otro programa
                continue
            report.deleted_files += 1
            report.freed_bytes += size
            report.deleted_paths.append(path)

        if self.prune_dirs:
            for d in sorted(set(scan.dirs), key=lambda p: p.count(os.sep), reverse=True):
                if any(is_within(d, r) for r in roots):
                    try:
                        os.rmdir(d)  # solo funciona si está vacía
                    except OSError:
                        pass
        if report.skipped:
            report.notes.append(f"{report.skipped} archivos no se borraron (en uso o modificados)")
        return report


# --- Papelera de reciclaje -------------------------------------------------------------------

class _ShQueryRBInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]


SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4


class RecycleBinCategory(Category):
    id = "papelera"
    name = "Papelera de reciclaje"
    description = "Vacía la papelera de todas las unidades. Lo que contiene se pierde definitivamente."
    risk = Risk.MEDIUM

    @staticmethod
    def _query() -> tuple[int, int]:
        info = _ShQueryRBInfo(ctypes.sizeof(_ShQueryRBInfo), 0, 0)
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
            return 0, 0
        return int(info.i64Size), int(info.i64NumItems)

    @staticmethod
    def _empty() -> int:
        flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)

    def scan(self) -> ScanResult:
        size, items = self._query()
        result = ScanResult(self.id, extra_bytes=size, extra_items=items)
        if items:
            result.notes.append("Revisa la papelera antes: esto no se puede deshacer")
        return result

    def clean(self, scan: ScanResult) -> CleanReport:
        report = CleanReport(self.id)
        if scan.item_count == 0:
            return report
        code = self._empty()
        if code == 0:  # S_OK
            report.deleted_files, report.freed_bytes = scan.item_count, scan.extra_bytes
        else:
            report.skipped = scan.item_count
            report.notes.append(f"Windows no pudo vaciar la papelera (código {code & 0xFFFFFFFF:#x})")
        return report
