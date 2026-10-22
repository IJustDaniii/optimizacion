from optiwin.core.detection import BatteryInfo, classify_laptop, gpu_kind, windows_label
from optiwin.core.power_status import parse_scheme_line


def test_laptop_con_bateria_y_chasis():
    assert classify_laptop([10], True)[0] is True


def test_sobremesa_sin_bateria():
    assert classify_laptop([3], False)[0] is False


def test_chasis_portatil_sin_bateria_es_sobremesa():
    ok, reason = classify_laptop([9], False)
    assert ok is False and "sin batería" in reason


def test_bateria_con_chasis_raro_es_portatil():
    assert classify_laptop([1], True)[0] is True


def test_gpu_kind():
    assert gpu_kind("NVIDIA GeForce GTX 1650") == "dedicada"
    assert gpu_kind("AMD Radeon(TM) Graphics") == "integrada"
    assert gpu_kind("Microsoft Basic Display Adapter") == "desconocida"


def test_windows_label():
    assert windows_label(26200, "25H2").startswith("Windows 11")
    assert windows_label(19045, "22H2").startswith("Windows 10")


def test_parse_scheme_espanol():
    line = "GUID del esquema de energía: 381b4222-f694-41f0-9685-ff5bb260df2e  (Equilibrado)"
    assert parse_scheme_line(line) == ("381b4222-f694-41f0-9685-ff5bb260df2e", "Equilibrado")


def test_parse_scheme_ingles():
    line = "Power Scheme GUID: 8C5E7FDA-E8BF-4A96-9A85-A6E23A8C635C  (High performance)"
    assert parse_scheme_line(line)[1] == "High performance"


def test_battery_health():
    assert BatteryInfo(50000, 40000, 100).health_percent == 80.0
    assert BatteryInfo(None, 40000, None).health_percent is None
