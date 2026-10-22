"""Objetos compartidos de la aplicación (los mismos del CLI: la GUI no duplica lógica)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from optiwin.cleanup.catalog import build_categories
from optiwin.cleanup.cleaner import Cleaner
from optiwin.core.config import Config
from optiwin.core.engine import Engine
from optiwin.core.logger import setup_logging
from optiwin.core.paths import app_home
from optiwin.core.state import StateStore
from optiwin.profiles.manager import ProfileManager
from optiwin.tweaks import build_catalog


@dataclass
class AppContext:
    home: Path
    log: logging.Logger
    config: Config
    engine: Engine
    manager: ProfileManager

    def new_cleaner(self) -> Cleaner:
        return Cleaner(build_categories(), self.home, self.log)

    def reload_catalog(self) -> None:
        """Hay que llamarlo si cambia la lista de juegos con GPU dedicada."""
        self.engine.catalog.clear()
        self.engine.catalog.update(build_catalog(self.config.gpu_apps))


def create_context() -> AppContext:
    home = app_home()
    log = setup_logging(home)
    config = Config(home / "config.json")
    engine = Engine(build_catalog(config.gpu_apps), StateStore(home / "state.json"), log)
    return AppContext(home, log, config, engine, ProfileManager(engine, config))
