import logging
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from optiwin.cleanup.catalog import build_categories
from optiwin.cleanup.categories import FileCategory, RecycleBinCategory, ScanResult
from optiwin.cleanup.cleaner import Cleaner, ConfirmationRequired, format_size
from optiwin.cleanup.safety import UnsafePath, assert_safe_root, is_within


def make_file(path: Path, size=100, age_hours=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_hours:
        t = time.time() - age_hours * 3600
        os.utime(path, (t, t))
    return path


def cleaner_for(tmp_path, *cats, admin=True, running=()):
    return Cleaner(list(cats), tmp_path / "home", logging.getLogger("test"),
                   admin_check=lambda: admin, running_names=lambda: set(running))


def cat(root: Path, **kw):
    return FileCategory(id=kw.pop("id", "t"), name="T", description="d", roots_fn=lambda: [root], **kw)


# --- seguridad de rutas ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    [
        "C:\\",
        "C:\\Users",
        os.environ["USERPROFILE"],
        os.environ["SystemRoot"],
        os.environ["ProgramFiles"],
        os.path.join(os.environ["USERPROFILE"], "Documents"),
        os.path.join(os.environ["USERPROFILE"], "Desktop", "cosas"),
        os.path.join(os.environ["USERPROFILE"], "Downloads"),
        os.path.join(os.environ["USERPROFILE"], "OneDrive", "x"),
        "D:\\Documentos\\x",
        "relativa\\ruta",
    ],
)
def test_raices_peligrosas_se_rechazan(bad):
    with pytest.raises(UnsafePath):
        assert_safe_root(bad)


def test_raices_legitimas_se_aceptan(tmp_path):
    assert assert_safe_root(tmp_path)
    assert assert_safe_root(Path(os.environ["SystemRoot"]) / "Temp")
    assert assert_safe_root(Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "Default" / "Cache")


def test_catalogo_real_solo_tiene_raices_seguras():
    for c in build_categories():
        if isinstance(c, FileCategory):
            for root in c._roots_fn():
                assert_safe_root(root)  # incluso las que no existen en esta máquina


def test_catalogo_nunca_apunta_a_datos_sensibles_de_navegador():
    sensibles = {"cookies", "login data", "history", "web data", "network", "bookmarks", "preferences", "sessions"}
    for c in build_categories():
        if isinstance(c, FileCategory):
            for root in c._roots_fn():
                assert not sensibles & {p.lower() for p in root.parts}, root


def test_is_within(tmp_path):
    root = Path(os.path.realpath(tmp_path))
    assert is_within(root / "a" / "b.txt", root)
    assert not is_within(root, root)
    assert not is_within(root.parent / "otro.txt", root)
    assert not is_within(root / ".." / "x.txt", root)


# --- análisis y borrado -----------------------------------------------------------------------------

def test_scan_no_borra_nada_y_cuenta_bien(tmp_path):
    root = tmp_path / "temp"
    make_file(root / "a.tmp", 100)
    make_file(root / "sub" / "b.tmp", 300)
    plan = cleaner_for(tmp_path, cat(root)).scan()
    assert plan.scans["t"].item_count == 2 and plan.scans["t"].total_bytes == 400
    assert (root / "a.tmp").exists() and (root / "sub" / "b.tmp").exists()


def test_borrar_exige_confirmacion(tmp_path):
    root = tmp_path / "temp"
    make_file(root / "a.tmp")
    cleaner = cleaner_for(tmp_path, cat(root))
    plan = cleaner.scan()
    with pytest.raises(ConfirmationRequired):
        cleaner.clean(plan, ["t"], confirmed=False)
    with pytest.raises(ConfirmationRequired):
        cleaner.clean(plan, ["t"], confirmed="si")  # solo True literal vale
    assert (root / "a.tmp").exists()


