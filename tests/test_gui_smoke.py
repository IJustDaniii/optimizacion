"""Prueba de humo de la GUI sin pantalla (Qt 'offscreen'): todas las páginas cargan y la ventana no se queda bloqueada."""

import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def wait_idle(app, window, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if window._busy == 0:
            return
        time.sleep(0.02)
    raise AssertionError("La ventana se quedó ocupada")


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OPTIWIN_HOME", str(tmp_path))
    from optiwin.gui.context import create_context
    from optiwin.gui.main_window import MainWindow

    win = MainWindow(create_context())
    win.show()
    wait_idle(qapp, win)
    yield win
    win._really_quit = True
    win.close()


def test_todas_las_paginas_cargan(qapp, window):
    for row in range(window.nav.count()):
        window.nav.setCurrentRow(row)
        wait_idle(qapp, window)
    assert window.nav.count() == 6
    assert window.home.info is not None and window.home.info.cpu is not None


def test_pagina_de_ajustes_lista_todo_el_catalogo(qapp, window):
    window.nav.setCurrentRow(2)
    wait_idle(qapp, window)
    page = window.pages[2]
    assert set(page.rows) == set(window.ctx.engine.catalog)
    assert page.tree.topLevelItemCount() >= 3


def test_simular_no_cambia_nada(qapp, window, monkeypatch):
    from optiwin.gui import widgets

    shown = []
    monkeypatch.setattr(widgets.TextDialog, "exec", lambda self: shown.append(self.windowTitle()))
    monkeypatch.setattr("optiwin.gui.pages.profiles.TextDialog.exec", lambda self: shown.append(self.windowTitle()))
    window.profiles._simulate("ahorro")
    wait_idle(qapp, window)
    assert shown and window.ctx.engine.store.applied == {}


def test_limpieza_solo_analiza_y_no_marca_riesgo_medio(qapp, window):
    window.nav.setCurrentRow(3)
    page = window.pages[3]
    page._scan()
    wait_idle(qapp, window, timeout=120)
    assert page.plan is not None
    from PySide6.QtCore import Qt

    for i in range(page.tree.topLevelItemCount()):
        item = page.tree.topLevelItem(i)
        cid = item.data(0, Qt.ItemDataRole.UserRole)
        if page.cleaner.categories[cid].risk.value != "bajo" and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            assert item.checkState(0) == Qt.CheckState.Unchecked
