"""Registro (log) de todo lo aplicado. Solo escribe en disco local; nada sale del equipo."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "optiwin"


def log_file(home: Path) -> Path:
    return home / "logs" / "optiwin.log"


def setup_logging(home: Path) -> logging.Logger:
    """Configura el logger de la app (idempotente: se puede llamar varias veces)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    path = log_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=512_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(handler)
    return logger


def read_log_tail(home: Path, lines: int = 30) -> list[str]:
    path = log_file(home)
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
