"""Construye el instalador: PyInstaller -> dist/OptiWin/ -> Inno Setup -> dist/OptiWin-Setup-X.Y.Z.exe (+ .sha256).

Uso (desde la raíz del repo, con el entorno de build instalado):
    python packaging/build.py
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def read_version() -> str:
    text = (ROOT / "src" / "optiwin" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"', text).group(1)


def write_version_info(version: str) -> None:
    v = tuple(int(p) for p in version.split(".")) + (0,)
    (ROOT / "packaging" / "version_info.txt").write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'IJustDaniii'),
      StringStruct('FileDescription', 'OptiWin - optimizador reversible para Windows'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'OptiWin'),
      StringStruct('OriginalFilename', 'OptiWin.exe'),
      StringStruct('ProductName', 'OptiWin'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def find_iscc() -> str:
    candidates = [os.environ.get("ISCC"), shutil.which("iscc")]
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            candidates.append(str(Path(base) / ("Programs" if base == os.environ.get("LOCALAPPDATA") else "") / "Inno Setup 6" / "ISCC.exe"))
    for c in candidates:
        if c and Path(c).is_file():
            return c
    sys.exit("No se encontró Inno Setup 6 (ISCC.exe). Instálalo o define la variable ISCC.")


def main() -> None:
    version = read_version()
    print(f"== Construyendo OptiWin {version}")
    write_version_info(version)
    shutil.rmtree(DIST / "OptiWin", ignore_errors=True)

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(ROOT / "build"), str(ROOT / "packaging" / "optiwin.spec")],
        check=True, cwd=ROOT,
    )

    subprocess.run([find_iscc(), f"/DAppVersion={version}", str(ROOT / "packaging" / "installer.iss")], check=True, cwd=ROOT)

    installer = DIST / f"OptiWin-Setup-{version}.exe"
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    (DIST / f"{installer.name}.sha256").write_text(f"{digest}  {installer.name}\n", encoding="utf-8")
    print(f"== Listo: {installer}  ({installer.stat().st_size / 1_048_576:.1f} MB)\n   SHA-256: {digest}")


if __name__ == "__main__":
    main()
