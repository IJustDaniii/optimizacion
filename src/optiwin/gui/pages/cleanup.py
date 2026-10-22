from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from optiwin.cleanup.cleaner import Cleaner, Plan, format_size
from optiwin.gui.pages.base import Page
from optiwin.gui.widgets import ConfirmDeleteDialog, TextDialog, card, label


class CleanupPage(Page):
    title = "Limpieza"
    subtitle = "Primero se analiza y se muestra cuánto ocupa cada categoría. No se borra nada sin tu confirmación escrita."

    def __init__(self, win):
        super().__init__(win)
        self.cleaner: Cleaner | None = None
        self.plan: Plan | None = None

        bar = QHBoxLayout()
        self.b_scan = QPushButton("Analizar")
        self.b_scan.setObjectName("primary")
        self.b_scan.clicked.connect(self._scan)
        self.total = label("Pulsa «Analizar» para ver qué se puede limpiar.", "muted", wrap=False)
        self.b_clean = QPushButton("Limpiar lo seleccionado…")
        self.b_clean.setObjectName("danger")
        self.b_clean.setEnabled(False)
        self.b_clean.clicked.connect(self._clean)
        bar.addWidget(self.b_scan)
        bar.addWidget(self.total, 1)
        bar.addWidget(self.b_clean)
        self.root.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Categoría", "Archivos", "Tamaño", "Estado"])
        self.tree.setColumnWidth(0, 380)
        self.tree.setRootIsDecorated(False)
        self.tree.itemChanged.connect(self._update_total)
        self.tree.currentItemChanged.connect(self._show_detail)
        self.root.addWidget(self.tree, 3)

        self.detail_card = card()
        dl = QVBoxLayout(self.detail_card)
        self.d_title = label("", "h2")
        self.d_text = label("")
        dl.addWidget(self.d_title)
        dl.addWidget(self.d_text)
        self.root.addWidget(self.detail_card, 2)

    # -- análisis -----------------------------------------------------------------------------
    def _scan(self) -> None:
        def work():
            cleaner = self.ctx.new_cleaner()
            return cleaner, cleaner.scan()

        self.win.run_async(work, self._show_plan, message="Analizando… (puede tardar un poco)")

    def _show_plan(self, result) -> None:
        self.cleaner, self.plan = result
        self.tree.blockSignals(True)
        self.tree.clear()
        for cid, scan in self.plan.scans.items():
            cat = self.cleaner.categories[cid]
            blocked = self.plan.blocked.get(cid)
            state = blocked or ("Riesgo medio" if cat.risk.value == "medio" else "")
            if cid in self.plan.warnings:
                state = (state + " · " if state else "") + "programa abierto"
            item = QTreeWidgetItem([cat.name, str(scan.item_count), format_size(scan.total_bytes), state])
            item.setData(0, Qt.ItemDataRole.UserRole, cid)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
            if blocked:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(3, "Reinicia OptiWin como administrador para incluirla.")
            else:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                # Por seguridad nada viene marcado salvo lo de bajo riesgo con contenido.
                on = scan.item_count > 0 and cat.risk.value == "bajo"
                item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        self._update_total()

    def _checked_ids(self) -> list[str]:
        ids = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                ids.append(item.data(0, Qt.ItemDataRole.UserRole))
        return ids

    def _update_total(self, *_) -> None:
        ids = self._checked_ids()
        total = sum(self.plan.scans[i].total_bytes for i in ids) if self.plan else 0
        self.total.setText(f"Seleccionado: {format_size(total)} en {len(ids)} categorías")
        self.b_clean.setEnabled(bool(ids))

    def _show_detail(self, item, *_) -> None:
        if item is None or not self.plan:
            return
        cid = item.data(0, Qt.ItemDataRole.UserRole)
        cat, scan = self.cleaner.categories[cid], self.plan.scans[cid]
        lines = [cat.description]
        lines += [f"• {n}" for n in scan.notes]
        if cid in self.plan.warnings:
            lines.append(f"⚠ {self.plan.warnings[cid]}")
        folders = scan.breakdown(6)
        if folders:
            lines.append("\nMás espacio en: " + " · ".join(f"{n} ({format_size(s)})" for n, s in folders))
        self.d_title.setText(cat.name)
        self.d_text.setText("\n".join(lines))

    # -- borrado ------------------------------------------------------------------------------
    def _clean(self) -> None:
        ids = self._checked_ids()
        if not ids or not self.plan or not self.cleaner:
            return
        total = sum(self.plan.scans[i].total_bytes for i in ids)
        names = "\n".join(f"  • {self.cleaner.categories[i].name} — {format_size(self.plan.scans[i].total_bytes)}" for i in ids)
        dialog = ConfirmDeleteDialog(f"Vas a borrar {format_size(total)}:\n{names}", self.win)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        cleaner, plan = self.cleaner, self.plan
        self.win.run_async(
            lambda: cleaner.clean(plan, ids, confirmed=True),
            self._done,
            message="Limpiando…",
        )

    def _done(self, reports) -> None:
        freed = sum(r.freed_bytes for r in reports)
        lines = [f"{r.category_id}: {r.deleted_files} archivos, {format_size(r.freed_bytes)} liberados"
                 + (f"  ({'; '.join(r.notes)})" if r.notes else "") for r in reports]
        self.win.status(f"Limpieza terminada: {format_size(freed)} liberados")
        TextDialog("Limpieza terminada", f"Total liberado: {format_size(freed)}\n\n" + "\n".join(lines), self.win).exec()
        self.plan = None
        self.tree.clear()
        self.b_clean.setEnabled(False)
        self.total.setText("Vuelve a pulsar «Analizar» para ver el estado actual.")
