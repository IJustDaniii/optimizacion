from __future__ import annotations

import os

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton

from optiwin.core.logger import read_log_tail
from optiwin.gui.pages.base import Page


class LogPage(Page):
    title = "Registro"
    subtitle = "Todo lo que OptiWin simula, aplica, deshace o borra queda anotado aquí (solo en tu equipo)."

    def __init__(self, win):
        super().__init__(win)
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        self.box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.root.addWidget(self.box, 1)
        row = QHBoxLayout()
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self.refresh)
        folder = QPushButton("Abrir carpeta de datos")
        folder.clicked.connect(lambda: os.startfile(self.ctx.home))
        row.addWidget(refresh)
        row.addWidget(folder)
        row.addStretch()
        self.root.addLayout(row)

    def refresh(self) -> None:
        lines = read_log_tail(self.ctx.home, 400)
        self.box.setPlainText("\n".join(lines) or "El registro está vacío.")
        self.box.verticalScrollBar().setValue(self.box.verticalScrollBar().maximum())
