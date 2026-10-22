"""Catálogo de ajustes. Para añadir uno: créalo en su módulo y aparecerá aquí automáticamente."""

from __future__ import annotations

from collections.abc import Iterable

from optiwin.tweaks import gaming, power, visual
from optiwin.tweaks.base import Tweak

_MODULES = (power, gaming, visual)


def build_catalog(gpu_apps: Iterable[str] = ()) -> dict[str, Tweak]:
    """Catálogo estático + un ajuste de GPU por cada juego añadido por el usuario."""
    catalog: dict[str, Tweak] = {}
    items = [t for module in _MODULES for t in module.tweaks()]
    items += [gaming.gpu_app_tweak(exe) for exe in gpu_apps]
    for tweak in items:
        if tweak.id in catalog:
            raise ValueError(f"Id de ajuste duplicado: {tweak.id}")
        catalog[tweak.id] = tweak
    return catalog
