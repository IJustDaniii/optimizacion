"""Punto de entrada de la interfaz gráfica."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from optiwin.gui.context import create_context
from optiwin.gui.main_window import MainWindow, app_icon


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    start_hidden = "--tray" in argv

    app = QApplication(sys.argv[:1])
    app.setApplicationName("OptiWin")
    app.setQuitOnLastWindowClosed(False)  # la bandeja mantiene la app viva; MainWindow decide cuándo salir
    app.setWindowIcon(app_icon())

    ctx = create_context()

    # Una sola instancia: si acabamos de relanzar como administrador, esperamos a que la anterior se cierre.
    lock = QLockFile(str(ctx.home / "gui.lock"))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(8000):
        QMessageBox.information(None, "OptiWin", "OptiWin ya está abierto (mira la bandeja del sistema).")
        return 0

    window = MainWindow(ctx)
    app.aboutToQuit.connect(lock.unlock)
    if not start_hidden:
        window.show()
        QTimer.singleShot(1200, window.startup_update_check)
    elif ctx.config.data["updates"].get("check_on_start"):
        QTimer.singleShot(5000, window.startup_update_check)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
