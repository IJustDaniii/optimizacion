"""Actualizaciones desde GitHub Releases.

Privacidad: la ÚNICA conexión de red de OptiWin es una petición GET a la API pública de releases
del repositorio, y solo cuando el usuario la pide (botón) o lo ha activado en Configuración. No se
envía ningún dato del equipo ni identificador; solo viaja la cabecera User-Agent "OptiWin/<versión>".

Seguridad de la descarga:
  * Solo HTTPS y solo hosts de GitHub (también al seguir redirecciones).
  * El nombre del instalador debe ser exactamente OptiWin-Setup-<versión>.exe y coincidir con la etiqueta.
  * Se exige el hash SHA-256 publicado en la release y se verifica antes de ejecutar nada.
    (Límite honesto: hash y archivo viven en la misma release; no sustituye a una firma de código.)
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from optiwin import __version__

REPO = "IJustDaniii/optimizacion"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
INSTALLER_RE = re.compile(r"^OptiWin-Setup-(\d+\.\d+\.\d+)\.exe$")
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    installer_name: str
    installer_url: str
    size: int
    sha256: str  # hash esperado (hex en minúsculas)


def parse_version(text: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text.strip())
    if not m:
        raise UpdateError(f"Versión no válida: {text!r}")
    return int(m[1]), int(m[2]), int(m[3])


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "") not in ALLOWED_HOSTS:
        raise UpdateError(f"Dirección no permitida: {url}")


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, timeout: float = 15):
    _check_url(url)
    request = urllib.request.Request(
        url, headers={"User-Agent": f"OptiWin/{__version__}", "Accept": "application/vnd.github+json"}
    )
    return urllib.request.build_opener(_SafeRedirects).open(request, timeout=timeout)


def _fetch_json(url: str) -> dict:
    try:
        with _open(url) as resp:
            return json.loads(resp.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Todavía no hay ninguna release publicada.") from exc
        raise UpdateError(f"GitHub respondió con el error {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("No se pudo conectar con GitHub (¿sin internet?).") from exc


def _fetch_text(url: str) -> str:
    with _open(url) as resp:
        return resp.read(10_000).decode("utf-8", errors="replace")


def release_from_json(data: dict, fetch_text: Callable[[str], str] = _fetch_text) -> ReleaseInfo:
    """Convierte la respuesta de la API en un ReleaseInfo validado (lógica pura, testeable)."""
    tag = str(data.get("tag_name", ""))
    version = ".".join(map(str, parse_version(tag)))
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError("La última release es un borrador o prerelease; se ignora.")

    assets = {a.get("name", ""): a for a in data.get("assets", []) if isinstance(a, dict)}
    name = f"OptiWin-Setup-{version}.exe"
    asset = assets.get(name)
    if asset is None or not INSTALLER_RE.fullmatch(name):
        raise UpdateError(f"La release {tag} no incluye {name}.")
    url = str(asset.get("browser_download_url", ""))
    _check_url(url)

    candidates: set[str] = set()
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        candidates.add(digest.split(":", 1)[1].lower())
    sha_asset = assets.get(name + ".sha256")
    if sha_asset:
        sha_url = str(sha_asset.get("browser_download_url", ""))
        _check_url(sha_url)
        m = _SHA256_RE.search(fetch_text(sha_url))
        if m:
            candidates.add(m[1].lower())
    if not candidates:
        raise UpdateError("La release no publica el hash SHA-256 del instalador; no se descargará.")
    if len(candidates) > 1:
        raise UpdateError("Los hashes publicados no coinciden entre sí; no se descargará.")

    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=str(data.get("body") or "")[:4000],
        installer_name=name,
        installer_url=url,
        size=int(asset.get("size") or 0),
        sha256=candidates.pop(),
    )


def check_for_update(
    current: str = __version__,
    *,
    fetch_json: Callable[[str], dict] = _fetch_json,
    fetch_text: Callable[[str], str] = _fetch_text,
) -> ReleaseInfo | None:
    """Devuelve la release si es MÁS NUEVA que `current`; None si ya estás al día."""
    info = release_from_json(fetch_json(LATEST_URL), fetch_text)
    return info if parse_version(info.version) > parse_version(current) else None


def download_installer(
    info: ReleaseInfo,
    dest_dir: Path,
    progress: Callable[[int, int], None] | None = None,
    *,
    opener: Callable[[str], object] = _open,
) -> Path:
    """Descarga y verifica el instalador. Si el hash no coincide, borra el archivo y falla."""
    if not INSTALLER_RE.fullmatch(info.installer_name):
        raise UpdateError("Nombre de instalador no válido.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / info.installer_name
    part = dest.with_suffix(".part")
    sha = hashlib.sha256()
    done = 0
    try:
        with opener(info.installer_url) as resp, open(part, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, info.size)
        if sha.hexdigest().lower() != info.sha256.lower():
            raise UpdateError("El hash SHA-256 del instalador no coincide. Descarga descartada.")
        part.replace(dest)
        return dest
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Falló la descarga: {exc}") from exc
