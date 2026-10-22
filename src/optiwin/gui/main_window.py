"""Ventana principal: navegación, ejecución en segundo plano, bandeja y cambio automático AC/DC."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from optiwin import __version__
from optiwin.core.autoswitch import AutoSwitcher
from optiwin.core.elevation import relaunch_gui_elevated
from optiwin.core.engine import Result
from optiwin.core.power_status import PowerStatus, read_power_status
from optiwin.core.updater import ReleaseInfo, UpdateError, check_for_update, download_installer
from optiwin.core.winutil import is_admin
from optiwin.gui.context import AppContext
from optiwin.gui.pages.cleanup import CleanupPage
from optiwin.gui.pages.home import HomePage
from optiwin.gui.pages.logs import LogPage
from optiwin.gui.pages.profiles import ProfilesPage
from optiwin.gui.pages.settings import SettingsPage
from optiwin.gui.pages.tweaks import TweaksPage
from optiwin.gui.tasks import TaskRunner
from optiwin.gui.widgets import STYLE, TextDialog, format_report, label, restore_blocked
from optiwin.profiles.definitions import PROFILES
from optiwin.profiles.manager import ActivationReport

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def app_icon() -> QIcon:
    png = ASSETS / "optiwin.png"
    return QIcon(str(png)) if png.exists() else QIcon()


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("OptiWin")
        self.setWindowIcon(app_icon())
        self.resize(1040, 720)
        self.setStyleSheet(STYLE)
        self.tasks = TaskRunner(self)
        self._busy = 0
        self._really_quit = False
        self._pending_source: str | None = None
        self._warned_no_restore = False
        self._last_status: PowerStatus = read_power_status()
        self._is_laptop: bool | None = None

        # -- estructura
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.banner = QWidget()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(16, 8, 16, 8)
        bl.addWidget(label("No tienes permisos de administrador. Se piden solo cuando una acción los necesita.", "muted"), 1)
        elevate = QPushButton("Reiniciar como administrador")
        elevate.clicked.connect(self.relaunch_as_admin)
        bl.addWidget(elevate)
        self.banner.setVisible(not is_admin())
        outer.addWidget(self.banner)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(body, 1)

        side = QVBoxLayout()
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(190)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.addWidget(self.nav, 1)
        side.addWidget(label(f"OptiWin {__version__}", "muted", wrap=False))
        side_w = QWidget()
        side_w.setLayout(side)
        body.addWidget(side_w)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        self.home = HomePage(self)
        self.profiles = ProfilesPage(self)
        self.pages = [self.home, self.profiles, TweaksPage(self), CleanupPage(self), LogPage(self), SettingsPage(self)]
        titles = ["Inicio", "Perfiles", "Ajustes", "Limpieza", "Registro", "Configuración"]
        for page, title in zip(self.pages, titles):
            self.nav.addItem(title)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._change_page)

        self.statusBar().showMessage("Listo")

        # -- bandeja
        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self)
            menu = QMenu()
            open_action = QAction("Abrir OptiWin", self)
            open_action.triggered.connect(self.show_window)
            quit_action = QAction("Salir", self)
            quit_action.triggered.connect(self.quit_app)
            menu.addAction(open_action)
            menu.addSeparator()
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.setToolTip("OptiWin")
            self.tray.show()

        # -- vigilante de alimentación (una llamada barata a la API cada 2 s)
        self.switcher = AutoSwitcher(self._on_source_change, read_status=lambda: self._last_status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(2000)

        self.nav.setCurrentRow(0)

    # -- navegación -------------------------------------------------------------------------------
    def _change_page(self, row: int) -> None:
        if row >= 0:
            self.stack.setCurrentIndex(row)
            self.pages[row].refresh()

    def refresh_all(self) -> None:
        self.pages[self.stack.currentIndex()].refresh()
        self.home._show_state()

    def status(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)

    def set_laptop(self, is_laptop: bool) -> None:
        self._is_laptop = is_laptop

    # -- trabajo en segundo plano --------------------------------------------------------------------
    def run_async(self, fn: Callable[[], Any], on_done: Callable[[Any], None],
                  on_error: Callable[[str], None] | None = None, message: str = "Trabajando…") -> None:
        self._set_busy(+1, message)

        def done(result):
            self._set_busy(-1)
            on_done(result)

        def failed(error):
            self._set_busy(-1)
            (on_error or self._show_error)(error)

        self.tasks.submit(fn, done, failed)

    def _set_busy(self, delta: int, message: str = "") -> None:
        self._busy += delta
        busy = self._busy > 0
        self.centralWidget().setEnabled(not busy)
        if busy:
            self.statusBar().showMessage(message)
            self.setCursor(Qt.CursorShape.BusyCursor)
        else:
            self.statusBar().showMessage("Listo")
            self.unsetCursor()

    def _show_error(self, error: str) -> None:
        self.ctx.log.error("ERROR GUI | %s", error)
        TextDialog("Ha ocurrido un error", error, self).exec()

    # -- cambios con red de seguridad ------------------------------------------------------------------
    def run_change(self, action: Callable[[bool], Any], on_done: Callable[[Any], None]) -> None:
        """action(skip_restore_point). Si falta el punto de restauración y no somos admin, se pregunta qué hacer."""

        def after(result):
            if restore_blocked(result):
                choice = self._ask_restore_choice()
                if choice == "elevate":
                    self.relaunch_as_admin()
                elif choice == "skip":
                    self.run_async(lambda: action(True), on_done)
                return
            on_done(result)

        self.run_async(lambda: action(False), after)

    def _ask_restore_choice(self) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Punto de restauración")
        box.setText("Antes del primer cambio OptiWin crea un punto de restauración de Windows.")
        box.setInformativeText("Windows solo permite crearlo con permisos de administrador. Los ajustes de OptiWin "
                               "seguirán siendo reversibles aunque lo omitas, pero no habrá copia de seguridad del sistema.")
        elevate = box.addButton("Reiniciar como administrador", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Continuar sin punto de restauración", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return "elevate" if box.clickedButton() is elevate else "skip" if box.clickedButton() is skip else "cancel"

    def finish_change(self, title: str, report: ActivationReport | list[Result] | Result) -> None:
        results = [report] if isinstance(report, Result) else report if isinstance(report, list) else report.results
        errors = [r for r in results if r.status == "error"]
        changed = sum(1 for r in results if r.status in ("applied", "reverted"))
        self.refresh_all()
        if errors:
            TextDialog(f"{title}: hubo problemas", format_report(report), self).exec()
            if any(r.needs_admin for r in errors):
                ask = QMessageBox.question(self, "Permisos de administrador",
                                           "Algunos pasos necesitan administrador. ¿Reiniciar OptiWin como administrador?")
                if ask == QMessageBox.StandardButton.Yes:
                    self.relaunch_as_admin()
        else:
            self.status(f"{title}: {changed} cambios aplicados")
            notes = report.notes if isinstance(report, ActivationReport) else []
            if notes:
                TextDialog(title, format_report(report), self).exec()

    # -- permisos ----------------------------------------------------------------------------------------
    def relaunch_as_admin(self) -> None:
        if relaunch_gui_elevated():
            self.quit_app()
        else:
            self.status("Se canceló la petición de administrador")

    # -- cambio automático ---------------------------------------------------------------------------------
    def on_auto_config_changed(self) -> None:
        self.switcher.current = None  # reevalúa la fuente actual con la nueva configuración
        self._pending_source = None

    def _tick(self) -> None:
        self._last_status = read_power_status()
        self.home.update_power(self._last_status)
        if self.ctx.config.auto_switch["enabled"]:
            self.switcher.poll_once()
            self._process_pending()

    def _on_source_change(self, source: str) -> None:
        self._pending_source = source

    def _process_pending(self) -> None:
        source = self._pending_source
        if source is None or self._busy:
            return
        self._pending_source = None
        if self.ctx.engine.store.restore_point is None:
            if not self._warned_no_restore:
                self._warned_no_restore = True
                self.notify("Cambio automático en pausa",
                            "Primero aplica algo a mano para crear el punto de restauración (hace falta una vez).")
            return
        auto = self.ctx.config.auto_switch
        pid = auto["on_ac"] if source == "ac" else auto["on_battery"]
        label_ = "enchufado" if source == "ac" else "con batería"
        self.ctx.log.info("AUTO | fuente=%s perfil=%s", source, pid)
        self.run_async(
            lambda: self.ctx.manager.activate(pid, close=False),  # el automático nunca cierra procesos
            lambda rep: self._auto_done(pid, label_, rep),
            message="Cambiando de perfil…",
        )

    def _auto_done(self, pid: str, label_: str, report: ActivationReport) -> None:
        self.refresh_all()
        if report.ok:
            self.notify("OptiWin", f"{label_.capitalize()}: perfil «{PROFILES[pid].name}» activado")
        else:
            self.notify("OptiWin", f"No se pudo activar «{PROFILES[pid].name}». Mira el Registro.")

    def notify(self, title: str, text: str) -> None:
        if self.tray:
            self.tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)
        self.status(text)

    # -- actualizaciones --------------------------------------------------------------------------------------
    def startup_update_check(self) -> None:
        setting = self.ctx.config.data["updates"].get("check_on_start")
        if setting is None:
            ask = QMessageBox.question(
                self, "Actualizaciones",
                "¿Quieres que OptiWin busque actualizaciones al abrirse?\n\nSolo hace una consulta a la API pública de "
                "GitHub; no se envía ningún dato de tu equipo. Puedes cambiarlo en Configuración.")
            setting = ask == QMessageBox.StandardButton.Yes
            self.ctx.config.data["updates"]["check_on_start"] = setting
            self.ctx.config.save()
        if setting:
            self.check_updates(manual=False)

    def check_updates(self, manual: bool) -> None:
        def work():
            try:
                return ("ok", check_for_update())
            except UpdateError as exc:
                return ("error", str(exc))

        self.run_async(work, lambda res: self._update_result(res, manual), message="Buscando actualizaciones…")

    def _update_result(self, res: tuple[str, Any], manual: bool) -> None:
        kind, value = res
        if kind == "error":
            self.ctx.log.info("ACTUALIZACION | %s", value)
            if manual:
                QMessageBox.information(self, "Actualizaciones", value)
            return
        info: ReleaseInfo | None = value
        if info is None:
            if manual:
                QMessageBox.information(self, "Actualizaciones", f"Ya tienes la última versión ({__version__}).")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Actualización disponible")
        box.setText(f"Hay una versión nueva: {info.version} (tienes la {__version__}).")
        box.setInformativeText("¿Descargarla e instalarla ahora? Se verifica su hash SHA-256 antes de ejecutarla.")
        box.setDetailedText(info.notes or "Sin notas de versión.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        dest = Path(tempfile.gettempdir()) / "OptiWin-update"

        def work():
            try:
                return ("ok", download_installer(info, dest))
            except UpdateError as exc:
                return ("error", str(exc))

        self.run_async(work, self._install_update, message=f"Descargando {info.installer_name}…")

    def _install_update(self, res: tuple[str, Any]) -> None:
        kind, value = res
        if kind == "error":
            QMessageBox.warning(self, "Actualización", value)
            return
        installer: Path = value
        self.ctx.log.info("ACTUALIZACION | ejecutando %s", installer.name)
        subprocess.Popen([str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], close_fds=True)
        self.quit_app()

    # -- ciclo de vida ----------------------------------------------------------------------------------------------
    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._really_quit = True
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 (nombre de Qt)
        if not self._really_quit and self.tray and self.ctx.config.auto_switch["enabled"]:
            event.ignore()
            self.hide()
            self.notify("OptiWin sigue activo", "El cambio automático enchufado/batería sigue funcionando desde la bandeja.")
        else:
            self._really_quit = True
            if self.tray:
                self.tray.hide()
            event.accept()
