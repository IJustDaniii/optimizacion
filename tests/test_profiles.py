import logging

import pytest

from optiwin.core.autoswitch import AutoSwitcher, source_of
from optiwin.core.config import Config
from optiwin.core.engine import Engine
from optiwin.core.power_status import PowerStatus
from optiwin.core.process_closer import CloseReport, InvalidProcessName, RunningProcess, normalize_name
from optiwin.core.restore_point import RestorePointResult
from optiwin.core.state import StateStore
from optiwin.profiles.definitions import PROFILES, Profile
from optiwin.profiles.manager import ProfileManager
from optiwin.tweaks import build_catalog
from optiwin.tweaks.powercfg_tweak import PowerCfgSettingTweak
from tests.test_engine import FakeTweak


# --- Los perfiles reales deben ser coherentes con el catálogo real -----------------------------

def test_perfiles_usan_ajustes_y_valores_validos():
    catalog = build_catalog()
    for profile in PROFILES.values():
        for tweak_id, value in profile.steps.items():
            assert tweak_id in catalog, f"{profile.id}: ajuste inexistente {tweak_id}"
            tweak = catalog[tweak_id]
            if isinstance(tweak, PowerCfgSettingTweak):
                assert tweak.min_value <= value <= tweak.max_value, f"{profile.id}: {tweak_id}={value} fuera de rango"
            assert not tweak.requires_admin, f"{profile.id}: {tweak_id} requiere admin y rompería el cambio automático"


def test_perfil_ahorro_solo_toca_la_fuente_bateria_y_juegos_toca_ambas():
    assert all(not k.endswith("_enchufado") for k in PROFILES["ahorro"].steps)
    assert any(k.endswith("_enchufado") for k in PROFILES["juegos"].steps)
    assert any(k.endswith("_bateria") for k in PROFILES["juegos"].steps)


# --- ProfileManager con ajustes falsos ------------------------------------------------------------

@pytest.fixture
def env(tmp_path):
    system = {"a": 1, "b": 2, "c": 3}
    catalog = {i: FakeTweak(i, system) for i in system}
    engine = Engine(
        catalog,
        StateStore(tmp_path / "state.json"),
        logging.getLogger("test"),
        admin_check=lambda: True,
        restore_point_fn=lambda: RestorePointResult(True, True, "ok"),
    )
    config = Config(tmp_path / "config.json")
    profiles = {
        "p1": Profile("p1", "P1", "d", steps={"a": 10, "b": 20}),
        "p2": Profile("p2", "P2", "d", steps={"b": 21, "c": 30}),
        "p3": Profile("p3", "P3", "d", steps={"a": 5}, closes_processes=True),
    }
    closed = []
    running = [RunningProcess(100, "Discord.exe", r"C:\x\Discord.exe")]

    def close_fn(procs, force=False):
        closed.extend(procs)
        return CloseReport(closed=list(procs), survivors=[])

    manager = ProfileManager(
        engine, config, profiles, find_running=lambda names: running, close_fn=close_fn, reopen_fn=lambda exes: []
    )
    return manager, system, closed


def test_cambiar_de_perfil_devuelve_a_su_original_lo_que_el_nuevo_no_toca(env):
    manager, system, _ = env
    manager.activate("p1")
    assert system == {"a": 10, "b": 20, "c": 3}
    manager.activate("p2")
    assert system == {"a": 1, "b": 21, "c": 30}  # 'a' vuelve a su original
    manager.deactivate()
    assert system == {"a": 1, "b": 2, "c": 3}
    assert manager.current() is None and manager.store.applied == {}


def test_simulacion_de_perfil_no_cambia_nada(env):
    manager, system, closed = env
    report = manager.activate("p3", dry_run=True, close=True)
    assert system == {"a": 1, "b": 2, "c": 3}
    assert manager.current() is None and not closed
    assert any("Discord.exe" in n for n in report.notes)


def test_no_cierra_procesos_sin_pedirlo(env):
    manager, _, closed = env
    report = manager.activate("p3")
    assert not closed and any("--cerrar" in n for n in report.notes)


def test_cierra_procesos_al_pedirlo_y_guarda_ruta_para_reabrir(env):
    manager, _, closed = env
    manager.activate("p3", close=True)
    assert [p.name for p in closed] == ["Discord.exe"]
    assert manager.current()["closed_exes"] == [r"C:\x\Discord.exe"]


def test_perfil_inexistente(env):
    manager, _, _ = env
    assert not manager.activate("nope").ok


def test_ajuste_no_disponible_se_omite_sin_romper_el_perfil(env):
    manager, system, _ = env
    manager.engine.catalog["a"].is_available = lambda: (False, "no hay")
    report = manager.activate("p1")
    assert report.ok and system["b"] == 20 and system["a"] == 1


# --- Cambio automático ------------------------------------------------------------------------------

def status(plugged, battery=True):
    return PowerStatus(plugged, battery, False, 80 if battery else None, None, False)


def test_source_of():
    assert source_of(status(True)) == "ac" and source_of(status(False)) == "dc"
    assert source_of(status(True, battery=False)) is None
    assert source_of(status(None)) is None


def test_autoswitch_primera_lectura_inmediata_y_cambios_estables():
    events, seq = [], iter([True, True, False, False, False, True, False, False])
    sw = AutoSwitcher(events.append, read_status=lambda: status(next(seq)), stable_reads=2)
    for _ in range(8):
        sw.poll_once()
    # arranque ac; dc tras 2 lecturas estables; el parpadeo ac aislado se ignora; dc estable ya activo
    assert events == ["ac", "dc"]


def test_autoswitch_ignora_equipos_sin_bateria():
    events = []
    sw = AutoSwitcher(events.append, read_status=lambda: status(True, battery=False))
    sw.poll_once()
    assert events == []


# --- Procesos y configuración -------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "C:\\x\\a.exe", "svchost.exe", "MsMpEng", "explorer", "a*.exe", "optiwin.exe"])
def test_nombres_de_proceso_invalidos_o_protegidos(bad):
    with pytest.raises(InvalidProcessName):
        normalize_name(bad)


def test_normalize_name_anade_exe():
    assert normalize_name(" Discord ") == "Discord.exe"


def test_config_persistencia_y_defaults(tmp_path):
    c = Config(tmp_path / "config.json")
    assert c.auto_switch["enabled"] is False
    c.auto_switch["enabled"] = True
    c.close_list("juegos").append("Foo.exe")
    c.save()
    c2 = Config(tmp_path / "config.json")
    assert c2.auto_switch["enabled"] is True and "Foo.exe" in c2.close_list("juegos")
    assert c2.auto_switch["on_ac"] == "colegio"  # el resto de claves conserva el default
