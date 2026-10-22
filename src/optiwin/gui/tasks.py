"""Ejecución de trabajo pesado fuera del hilo de la interfaz (para que la ventana nunca se congele)."""

from __future__ import annotations

import itertools
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Job(QRunnable):
    def __init__(self, job_id: int, fn: Callable[[], Any], runner: TaskRunner):
        super().__init__()
        self.job_id, self.fn, self.runner = job_id, fn, runner

    def run(self) -> None:
        try:
            result, error = self.fn(), None
        except Exception as exc:  # se muestra al usuario; no debe tumbar el hilo
            result, error = None, f"{exc}\n\n{traceback.format_exc()}"
        self.runner.finished.emit(self.job_id, result, error)


class TaskRunner(QObject):
    """Vive en el hilo de la interfaz: las señales de los hilos de trabajo llegan aquí en cola,
    así los callbacks (on_done / on_error) siempre se ejecutan en el hilo de la interfaz."""

    finished = Signal(int, object, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ids = itertools.count(1)
        self._callbacks: dict[int, tuple[Callable, Callable | None]] = {}
        self._pool = QThreadPool.globalInstance()
        self.finished.connect(self._dispatch)

    def submit(self, fn: Callable[[], Any], on_done: Callable[[Any], None], on_error: Callable[[str], None] | None = None) -> None:
        job_id = next(self._ids)
        self._callbacks[job_id] = (on_done, on_error)
        self._pool.start(_Job(job_id, fn, self))

    @Slot(int, object, object)
    def _dispatch(self, job_id: int, result: Any, error: str | None) -> None:
        on_done, on_error = self._callbacks.pop(job_id)
        if error is None:
            on_done(result)
        elif on_error:
            on_error(error)
