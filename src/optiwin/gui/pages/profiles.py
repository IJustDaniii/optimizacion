from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QPushButton, QVBoxLayout

from optiwin.gui.pages.base import Page
from optiwin.gui.widgets import TextDialog, card, format_report, label
from optiwin.profiles.definitions import PROFILES


class ProfilesPage(Page):
    title = "Perfiles"
    subtitle = "Un clic para cambiar cómo se comporta el equipo. Todo es reversible y puedes simular antes."
    scrollable = True

    def __init__(self, win):
        super().__init__(win)
        self.close_checks: dict[str, QCheckBox] = {}
        self.name_labels = {}

        for profile in PROFILES.values():
            box = card()
            lay = QVBoxLayout(box)
            self.name_labels[profile.id] = label(profile.name, "h2")
            lay.addWidget(self.name_labels[profile.id])
            lay.addWidget(label(profile.description, "muted"))
            row = QHBoxLayout()
            if profile.closes_processes:
                chk = QCheckBox("Cerrar los procesos de mi lista (Configuración)")
                self.close_checks[profile.id] = chk
                row.addWidget(chk)
            row.addStretch()
            sim = QPushButton("Simular")
            sim.clicked.connect(lambda _=False, pid=profile.id: self._simulate(pid))
            act = QPushButton("Activar")
            act.setObjectName("primary")
            act.clicked.connect(lambda _=False, pid=profile.id: self._activate(pid))
            row.addWidget(sim)
            row.addWidget(act)
            lay.addLayout(row)
            self.root.addWidget(box)

        off_row = QHBoxLayout()
        self.reopen = QCheckBox("Reabrir los programas que se cerraron")
        off = QPushButton("Desactivar perfil actual")
        off.clicked.connect(self._deactivate)
        off_row.addWidget(self.reopen)
        off_row.addStretch()
        off_row.addWidget(off)
        self.root.addLayout(off_row)

        auto = card()
        alay = QVBoxLayout(auto)
        alay.addWidget(label("Cambio automático al enchufar / desenchufar", "h2"))
        alay.addWidget(label(
            "Mientras OptiWin esté abierto (se queda en la bandeja del sistema), aplica un perfil al enchufar "
            "y otro al desenchufar. Nunca cierra procesos. Necesita que ya exista el punto de restauración.", "muted"))
        self.auto_enabled = QCheckBox("Activar el cambio automático")
        self.on_ac, self.on_dc = QComboBox(), QComboBox()
        for combo in (self.on_ac, self.on_dc):
            for p in PROFILES.values():
                combo.addItem(p.name, p.id)
        row = QHBoxLayout()
        row.addWidget(label("Enchufado:", wrap=False))
        row.addWidget(self.on_ac)
        row.addWidget(label("Con batería:", wrap=False))
        row.addWidget(self.on_dc)
        row.addStretch()
        alay.addWidget(self.auto_enabled)
        alay.addLayout(row)
        self.root.addWidget(auto)
        self.root.addStretch()

        self._loading = False
        for w in (self.on_ac, self.on_dc):
            w.currentIndexChanged.connect(self._save_auto)
        self.auto_enabled.toggled.connect(self._save_auto)

    def refresh(self) -> None:
        cur = self.ctx.manager.current()
        for pid, lab in self.name_labels.items():
            lab.setText(PROFILES[pid].name + ("  ● ACTIVO" if cur and cur["id"] == pid else ""))
        a = self.ctx.config.auto_switch
        self._loading = True
        self.auto_enabled.setChecked(bool(a["enabled"]))
        self.on_ac.setCurrentIndex(max(0, self.on_ac.findData(a["on_ac"])))
        self.on_dc.setCurrentIndex(max(0, self.on_dc.findData(a["on_battery"])))
        self._loading = False

    def _save_auto(self, *_):
        if self._loading:
            return
        a = self.ctx.config.auto_switch
        a["enabled"] = self.auto_enabled.isChecked()
        a["on_ac"], a["on_battery"] = self.on_ac.currentData(), self.on_dc.currentData()
        self.ctx.config.save()
        self.ctx.log.info("CONFIG | cambio automático=%s ac=%s bateria=%s", a["enabled"], a["on_ac"], a["on_battery"])
        self.win.on_auto_config_changed()

    def _close_flag(self, pid: str) -> bool:
        chk = self.close_checks.get(pid)
        return bool(chk and chk.isChecked())

    def _simulate(self, pid: str) -> None:
        close = self._close_flag(pid)
        self.win.run_async(
            lambda: self.ctx.manager.activate(pid, dry_run=True, close=close),
            lambda rep: TextDialog(f"Simulación: {PROFILES[pid].name}", format_report(rep, verbose=True), self.win).exec(),
            message="Simulando…",
        )

    def _activate(self, pid: str) -> None:
        close = self._close_flag(pid)
        self.win.run_change(
            lambda skip: self.ctx.manager.activate(pid, close=close, skip_restore_point=skip),
            lambda rep: self.win.finish_change(f"Perfil «{PROFILES[pid].name}»", rep),
        )

    def _deactivate(self) -> None:
        reopen = self.reopen.isChecked()
        self.win.run_async(
            lambda: self.ctx.manager.deactivate(reopen=reopen),
            lambda rep: self.win.finish_change("Desactivar perfil", rep),
            message="Desactivando…",
        )
