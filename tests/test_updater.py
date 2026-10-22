import hashlib
import io

import pytest

from optiwin.core import updater
from optiwin.core.updater import ReleaseInfo, UpdateError, check_for_update, download_installer, parse_version, release_from_json

GOOD_HASH = "a" * 64
BASE = "https://github.com/IJustDaniii/optimizacion/releases/download/v0.6.0/"


def release(tag="v0.6.0", **over):
    name = f"OptiWin-Setup-{tag.lstrip('v')}.exe"
    data = {
        "tag_name": tag,
        "body": "Notas",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": name, "browser_download_url": BASE + name, "size": 1000, "digest": f"sha256:{GOOD_HASH}"},
        ],
    }
    data.update(over)
    return data


def test_parse_version():
    assert parse_version("v1.2.3") == (1, 2, 3) and parse_version("0.5.0") == (0, 5, 0)
    assert parse_version("v0.10.0") > parse_version("v0.9.9")  # no es comparación de texto
    for bad in ("", "latest", "1.2", "v1.2.3-beta", "1.2.3.4"):
        with pytest.raises(UpdateError):
            parse_version(bad)


def test_hay_actualizacion_solo_si_es_mas_nueva():
    fetch = lambda url: release("v0.6.0")
    assert check_for_update("0.5.0", fetch_json=fetch).version == "0.6.0"
    assert check_for_update("0.6.0", fetch_json=fetch) is None
    assert check_for_update("1.0.0", fetch_json=fetch) is None


def test_ignora_borradores_y_prereleases():
    for flag in ("draft", "prerelease"):
        with pytest.raises(UpdateError):
            release_from_json(release(**{flag: True}))


def test_exige_instalador_con_el_nombre_exacto():
    data = release()
    data["assets"][0]["name"] = "malware.exe"
    with pytest.raises(UpdateError):
        release_from_json(data)


def test_rechaza_hosts_y_esquemas_no_permitidos():
    for url in ("http://github.com/x/OptiWin-Setup-0.6.0.exe", "https://evil.example.com/OptiWin-Setup-0.6.0.exe",
                "https://github.com.evil.com/OptiWin-Setup-0.6.0.exe"):
        data = release()
        data["assets"][0]["browser_download_url"] = url
        with pytest.raises(UpdateError):
            release_from_json(data)


def test_sin_hash_publicado_no_se_descarga():
    data = release()
    del data["assets"][0]["digest"]
    with pytest.raises(UpdateError, match="SHA-256"):
        release_from_json(data)


def test_hash_desde_archivo_sha256_y_conflicto_con_digest():
    data = release()
    del data["assets"][0]["digest"]
    data["assets"].append({"name": "OptiWin-Setup-0.6.0.exe.sha256", "browser_download_url": BASE + "x.sha256"})
    info = release_from_json(data, fetch_text=lambda url: f"{'B' * 64}  OptiWin-Setup-0.6.0.exe\n")
    assert info.sha256 == "b" * 64

    data["assets"][0]["digest"] = f"sha256:{GOOD_HASH}"
    with pytest.raises(UpdateError, match="no coinciden"):
        release_from_json(data, fetch_text=lambda url: "b" * 64)


def test_redireccion_a_host_no_permitido_se_bloquea():
    handler = updater._SafeRedirects()
    with pytest.raises(UpdateError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com/x.exe")


# --- descarga -------------------------------------------------------------------------------------------------

class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def info_for(payload: bytes, sha: str | None = None) -> ReleaseInfo:
    return ReleaseInfo("0.6.0", "v0.6.0", "", "OptiWin-Setup-0.6.0.exe", BASE + "OptiWin-Setup-0.6.0.exe",
                       len(payload), sha or hashlib.sha256(payload).hexdigest())


def test_descarga_correcta_verifica_hash(tmp_path):
    payload = b"instalador" * 1000
    seen = []
    path = download_installer(info_for(payload), tmp_path, lambda d, t: seen.append((d, t)),
                              opener=lambda url: FakeResp(payload))
    assert path.read_bytes() == payload and seen[-1][0] == len(payload)
    assert not list(tmp_path.glob("*.part"))


def test_hash_incorrecto_borra_la_descarga(tmp_path):
    payload = b"contenido manipulado"
    with pytest.raises(UpdateError, match="no coincide"):
        download_installer(info_for(payload, sha="0" * 64), tmp_path, opener=lambda url: FakeResp(payload))
    assert list(tmp_path.iterdir()) == []


def test_nombre_de_instalador_invalido_no_descarga(tmp_path):
    bad = ReleaseInfo("0.6.0", "v0.6.0", "", "..\\evil.exe", BASE + "x", 1, GOOD_HASH)
    with pytest.raises(UpdateError):
        download_installer(bad, tmp_path, opener=lambda url: FakeResp(b"x"))
