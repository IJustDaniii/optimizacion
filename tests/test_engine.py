import logging

import pytest

from optiwin.core.engine import Engine
from optiwin.core.restore_point import RestorePointResult
from optiwin.core.state import StateStore
from optiwin.tweaks.base import Risk, Tweak


class FakeTweak(Tweak):
    """Ajuste en memoria: el 'sistema' es un diccionario compartido."""

    def __init__(self, id, system, *, admin=False, fail_apply=False):
        self.id, self.name, self.category = id, f"Fake {id}", "test"
        self.description, self.risk, self.benefit = "d", Risk.LOW, "b"
        self.default_value = 1
        self.requires_admin = admin
        self.admin_reason = "porque sí"
        self.system, self.fail_apply = system, fail_apply

    def read(self):
        return {"v": self.system.get(self.id)}

    def apply(self, value):
        if self.fail_apply:
            raise OSError("boom")
        self.system[self.id] = value

    def restore(self, snapshot):
        if snapshot["v"] is None:
            self.system.pop(self.id, None)
        else:
            self.system[self.id] = snapshot["v"]

    def matches(self, snapshot, value):
        return snapshot["v"] == value

    def summarize(self, snapshot):
        return str(snapshot["v"])


@pytest.fixture
def make(tmp_path):
    def _make(*tweaks, admin=True, rp_ok=True):
        system = tweaks[0].system if tweaks else {}
        calls = {"rp": 0}

        def rp():
            calls["rp"] += 1
            return RestorePointResult(rp_ok, rp_ok, "msg")

        engine = Engine(
            {t.id: t for t in tweaks},
            StateStore(tmp_path / "state.json"),
            logging.getLogger("test"),
            admin_check=lambda: admin,
            restore_point_fn=rp,
        )
        return engine, system, calls, tmp_path

    return _make


def test_aplicar_y_deshacer_restaura_el_original(make):
    system = {"a": 5}
    engine, _, _, _ = make(FakeTweak("a", system))
    assert engine.apply("a", 9).status == "applied"
    assert system["a"] == 9
    assert engine.revert("a").status == "reverted"
    assert system["a"] == 5


def test_original_ausente_se_borra_al_deshacer(make):
    system = {}
    engine, _, _, _ = make(FakeTweak("a", system))
    engine.apply("a", 3)
    engine.revert("a")
    assert "a" not in system


def test_simulacion_no_cambia_ni_guarda_nada(make):
    system = {"a": 5}
    engine, _, calls, tmp = make(FakeTweak("a", system))
    r = engine.apply("a", 9, dry_run=True)
    assert r.status == "dry_run" and "5" in r.message and "9" in r.message
    assert system["a"] == 5
    assert calls["rp"] == 0
    assert engine.store.applied == {}


def test_punto_de_restauracion_solo_una_vez_y_antes_del_primer_cambio(make):
    system = {}
    engine, _, calls, _ = make(FakeTweak("a", system), FakeTweak("b", system))
    engine.apply("a", 1)
    engine.apply("b", 1)
    assert calls["rp"] == 1


def test_si_falla_el_punto_de_restauracion_no_se_cambia_nada(make):
    system = {"a": 5}
    engine, _, _, _ = make(FakeTweak("a", system), rp_ok=False)
    r = engine.apply("a", 9)
    assert r.status == "error"
    assert system["a"] == 5
    assert engine.store.applied == {}


def test_sin_admin_no_se_puede_crear_punto_y_se_explica(make):
    system = {"a": 5}
    engine, _, calls, _ = make(FakeTweak("a", system), admin=False)
    r = engine.apply("a", 9)
    assert r.status == "error" and r.needs_admin and "--elevar" in r.message
    assert system["a"] == 5 and calls["rp"] == 0


def test_omitir_punto_de_restauracion_es_explicito(make):
    system = {"a": 5}
    engine, _, calls, _ = make(FakeTweak("a", system), admin=False)
    assert engine.apply("a", 9, skip_restore_point=True).status == "applied"
    assert calls["rp"] == 0


def test_ajuste_que_requiere_admin(make):
    system = {"a": 5}
    engine, _, _, _ = make(FakeTweak("a", system, admin=True), admin=False)
    r = engine.apply("a", 9, skip_restore_point=True)
    assert r.status == "error" and r.needs_admin and "porque sí" in r.message


def test_mismo_valor_no_hace_nada(make):
    system = {"a": 5}
    engine, _, calls, _ = make(FakeTweak("a", system))
    assert engine.apply("a", 5).status == "skipped"
    assert calls["rp"] == 0 and engine.store.applied == {}


def test_reaplicar_no_pisa_el_original(make):
    system = {"a": 5}
    engine, _, _, _ = make(FakeTweak("a", system))
    engine.apply("a", 7)
    engine.apply("a", 9)
    engine.revert("a")
    assert system["a"] == 5


def test_fallo_al_aplicar_no_guarda_estado(make):
    system = {"a": 5}
    engine, _, _, _ = make(FakeTweak("a", system, fail_apply=True))
    assert engine.apply("a", 9).status == "error"
    assert engine.store.applied == {}


def test_restaurar_todo_en_orden_inverso_y_persistencia(make, tmp_path):
    system = {"a": 1, "b": 2, "c": 3}
    engine, _, _, home = make(FakeTweak("a", system), FakeTweak("b", system), FakeTweak("c", system))
    for i in "abc":
        engine.apply(i, 99)

    # Otra instancia (como reabrir la app) debe ver el estado guardado
    engine2 = Engine(
        engine.catalog, StateStore(home / "state.json"), logging.getLogger("test"), admin_check=lambda: True
    )
    results = engine2.revert_all()
    assert [r.tweak_id for r in results] == ["c", "b", "a"]
    assert system == {"a": 1, "b": 2, "c": 3}
    assert engine2.store.applied == {}


def test_ajuste_inexistente(make):
    engine, _, _, _ = make(FakeTweak("a", {}))
    assert engine.apply("zzz").status == "error"
    assert engine.revert("zzz").status == "error"


def test_estado_corrupto_se_aparta_sin_perderlo(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{no es json", encoding="utf-8")
    store = StateStore(path)
    assert store.applied == {}
    assert (tmp_path / "state.corrupt.json").exists()
