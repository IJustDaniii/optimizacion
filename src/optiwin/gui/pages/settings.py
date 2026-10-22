from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from optiwin import __version__
from optiwin.core import autostart, process_closer
from optiwin.core.winutil import is_admin
from optiwin.gui.pages.base import Page
from optiwin.gui.widgets import card, label
from optiwin.profiles.definitions import PROFILES


class SettingsPage(Page):
    title = "Configuración"
    scrollable = True

    def __init__(self, win):
        super().__init__(win)
        col = self.root
        self._loading = False

        # -- Actualizaciones
        box = card()
        lay = QVBoxLayout(box)
        lay.addWidget(label("Actualizaciones", "h2"))
        lay.addWidget(label(
            f"Versión instalada: {__version__}. Buscar actualizaciones hace UNA petición a la API pública de GitHub "
            "(repositorio IJustDaniii/optimizacion); no se envía ningún dato de tu equipo. El instalador descargado "
            "se verifica con su hash SHA-256 antes de ejecutarse.", "muted"))
        self.chk_updates = QCheckBox("Buscar actualizaciones automáticamente al abrir OptiWin")
        self.chk_updates.toggled.connect(self._save_updates)
        btn = QPushButton("Buscar actualizaciones ahora")
        btn.clicked.connect(lambda: self.win.check_updates(manual=True))
        lay.addWidget(self.chk_updates)
        lay.addWidget(btn)
        col.addWidget(box)

        # -- Inicio con Windows
        box = card()
        lay = QVBoxLayout(box)
        lay.addWidget(label("Inicio con Windows", "h2"))
        lay.addWidget(label("Abre OptiWin minimizado en la bandeja al iniciar sesión, para que el cambio automático "
                            "enchufado/batería funcione siempre. Se puede quitar aquí en cualquier momento.", "muted"))
        self.chk_start = QCheckBox("Iniciar OptiWin con Windows (en la bandeja)")
        self.chk_start.toggled.connect(self._save_autostart)
        lay.addWidget(self.chk_start)
        col.addWidget(box)

        # -- Listas de cierre
        box = card()
        lay = QVBoxLayout(box)
        lay.addWidget(label("Procesos que se cierran al activar un perfil", "h2"))
        lay.addWidget(label("Un nombre por línea (por ejemplo Discord.exe). Solo se cierra con la casilla «Cerrar…» del "
                            "perfil, de forma amable, y nunca procesos del sistema ni Defender.", "muted"))
        grid = QGridLayout()
        self.close_edits: dict[str, QPlainTextEdit] = {}
        for i, pid in enumerate(p.id for p in PROFILES.values() if p.closes_processes):
            grid.addWidget(label(PROFILES[pid].name, "h2"), 0, i)
            edit = QPlainTextEdit()
            edit.setFixedHeight(120)
            self.close_edits[pid] = edit
            grid.addWidget(edit, 1, i)
        lay.addLayout(grid)
        save = QPushButton("Guardar listas")
        save.clicked.connect(self._save_close_lists)
        lay.addWidget(save)
        col.addWidget(box)

        # -- Juegos con GPU dedicada
        box = card()
        lay = QVBoxLayout(box)
        lay.addWidget(label("Juegos con GPU dedicada", "h2"))
        lay.addWidget(label("El perfil Juegos indica a Windows que use la GPU de alto rendimiento para estos programas.", "muted"))
        self.gpu_list = QListWidget()
        self.gpu_list.setFixedHeight(110)
        row = QHBoxLayout()
        add, rem = QPushButton("Añadir juego (.exe)…"), QPushButton("Quitar seleccionado")
        add.clicked.connect(self._add_gpu)
        rem.clicked.connect(self._remove_gpu)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        lay.addWidget(self.gpu_list)
        lay.addLayout(row)
        col.addWidget(box)

        # -- Permisos
        box = card()
        lay = QVBoxLayout(box)
        lay.addWidget(label("Permisos de administrador", "h2"))
        self.admin_label = label("")
        elevate = QPushButton("Reiniciar como administrador")
        elevate.clicked.connect(self.win.relaunch_as_admin)
        self.elevate = elevate
        lay.addWidget(self.admin_label)
        lay.addWidget(elevate)
        col.addWidget(box)
        col.addStretch()

    def refresh(self) -> None:
        cfg = self.ctx.config
        self._loading = True
        self.chk_updates.setChecked(bool(cfg.data["updates"].get("check_on_start")))
        self.chk_start.setChecked(autostart.is_enabled())
        for pid, edit in self.close_edits.items():
            edit.setPlainText("\n".join(cfg.close_list(pid)))
        self.gpu_list.clear()
        self.gpu_list.addItems(cfg.gpu_apps)
        admin = is_admin()
        self.admin_label.setText("Ahora mismo OptiWin se ejecuta como administrador." if admin else
                                 "OptiWin se ejecuta sin permisos de administrador y los pide solo cuando una acción lo necesita "
                                 "(crear el punto de restauración, ajustes de sistema, limpiar carpetas de Windows).")
        self.elevate.setVisible(not admin)
        self._loading = False

    # -- guardado ------------------------------------------------------------------------------------
    def _save_updates(self, on: bool) -> None:
        if self._loading:
            return
        self.ctx.config.data["updates"]["check_on_start"] = bool(on)
        self.ctx.config.save()
        self.ctx.log.info("CONFIG | buscar actualizaciones al abrir=%s", on)

    def _save_autostart(self, on: bool) -> None:
        if self._loading:
            return
        try:
            autostart.set_enabled(on)
            self.ctx.log.info("CONFIG | inicio con Windows=%s", on)
        except OSError as exc:
            QMessageBox.warning(self, "Inicio con Windows", f"No se pudo cambiar: {exc}")

    def _save_close_lists(self) -> None:
        cfg = self.ctx.config
        problems = []
        new_lists: dict[str, list[str]] = {}
        for pid, edit in self.close_edits.items():
            names: list[str] = []
            for line in edit.toPlainText().splitlines():
                if not line.strip():
                    continue
                try:
                    name = process_closer.normalize_name(line)
                except process_closer.InvalidProcessName as exc:
                    problems.append(str(exc))
                    continue
                if name.lower() not in [n.lower() for n in names]:
                    names.append(name)
            new_lists[pid] = names
        for pid, names in new_lists.items():
            cfg.data["close_processes"][pid] = names
        cfg.save()
        self.ctx.log.info("CONFIG | listas de cierre actualizadas")
        self.refresh()
        if problems:
            QMessageBox.warning(self, "Algunas líneas no se guardaron", "\n".join(sorted(set(problems))))
        else:
            self.win.status("Listas guardadas")

    def _add_gpu(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elige el .exe del juego", "", "Programas (*.exe)")
        if not path:
            return
        path = os.path.normpath(path)
        apps = self.ctx.config.gpu_apps
        if path.lower() not in [a.lower() for a in apps]:
            apps.append(path)
            self.ctx.config.save()
            self.ctx.reload_catalog()
            self.ctx.log.info("CONFIG | GPU dedicada añadida: %s", path)
        self.refresh()

    def _remove_gpu(self) -> None:
        item = self.gpu_list.currentItem()
        if not item:
            return
        apps = self.ctx.config.gpu_apps
        apps[:] = [a for a in apps if a != item.text()]
        self.ctx.config.save()
        self.ctx.reload_catalog()
        self.ctx.log.info("CONFIG | GPU dedicada quitada: %s", item.text())
        self.refresh()
