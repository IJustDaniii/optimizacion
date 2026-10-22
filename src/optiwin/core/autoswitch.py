"""Cambio automático de perfil al enchufar/desenchufar el cargador.

Sondeo cada pocos segundos con GetSystemPowerStatus (una llamada a la API, coste de CPU despreciable).
Se exige que la nueva fuente se mantenga en lecturas consecutivas para ignorar parpadeos de
cargadores flojos.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from optiwin.core.power_status import PowerStatus, read_power_status


def source_of(status: PowerStatus) -> str | None:
    """'ac' | 'dc' | None (sin batería o desconocido: no hay nada que conmutar)."""
    if not status.has_battery or status.plugged_in is None:
        return None
    return "ac" if status.plugged_in else "dc"


class AutoSwitcher:
    def __init__(
        self,
        on_change: Callable[[str], None],
        *,
        read_status: Callable[[], PowerStatus] = read_power_status,
        interval: float = 2.0,
        stable_reads: int = 2,
    ):
        self.on_change, self.read_status = on_change, read_status
        self.interval, self.stable_reads = interval, stable_reads
        self.current: str | None = None
        self._candidate: str | None = None
        self._count = 0

    def poll_once(self) -> None:
        """Una lectura. Llama a on_change(fuente) la primera vez y cuando la fuente cambia de forma estable."""
        source = source_of(self.read_status())
        if source is None:
            return
        if source == self.current:
            self._candidate, self._count = None, 0
            return
        if source != self._candidate:
            self._candidate, self._count = source, 1
        else:
            self._count += 1
        # La primera lectura del arranque se acepta en seguida; los cambios exigen estabilidad.
        if self.current is None or self._count >= self.stable_reads:
            self.current, self._candidate, self._count = source, None, 0
            self.on_change(source)

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.poll_once()
            stop.wait(self.interval)
