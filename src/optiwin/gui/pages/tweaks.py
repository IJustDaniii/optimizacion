from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from optiwin.core.engine import TweakStatus
from optiwin.gui.pages.base import Page
from optiwin.gui.widgets import TextDialog, card, format_report, label
from optiwin.tweaks.powercfg_tweak import PowerCfgSettingTweak

CATEGORY_NAMES = {"energia": "Energía", "juegos": "Juegos", "visual": "Efectos visuales"}


class TweaksPage(Page):
    title = "Ajustes"
    subtitle = "Cada ajuste se explica, guarda su valor original y se puede deshacer por separado."

    def __init__(self, win):
        super().__init__(win)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Ajuste", "Valor actual", "Estado", "Riesgo"])
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 250)
        self.tree.setRootIsDecorated(True)
        self.tree.currentItemChanged.connect(self._select)
        self.root.addWidget(self.tree, 3)

        self.detail = card()
        dl = QVBoxLayout(self.detail)
        self.d_title = label("Selecciona un ajuste", "h2")
        self.d_desc = label("")
        self.d_benefit = label("", "muted")
        self.d_meta = label("")
        for w in (self.d_title, self.d_desc, self.d_benefit, self.d_meta):
            dl.addWidget(w)
        row = QHBoxLayout()
        self.value_label = label("Valor a aplicar:", wrap=False)
        self.spin = QSpinBox()
        self.spin.valueChanged.connect(self._update_meaning)
        self.meaning = label("", "muted", wrap=False)
        self.b_sim, self.b_apply, self.b_undo = QPushButton("Simular"), QPushButton("Aplicar"), QPushButton("Deshacer")
        self.b_apply.setObjectName("primary")
        self.b_sim.clicked.connect(self._simulate)
        self.b_apply.clicked.connect(self._apply)
        self.b_undo.clicked.connect(self._undo)
        for w in (self.value_label, self.spin, self.meaning):
            row.addWidget(w)
        row.addStretch()
        for b in (self.b_sim, self.b_undo, self.b_apply):
            row.addWidget(b)
        dl.addLayout(row)
        self.root.addWidget(self.detail, 2)

        self.rows: dict[str, TweakStatus] = {}
        self.items: dict[str, QTreeWidgetItem] = {}
        self._set_enabled(False)

    # -- lista -------------------------------------------------------------------------------
    def refresh(self) -> None:
        selected = self._current_id()
        self.win.run_async(self.ctx.engine.status, lambda rows: self._populate(rows, selected), message="Leyendo ajustes…")

    def _populate(self, rows: list[TweakStatus], selected: str | None) -> None:
        self.tree.clear()
        self.rows = {r.tweak.id: r for r in rows}
        self.items = {}
        groups: dict[str, QTreeWidgetItem] = {}
        for r in rows:
            t = r.tweak
            parent = groups.get(t.category)
            if parent is None:
                parent = QTreeWidgetItem([CATEGORY_NAMES.get(t.category, t.category.capitalize())])
                parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(parent)
                groups[t.category] = parent
            state = "Aplicado" if r.applied else ("No disponible" if not r.available else "—")
            item = QTreeWidgetItem([t.name, r.current, state, t.risk.value.capitalize()])
            item.setData(0, Qt.ItemDataRole.UserRole, t.id)
            if not r.available:
                item.setDisabled(True)
                item.setToolTip(0, r.unavailable_reason)
            parent.addChild(item)
            self.items[t.id] = item
        self.tree.expandAll()
        if selected in self.items:
            self.tree.setCurrentItem(self.items[selected])

    def _current_id(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    # -- detalle -------------------------------------------------------------------------------
    def _set_enabled(self, on: bool) -> None:
        for w in (self.b_sim, self.b_apply, self.b_undo, self.spin):
            w.setEnabled(on)

    def _select(self, *_):
        tid = self._current_id()
        row = self.rows.get(tid) if tid else None
        if row is None:
            self._set_enabled(False)
            return
        t = row.tweak
        self.d_title.setText(t.name)
        self.d_desc.setText(t.description)
        self.d_benefit.setText(f"Beneficio esperado: {t.benefit}")
        admin = f"Necesita administrador: {t.admin_reason}" if t.requires_admin else "No necesita administrador"
        reboot = " · Requiere reiniciar" if t.reboot_required else ""
        self.d_meta.setText(f"Riesgo: {t.risk.value} · {admin}{reboot}")
        is_power = isinstance(t, PowerCfgSettingTweak)
        for w in (self.value_label, self.spin, self.meaning):
            w.setVisible(is_power)
        if is_power:
            self.spin.setRange(t.min_value, t.max_value)
            self.spin.setSuffix(t.unit)
            self.spin.setValue(t.default_value)
            self._update_meaning()
        self._set_enabled(row.available)
        self.b_undo.setEnabled(row.available and row.applied)

    def _update_meaning(self, *_):
        row = self.rows.get(self._current_id() or "")
        if row and isinstance(row.tweak, PowerCfgSettingTweak):
            self.meaning.setText(row.tweak.labels.get(self.spin.value(), ""))

    def _value(self):
        row = self.rows[self._current_id()]
        return self.spin.value() if isinstance(row.tweak, PowerCfgSettingTweak) else None

    # -- acciones --------------------------------------------------------------------------------
    def _simulate(self) -> None:
        tid, value = self._current_id(), self._value()
        self.win.run_async(
            lambda: self.ctx.engine.apply(tid, value, dry_run=True),
            lambda r: TextDialog("Simulación", format_report(r, verbose=True), self.win).exec(),
            message="Simulando…",
        )

    def _apply(self) -> None:
        tid, value = self._current_id(), self._value()
        self.win.run_change(
            lambda skip: self.ctx.engine.apply(tid, value, skip_restore_point=skip),
            lambda r: self.win.finish_change(self.rows[tid].tweak.name, r),
        )

    def _undo(self) -> None:
        tid = self._current_id()
        self.win.run_async(
            lambda: self.ctx.engine.revert(tid),
            lambda r: self.win.finish_change(self.rows[tid].tweak.name, r),
            message="Deshaciendo…",
        )
