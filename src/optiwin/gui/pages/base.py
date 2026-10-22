from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from optiwin.gui.widgets import label

if TYPE_CHECKING:
    from optiwin.gui.main_window import MainWindow


class Page(QWidget):
    title = ""
    subtitle = ""
    scrollable = False  # True para páginas con mucho contenido: así los textos nunca se recortan

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        self.ctx = win.ctx
        if self.scrollable:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            inner = QWidget()
            scroll.setWidget(inner)
            outer.addWidget(scroll)
            self.root = QVBoxLayout(inner)
        else:
            self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 22, 28, 22)
        self.root.setSpacing(14)
        self.root.addWidget(label(self.title, "h1"))
        if self.subtitle:
            self.root.addWidget(label(self.subtitle, "muted"))

    def refresh(self) -> None:
        """Vuelve a leer el estado. Lo llama la ventana al mostrar la página y tras cada cambio."""
