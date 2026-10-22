import winreg
from datetime import datetime, timedelta

import pytest

from optiwin.core.restore_point import interpret_result
from optiwin.tweaks import build_catalog
from optiwin.tweaks.base import Risk
from optiwin.tweaks.powercfg_tweak import SettingUnavailable, parse_current_values
from optiwin.tweaks.registry_tweak import RegistryValueTweak

TEST_KEY = r"Software\OptiWinTest"


@pytest.fixture
def reg_tweak():
    tweak = RegistryValueTweak(
        id="t.reg", name="t", category="t", description="d", risk=Risk.LOW, benefit="b",
        hive="HKCU", key=TEST_KEY + r"\Sub", value_name="Valor", default_value=1,
    )
    yield tweak
    for path in (TEST_KEY + r"\Sub", TEST_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass


def test_registro_valor_inexistente_se_borra_al_restaurar(reg_tweak):
    original = reg_tweak.read()
    assert original == {"exists": False}
    reg_tweak.apply(1)
    assert reg_tweak.read()["data"] == 1
    reg_tweak.restore(original)
    assert reg_tweak.read() == {"exists": False}


def test_registro_valor_existente_se_restaura_igual(reg_tweak):
    reg_tweak.apply(7)
    original = reg_tweak.read()
    reg_tweak.apply(0)
    assert reg_tweak.matches(reg_tweak.read(), 0)
    reg_tweak.restore(original)
    assert reg_tweak.read() == original


def test_hklm_exige_admin():
    t = RegistryValueTweak(
        id="x", name="x", category="x", description="d", risk=Risk.LOW, benefit="b",
        hive="HKLM", key="Software\\X", value_name="v", default_value=1,
    )
    assert t.requires_admin


ES = """GUID de plan de energía: 381b4222-f694-41f0-9685-ff5bb260df2e  (Equilibrado)
    Mínima configuración posible: 0x00000000
    Máxima configuración posible: 0x00000064
    Incremento de configuración posible: 0x00000001
    Unidades de configuración posibles: %
  Índice de configuración de corriente alterna actual: 0x00000064
  Índice de configuración de corriente continua actual: 0x00000050
"""
EN = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
    Possible Setting Index: 000
    Possible Setting Friendly Name: Off
    Possible Setting Index: 002
    Possible Setting Friendly Name: Maximum power savings
  Current AC Power Setting Index: 0x00000000
  Current DC Power Setting Index: 0x00000002
"""


def test_parse_powercfg_es_y_en():
    assert parse_current_values(ES) == (100, 80)
    assert parse_current_values(EN) == (0, 2)


def test_parse_powercfg_ajuste_oculto():
    with pytest.raises(SettingUnavailable):
        parse_current_values("GUID de plan de energía: 381b4222  (Equilibrado)\n")


def test_restore_point_interpretacion():
    now = datetime(2026, 10, 22, 12, 0)
    assert interpret_result(3, 4, None, None, now).created
    reciente = interpret_result(4, 4, (now - timedelta(hours=5)).isoformat(), None, now)
    assert reciente.ok and not reciente.created
    viejo = interpret_result(4, 4, (now - timedelta(days=3)).isoformat(), "deshabilitado", now)
    assert not viejo.ok and "deshabilitado" in viejo.message
    assert not interpret_result(0, 0, None, None, now).ok


def test_catalogo_ids_unicos_y_metadatos_completos():
    catalog = build_catalog()
    assert len(catalog) >= 5
    for t in catalog.values():
        assert t.description and t.benefit and t.risk in Risk and t.id == t.id.lower()
