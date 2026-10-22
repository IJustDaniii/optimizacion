"""Contrato común de todos los ajustes. Añadir un ajuste = una clase/instancia nueva."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any


class Risk(StrEnum):
    LOW = "bajo"
    MEDIUM = "medio"
    HIGH = "alto"


class Tweak(ABC):
    """Un ajuste reversible.

    - `read()` devuelve una "foto" (JSON-serializable) del estado actual.
    - `apply(value)` cambia el sistema.
    - `restore(snapshot)` devuelve el sistema EXACTAMENTE a la foto guardada.
    El motor (engine.py) se encarga de guardar la foto, registrar logs y pedir permisos.
    """

    id: str
    name: str
    category: str  # energia, rendimiento, juegos, visual, limpieza...
    description: str  # qué hace, en cristiano
    risk: Risk
    benefit: str  # beneficio esperado (honesto)
    default_value: Any
    requires_admin: bool = False
    admin_reason: str = ""
    reboot_required: bool = False

    @abstractmethod
    def read(self) -> Any: ...

    @abstractmethod
    def apply(self, value: Any) -> None: ...

    @abstractmethod
    def restore(self, snapshot: Any) -> None: ...

    @abstractmethod
    def matches(self, snapshot: Any, value: Any) -> bool:
        """¿El estado `snapshot` ya equivale a haber aplicado `value`?"""

    def summarize(self, snapshot: Any) -> str:
        """Texto corto de una foto, para mostrar al usuario."""
        return str(snapshot)

    def is_available(self) -> tuple[bool, str]:
        """False + motivo si este equipo no soporta el ajuste."""
        return True, ""