def test_borra_lo_analizado_y_poda_carpetas_vacias_pero_no_la_raiz(tmp_path):
    root = tmp_path / "temp"
    make_file(root / "a.tmp", 100)
    make_file(root / "sub" / "deep" / "b.tmp", 300)
    cleaner = cleaner_for(tmp_path, cat(root))
    reports = cleaner.clean(cleaner.scan(), ["t"], confirmed=True)
    assert reports[0].deleted_files == 2 and reports[0].freed_bytes == 400
    assert root.is_dir() and list(root.iterdir()) == []


def test_filtro_de_nombre_y_edad_minima(tmp_path):
    root = tmp_path / "x"
    make_file(root / "viejo.dmp", age_hours=48)
    make_file(root / "nuevo.dmp")  # reciente: se conserva
    make_file(root / "otro.txt", age_hours=48)  # no coincide con el filtro
    c = cat(root, include=lambda n: n.endswith(".dmp"), min_age_hours=24)
    cleaner = cleaner_for(tmp_path, c)
    cleaner.clean(cleaner.scan(), ["t"], confirmed=True)
    assert not (root / "viejo.dmp").exists()
    assert (root / "nuevo.dmp").exists() and (root / "otro.txt").exists()


def test_carpetas_protegidas_de_primer_nivel_no_se_tocan(tmp_path):
    root = tmp_path / "x"
    make_file(root / "Claude" / "trabajo.img", age_hours=999)  # coincide sin importar mayúsculas
    make_file(root / "otra" / "a.tmp", age_hours=999)
    make_file(root / "sub" / "claude" / "b.tmp", age_hours=999)  # solo protege el primer nivel
    cleaner = cleaner_for(tmp_path, cat(root, exclude_top_level=("claude",)))
    plan = cleaner.scan()
    assert any("excluy" in n or "protegidas" in n for n in plan.scans["t"].notes)
    cleaner.clean(plan, ["t"], confirmed=True)
    assert (root / "Claude" / "trabajo.img").exists()
    assert not (root / "otra" / "a.tmp").exists() and not (root / "sub" / "claude" / "b.tmp").exists()


def test_desglose_por_carpeta(tmp_path):
    root = tmp_path / "x"
    make_file(root / "grande" / "a.bin", 900)
    make_file(root / "grande" / "sub" / "b.bin", 100)
    make_file(root / "pequena" / "c.bin", 10)
    make_file(root / "suelto.bin", 5)
    scan = cleaner_for(tmp_path, cat(root)).scan().scans["t"]
    assert scan.breakdown(2) == [("grande", 1000), ("pequena", 10)]


def test_temp_usuario_real_protege_claude_y_exige_7_dias():
    temp = next(c for c in build_categories() if c.id == "temp_usuario")
    assert "claude" in temp.exclude_top_level and temp.min_age_hours >= 24 * 7


def test_archivo_modificado_tras_el_analisis_no_se_borra(tmp_path):
    root = tmp_path / "x"
    f = make_file(root / "a.tmp", age_hours=48)
    cleaner = cleaner_for(tmp_path, cat(root, min_age_hours=24))
    plan = cleaner.scan()
    f.write_bytes(b"nuevo contenido")  # alguien lo toca entre la vista previa y el borrado
    report = cleaner.clean(plan, ["t"], confirmed=True)[0]
    assert f.exists() and report.skipped == 1 and report.deleted_files == 0


def test_solo_se_borra_lo_que_se_mostro(tmp_path):
    root = tmp_path / "x"
    make_file(root / "a.tmp")
    cleaner = cleaner_for(tmp_path, cat(root))
    plan = cleaner.scan()
    make_file(root / "aparecido_despues.tmp")  # no estaba en la vista previa
    cleaner.clean(plan, ["t"], confirmed=True)
    assert (root / "aparecido_despues.tmp").exists()


def test_plan_manipulado_con_ruta_fuera_de_la_raiz_no_borra(tmp_path):
    root = tmp_path / "x"
    root.mkdir()
    ajeno = make_file(tmp_path / "importante.docx")
    cleaner = cleaner_for(tmp_path, cat(root))
    plan = cleaner.scan()
    plan.scans["t"].files.append((str(ajeno), 100))  # intento de colar un archivo externo
    plan.scans["t"].files.append((str(root / ".." / "importante.docx"), 100))  # y con ..
    report = cleaner.clean(plan, ["t"], confirmed=True)[0]
    assert ajeno.exists() and report.skipped == 2


