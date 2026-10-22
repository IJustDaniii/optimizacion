# -*- mode: python ; coding: utf-8 -*-
# Genera dist/OptiWin/ con OptiWin.exe (interfaz, sin consola) y optiwin-cli.exe (consola).
# Se invoca desde packaging/build.py. Modo carpeta (onedir): arranca antes y da menos falsos
# positivos en antivirus que un único .exe autoextraíble.
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "src" / "optiwin" / "assets" / "optiwin.ico")
VERSION = str(ROOT / "packaging" / "version_info.txt")
ASSETS = (str(ROOT / "src" / "optiwin" / "assets"), "optiwin/assets")

common = dict(pathex=[str(ROOT / "src")], noarchive=False)

gui = Analysis(
    [str(ROOT / "packaging" / "gui_entry.py")],
    datas=[ASSETS],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtPdf", "PySide6.QtSvg", "PySide6.Qt3DCore", "PySide6.QtWebEngineCore"],
    **common,
)
cli = Analysis(
    [str(ROOT / "packaging" / "cli_entry.py")],
    excludes=["tkinter", "unittest", "PySide6", "shiboken6"],
    **common,
)
MERGE((gui, "OptiWin", "OptiWin"), (cli, "optiwin-cli", "optiwin-cli"))

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="OptiWin",
              console=False, icon=ICON, version=VERSION)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="optiwin-cli",
              console=True, icon=ICON, version=VERSION)

COLLECT(gui_exe, gui.binaries, gui.datas, cli_exe, cli.binaries, cli.datas, name="OptiWin")
