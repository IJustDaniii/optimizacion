from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QMessageBox, QPushButton

from optiwin.core.detection import SystemInfo, detect_system
from optiwin.core.power_status import KNOWN_SCHEMES, PowerStatus
from optiwin.gui.pages.base import Page
from optiwin.gui.widgets import card, format_report, label
from optiwin.profiles.definitions import PROFILES


def _fmt_time(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    h, m = divmod(seconds // 60, 60)
    return f"{h} h {m:02d} min"


class HomePage(Page):
    title = "Inicio"
    subtitle = "Resumen de tu equipo y de cómo está alimentado ahora mismo."

    def __init__(self, win):
        super().__init__(win)
        self.info: SystemInfo | None = None

        row = QHBoxLayout()
        self.sys_form = QFormLayout()
        sys_card = card()
        sys_card.setLayout(self.sys_form)
        self.sys_labels: dict[str, object] = {}
        for key, text in [("equipo", "Equipo"), ("tipo", "Tipo"), ("windows", "Windows"), ("cpu", "CPU"),
                          ("gpu", "GPU"), ("ram", "RAM"), ("discos", "Discos")]:
            self.sys_labels[key] = label("…")
            self.sys_form.addRow(label(text, "muted", wrap=False), self.sys_labels[key])
        row.addWidget(sys_card, 3)

        self.pow_form = QFormLayout()
        pow_card = card()
        pow_card.setLayout(self.pow_form)
        self.pow_labels: dict[str, object] = {}
        for key, text in [("fuente", "Alimentación"), ("bateria", "Batería"), ("salud", "Salud de la batería"),
                          ("plan", "Plan de energía"), ("perfil", "Perfil activo"), ("restauracion", "Punto de restauración")]:
            self.pow_labels[key] = label("…")
            self.pow_form.addRow(label(text, "muted", wrap=False), self.pow_labels[key])
        row.addWidget(pow_card, 2)
        self.root.addLayout(row)

        buttons = QHBoxLayout()
        self.revert_all = QPushButton("Restaurar todo a como estaba")
        self.revert_all.clicked.connect(self._revert_all)
        buttons.addWidget(self.revert_all)
        buttons.addStretch()
        self.root.addLayout(buttons)
        self.root.addStretch()

    # -- datos -------------------------------------------------------------------------------
    def refresh(self) -> None:
        self.win.run_async(detect_system, self._show_info, message="Detectando el equipo…")
        self._show_state()

    def _show_info(self, info: SystemInfo) -> None:
        self.info = info
        s = self.sys_labels
        s["equipo"].setText(f"{info.manufacturer} {info.model}")
        s["tipo"].setText(("Portátil" if info.is_laptop else "Sobremesa") + f"  ({info.laptop_reason})")
        s["windows"].setText(info.windows)
        s["cpu"].setText(f"{info.cpu.name} — {info.cpu.cores} núcleos / {info.cpu.threads} hilos" if info.cpu else "—")
        s["gpu"].setText("\n".join(f"{g.name} ({g.kind}{f', {g.vram_gb} GB' if g.vram_gb else ''})" for g in info.gpus) or "—")
        s["ram"].setText(f"{info.ram_gb} GB" + (f" a {info.ram_speed_mhz} MHz" if info.ram_speed_mhz else ""))
        s["discos"].setText("\n".join(f"{d.name} ({d.kind}, {d.size_gb} GB)" for d in info.disks) or "—")

        p = self.pow_labels
        if info.battery:
            h = info.battery.health_percent
            p["salud"].setText(f"{h} %  (ciclos: {info.battery.cycles if info.battery.cycles is not None else '—'})" if h is not None else "no disponible en este equipo")
        else:
            p["salud"].setText("— (equipo sin batería)")
        if info.power_scheme:
            guid, name = info.power_scheme
            p["plan"].setText(f"{name}" + ("" if guid in KNOWN_SCHEMES else " (personalizado)"))
        self.win.set_laptop(info.is_laptop)

    def _show_state(self) -> None:
        cur = self.ctx.manager.current()
        self.pow_labels["perfil"].setText(PROFILES[cur["id"]].name if cur and cur["id"] in PROFILES else "Ninguno")
        rp = self.ctx.engine.store.restore_point
        self.pow_labels["restauracion"].setText("Creado" if rp else "Aún no (se crea antes del primer cambio)")
        self.revert_all.setEnabled(bool(self.ctx.engine.store.applied))

    def update_power(self, status: PowerStatus) -> None:
        p = self.pow_labels
        p["fuente"].setText(status.source.capitalize())
        if status.has_battery:
            extra = " (cargando)" if status.charging else ""
            if status.plugged_in is False:
                extra += f" — quedan {_fmt_time(status.seconds_left)}"
            p["bateria"].setText(f"{status.battery_percent} %{extra}")
        else:
            p["bateria"].setText("— (sin batería)")

    # -- acciones ----------------------------------------------------------------------------
    def _revert_all(self) -> None:
        n = len(self.ctx.engine.store.applied)
        ok = QMessageBox.question(self, "Restaurar todo", f"Se devolverán a su valor original los {n} ajustes que OptiWin ha cambiado. ¿Continuar?")
        if ok != QMessageBox.StandardButton.Yes:
            return

        def work():
            results = self.ctx.engine.revert_all()
            if not self.ctx.engine.store.applied:
                self.ctx.engine.store.set_active_profile(None)
            return results

        self.win.run_async(work, lambda res: self.win.finish_change("Restaurar todo", res), message="Restaurando…")