def test_las_uniones_no_se_atraviesan_ni_se_borran(tmp_path):
    root, fuera = tmp_path / "x", tmp_path / "fuera"
    make_file(root / "a.tmp")
    secreto = make_file(fuera / "secreto.docx")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "enlace"), str(fuera)], check=True, capture_output=True)
    cleaner = cleaner_for(tmp_path, cat(root))
    plan = cleaner.scan()
    assert all("secreto" not in p for p, _ in plan.scans["t"].files)
    cleaner.clean(plan, ["t"], confirmed=True)
    assert secreto.exists() and (root / "enlace").exists()
    os.rmdir(root / "enlace")


def test_archivo_de_solo_lectura_se_borra(tmp_path):
    root = tmp_path / "x"
    f = make_file(root / "ro.tmp")
    os.chmod(f, stat.S_IREAD)
    cleaner = cleaner_for(tmp_path, cat(root))
    assert cleaner.clean(cleaner.scan(), ["t"], confirmed=True)[0].deleted_files == 1


def test_categoria_de_sistema_sin_admin_se_omite(tmp_path):
    root = tmp_path / "x"
    f = make_file(root / "a.tmp")
    cleaner = cleaner_for(tmp_path, cat(root, requires_admin=True), admin=False)
    plan = cleaner.scan()
    assert "t" in plan.blocked
    report = cleaner.clean(plan, ["t"], confirmed=True)[0]
    assert f.exists() and report.deleted_files == 0 and "Omitida" in report.notes[0]


def test_aviso_si_el_navegador_esta_abierto(tmp_path):
    root = tmp_path / "x"
    make_file(root / "a.tmp")
    c = cat(root, running_processes=("chrome.exe",))
    assert "t" in cleaner_for(tmp_path, c, running={"chrome.exe"}).scan().warnings
    assert "t" not in cleaner_for(tmp_path, c, running=set()).scan().warnings


def test_categoria_inexistente_y_manifiesto(tmp_path):
    root = tmp_path / "x"
    make_file(root / "a.tmp")
    cleaner = cleaner_for(tmp_path, cat(root))
    with pytest.raises(KeyError):
        cleaner.scan(["nope"])
    cleaner.clean(cleaner.scan(), ["t"], confirmed=True)
    manifests = list((tmp_path / "home" / "logs").glob("limpieza-*.txt"))
    assert len(manifests) == 1 and "a.tmp" in manifests[0].read_text(encoding="utf-8")


def test_raiz_que_no_existe_no_es_error(tmp_path):
    cleaner = cleaner_for(tmp_path, cat(tmp_path / "no_existe"))
    assert cleaner.scan().scans == {}


# --- papelera (sin tocar la real) --------------------------------------------------------------------

def test_papelera_no_vacia_sin_nada_que_vaciar(monkeypatch):
    llamadas = []
    monkeypatch.setattr(RecycleBinCategory, "_query", staticmethod(lambda: (0, 0)))
    monkeypatch.setattr(RecycleBinCategory, "_empty", staticmethod(lambda: llamadas.append(1) or 0))
    c = RecycleBinCategory()
    assert c.clean(c.scan()).deleted_files == 0 and not llamadas


def test_papelera_con_contenido(monkeypatch):
    monkeypatch.setattr(RecycleBinCategory, "_query", staticmethod(lambda: (5000, 3)))
    monkeypatch.setattr(RecycleBinCategory, "_empty", staticmethod(lambda: 0))
    c = RecycleBinCategory()
    scan = c.scan()
    assert scan.total_bytes == 5000 and scan.item_count == 3
    assert c.clean(scan).freed_bytes == 5000


def test_format_size():
    assert format_size(512) == "512 B" and format_size(1536) == "1.5 KB" and format_size(5 * 1024**3) == "5.0 GB"
