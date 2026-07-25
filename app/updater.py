"""Chequeo de actualizaciones contra la API de Releases de GitHub.

Compara `version.txt` (empaquetado junto a la app) con el último release
publicado. El repositorio es público, así que la consulta va sin autenticación.

Este módulo **solo consulta y compara**: no descarga ni reemplaza nada. La
descarga del paquete liviano y el aviso en la interfaz viven en otro lado.

Diseño defensivo, por dos motivos aprendidos en la Fase 2:

- **Nunca bloquea el arranque.** Se dispara en un hilo aparte; si GitHub tarda
  o no hay internet, la app funciona igual. Una precarga bloqueante ya nos
  costó que la primera ejecución mostrara una pantalla de error.
- **Nunca propaga excepciones.** Un fallo de red no puede romper la aplicación:
  queda registrado en el estado y la app sigue andando sin actualizarse.
"""
import json
import os
import re
import threading
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Configurable por entorno para poder probar contra otro repo sin tocar código.
REPO = os.environ.get("VR_UPDATE_REPO", "alexanderrr1/vocal-remover-desktop")
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

# Corto a propósito: esto corre al arrancar y nadie debería esperarlo.
TIMEOUT = 8.0

# status: idle | checking | up-to-date | update-available | error
_state: Dict[str, Any] = {
    "status": "idle",
    "current": None,
    "latest": None,
    "asset_name": None,
    "download_url": None,
    "size": None,
    "html_url": None,
    "published_at": None,
    "notes": None,
    "error": None,
}
_lock = threading.Lock()


def _set(**kwargs: Any) -> None:
    with _lock:
        _state.update(kwargs)


def get_state() -> Dict[str, Any]:
    """Copia del estado actual, segura para serializar."""
    with _lock:
        return dict(_state)


# ── Versiones ───────────────────────────────────────────────────────────────

_NUMBERS = re.compile(r"\d+")


def parse_version(raw: str) -> Tuple[int, ...]:
    """'v1.0.3' / '1.0.3' / '1.0.3-beta' -> (1, 0, 3).

    Descarta el prefijo 'v' de los tags de git y cualquier sufijo de
    pre-release, que para comparar no aportan."""
    core = raw.strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = tuple(int(n) for n in _NUMBERS.findall(core))
    return parts or (0,)


def is_newer(latest: str, current: str) -> bool:
    """¿`latest` es posterior a `current`? Compara por componente numérico.

    Rellena con ceros para que '1.1' > '1.0.9' funcione."""
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a > b


def read_local_version() -> Optional[str]:
    """Versión instalada, desde version.txt en la raíz de la app."""
    override = os.environ.get("VR_VERSION")
    if override:
        return override.strip()

    # app/updater.py -> la raíz de la app es el directorio padre
    candidate = Path(__file__).resolve().parent.parent / "version.txt"
    try:
        return candidate.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ── Consulta a GitHub ───────────────────────────────────────────────────────


def _fetch_latest_release() -> Dict[str, Any]:
    # GitHub rechaza pedidos sin User-Agent con 403.
    req = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"VocalRemover/{read_local_version() or 'dev'}",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def _pick_installer(assets: Any) -> Optional[Dict[str, Any]]:
    """El .exe del release. Si hay varios, el primero que termine en .exe."""
    for asset in assets or []:
        name = str(asset.get("name", ""))
        if name.lower().endswith(".exe"):
            return asset
    return None


def check_for_update() -> Dict[str, Any]:
    """Consulta el último release y actualiza el estado. No lanza excepciones."""
    current = read_local_version()
    _set(status="checking", current=current, error=None)

    if not current:
        _set(status="error", error="No se pudo leer la versión local (version.txt).")
        return get_state()

    try:
        release = _fetch_latest_release()
    except Exception as exc:
        # Sin internet, GitHub caído, rate limit, o todavía no hay releases.
        # Nada de esto justifica molestar al usuario: la app anda igual.
        _set(status="error", error=f"{type(exc).__name__}: {exc}")
        print(f"[updater] No se pudo consultar actualizaciones: {exc}")
        return get_state()

    latest = str(release.get("tag_name") or "").strip()
    if not latest:
        _set(status="error", error="El release no trae tag_name.")
        return get_state()

    asset = _pick_installer(release.get("assets"))
    notes = release.get("body") or None
    if notes and len(notes) > 2000:
        notes = notes[:2000] + "…"

    _set(
        latest=latest,
        asset_name=(asset or {}).get("name"),
        download_url=(asset or {}).get("browser_download_url"),
        size=(asset or {}).get("size"),
        html_url=release.get("html_url"),
        published_at=release.get("published_at"),
        notes=notes,
        status="update-available" if is_newer(latest, current) else "up-to-date",
    )

    state = get_state()
    if state["status"] == "update-available":
        print(f"[updater] Hay una versión nueva: {current} -> {latest}")
    else:
        print(f"[updater] Estás en la última versión ({current}).")
    return state


def check_in_background() -> threading.Thread:
    """Dispara el chequeo sin bloquear a quien llama.

    Hilo propio a propósito: el executor de la app tiene un solo worker y lo
    ocupa la carga del modelo, así que el chequeo quedaría encolado detrás de
    una descarga de 640 MB."""
    thread = threading.Thread(target=check_for_update, daemon=True, name="vr-updater")
    thread.start()
    return thread
