"""Piezas de interfaz reutilizables y formato de resultados."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from optiwin.core.engine import Result
from optiwin.profiles.manager import ActivationReport

STYLE = """
QFrame#card { background: palette(base); border: 1px solid palette(mid); border-radius: 10px; }
QLabel#h1 { font-size: 20px; font-weight: 600; }
QLabel#h2 { font-size: 14px; font-weight: 600; }
QLabel#muted { color: palette(placeholder-text); }
QLabel#badge-low { color: #2e7d32; font-weight: 600; }
QLabel#badge-medium { color: #b26a00; font-weight: 600; }
QLabel#badge-high { color: #c62828; font-weight: 600; }
QListWidget#nav { border: none; font-size: 14px; background: transparent; }
QListWidget#nav::item { padding: 10px 14px; border-radius: 8px; margin: 2px 6px; }
QListWidget#nav::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QPushButton#primary { background: palette(highlight); color: palette(highlighted-text); border: none; padding: 7px 16px; border-radius: 6px; }
QPushButton#primary:disabled { background: palette(mid); }
QPushButton#danger { background: #c62828; color: white; border: none; padding: 7px 16px; border-radius: 6px; }
QPushButton#danger:disabled { background: palette(mid); }
"""

_LABELS = {"applied": "APLICADO", "dry_run": "SIMULACIÓN", "reverted": "DESHECHO", "skipped": "SIN CAMBIOS", "error": "ERROR"}


def card(parent: QWidget | None = None) -> QFrame:
    frame = QFrame(parent)
    frame.setObjectName("card")
    return frame


def label(text: str, kind: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if kind:
        lab.setObjectName(kind)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def format_result(r: Result) -> str:
    ident = f" {r.tweak_id}" if r.tweak_id != "-" else ""
    return f"[{_LABELS[r.status]}]{ident} {r.message}"


def format_report(report: ActivationReport | list[Result] | Result, verbose: bool = False) -> str:
    """Texto legible de lo que pasó. Sin `verbose` se omiten los pasos 'sin cambios'."""
    if isinstance(report, Result):
        return format_result(report)
    results = report if isinstance(report, list) else report.results
    lines = [format_result(r) for r in results if verbose or r.status != "skipped"]
    skipped = sum(1 for r in results if r.status == "skipped")
    if skipped and not verbose:
        lines.append(f"({skipped} ajustes ya tenían el valor correcto)")
    if isinstance(report, ActivationReport):
        lines += [f"· {n}" for n in report.notes]
    return "\n".join(lines) or "No hay cambios."


def restore_blocked(report: ActivationReport | list[Result] | Result) -> bool:
    """¿Se paró todo porque falta crear el punto de restauración (y hacen falta permisos de admin)?"""
    results = [report] if isinstance(report, Result) else report if isinstance(report, list) else report.results
    return any(r.tweak_id == "-" and r.needs_admin for r in results)


class TextDialog(QDialog):
    def __init__(self, title: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 420)
        layout = QVBoxLayout(self)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ConfirmDeleteDialog(QDialog):
    """Confirmación escrita: el botón solo se activa al escribir BORRAR."""

    WORD = "BORRAR"

    def __init__(self, summary: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Confirmar limpieza")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(label(summary))
        layout.addWidget(label("Se borrará DEFINITIVAMENTE (no va a la papelera). Esta acción no se puede deshacer.", "h2"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(f"Escribe {self.WORD} para continuar")
        layout.addWidget(self.edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Borrar")
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.edit.textChanged.connect(lambda t: self.ok.setEnabled(t.strip() == self.WORD))
