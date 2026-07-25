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
import hashlib
import json
import os
import re
import shutil
import ssl
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Configurable por entorno para poder probar contra otro repo sin tocar código.
REPO = os.environ.get("VR_UPDATE_REPO", "alexanderrr1/vocal-remover-desktop")
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

# Corto a propósito: esto corre al arrancar y nadie debería esperarlo.
TIMEOUT = 8.0

# status:  idle | checking | up-to-date | update-available
#          downloading | staged | error
#
# "staged" = descargado y verificado, listo para aplicarse en el próximo
# arranque. Nunca se reemplazan archivos con la app corriendo.
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
    # Paquete liviano (app/ + yt-dlp), lo que realmente se descarga
    "package_url": None,
    "package_name": None,
    "package_size": None,
    "sha256_url": None,
    "progress": 0,
}
_lock = threading.Lock()


# ── Rutas de trabajo ────────────────────────────────────────────────────────


def install_dir() -> Path:
    """Raíz de la instalación: donde viven desktop.py, app/ y bin/.

    `VR_INSTALL_DIR` permite apuntarla a otro lado para poder probar el
    reemplazo de archivos sin tocar una instalación real."""
    override = os.environ.get("VR_INSTALL_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "VocalRemover"


def updates_dir() -> Path:
    d = _data_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


STAGED_MARKER = ".ready"


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


def _ssl_context() -> Optional[ssl.SSLContext]:
    """Contexto TLS con las raíces de certifi, que viajan en el paquete.

    En Windows, Python valida contra el almacén de certificados del sistema.
    En una instalación recién hecha ese almacén está casi vacío: Windows
    descarga las raíces bajo demanda cuando el navegador las necesita, y ese
    mecanismo no se dispara desde Python. Resultado: CERTIFICATE_VERIFY_FAILED
    contra api.github.com en una PC nueva, mientras que en la máquina de
    desarrollo funciona porque ahí el almacén ya está poblado.

    Usar el bundle de certifi hace que la validación no dependa del estado del
    sistema operativo. Si por algún motivo no estuviera, se cae al
    comportamiento por defecto en vez de romper."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception as exc:
        print(f"[updater] Sin certifi, se usa el almacén del sistema ({exc}).")
        return None


def _fetch_latest_release() -> Dict[str, Any]:
    # GitHub rechaza pedidos sin User-Agent con 403.
    req = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"VocalRemover/{read_local_version() or 'dev'}",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as resp:
        return json.load(resp)


def _pick_installer(assets: Any) -> Optional[Dict[str, Any]]:
    """El .exe del release. Si hay varios, el primero que termine en .exe."""
    for asset in assets or []:
        name = str(asset.get("name", ""))
        if name.lower().endswith(".exe"):
            return asset
    return None


def _pick_package(assets: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """El zip liviano y su .sha256, por nombre (`VocalRemover-app-*.zip`).

    Puede no existir: los releases viejos traen solo el instalador. En ese caso
    no hay actualización incremental posible y hay que reinstalar a mano."""
    pkg = sha = None
    for asset in assets or []:
        name = str(asset.get("name", "")).lower()
        if name.startswith("vocalremover-app-"):
            if name.endswith(".zip"):
                pkg = asset
            elif name.endswith(".zip.sha256"):
                sha = asset
    return pkg, sha


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
    pkg, sha = _pick_package(release.get("assets"))
    notes = release.get("body") or None
    if notes and len(notes) > 2000:
        notes = notes[:2000] + "…"

    _set(
        latest=latest,
        asset_name=(asset or {}).get("name"),
        download_url=(asset or {}).get("browser_download_url"),
        size=(asset or {}).get("size"),
        package_name=(pkg or {}).get("name"),
        package_url=(pkg or {}).get("browser_download_url"),
        package_size=(pkg or {}).get("size"),
        sha256_url=(sha or {}).get("browser_download_url"),
        html_url=release.get("html_url"),
        published_at=release.get("published_at"),
        notes=notes,
        progress=0,
        status="update-available" if is_newer(latest, current) else "up-to-date",
    )

    state = get_state()
    if state["status"] == "update-available":
        print(f"[updater] Hay una versión nueva: {current} -> {latest}")
    else:
        print(f"[updater] Estás en la última versión ({current}).")
    return state


# ── Descarga y preparación ──────────────────────────────────────────────────


def _download(url: str, dest: Path, on_progress=None) -> None:
    """Descarga a un archivo temporal y recién al final lo mueve a `dest`.

    Así una descarga cortada nunca deja un archivo con nombre definitivo pero
    contenido incompleto."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "VocalRemover"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp, \
            open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if on_progress and total:
                on_progress(int(done * 100 / total))
    tmp.replace(dest)


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _read_expected_hash(path: Path) -> Optional[str]:
    """Primer token del archivo .sha256, solo si es un SHA-256 hexadecimal.

    Se lee en binario y con `errors='replace'` a propósito: si en vez del hash
    llegó una página de error o un binario, queremos un mensaje claro y no un
    UnicodeDecodeError a mitad de una actualización."""
    try:
        texto = path.read_bytes().decode("utf-8", errors="replace").strip()
    except OSError:
        return None
    if not texto:
        return None
    candidato = texto.split()[0].strip().lower()
    return candidato if _HEX64.match(candidato) else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_update() -> Dict[str, Any]:
    """Descarga el paquete liviano, lo verifica y lo deja listo para aplicar.

    No toca la instalación: extrae a una carpeta aparte y escribe un marcador.
    El reemplazo real ocurre en el próximo arranque, con el código todavía sin
    importar — reemplazar archivos de una app en ejecución es pedir problemas.
    """
    state = get_state()

    if state["status"] not in ("update-available", "error", "staged"):
        return _fail("No hay ninguna actualización pendiente de descargar.")
    if not state.get("package_url"):
        return _fail(
            "El release no publica el paquete liviano; hay que actualizar "
            "reinstalando desde la página de descargas."
        )

    version = state["latest"]
    work = updates_dir()
    staged = work / "staged"
    zip_path = work / str(state["package_name"] or "update.zip")

    _set(status="downloading", progress=0, error=None)
    try:
        _download(state["package_url"], zip_path,
                  on_progress=lambda p: _set(progress=p))

        # Verificación de integridad antes de tocar nada. Reemplazar archivos
        # de una instalación que hoy funciona con un zip corrupto es el peor
        # resultado posible de un auto-update.
        if state.get("sha256_url"):
            sha_file = work / "package.sha256"
            _download(state["sha256_url"], sha_file)
            expected = _read_expected_hash(sha_file)
            if expected is None:
                zip_path.unlink(missing_ok=True)
                return _fail("El archivo de verificación no tiene el formato esperado "
                             "(un SHA-256 en hexadecimal). No se aplica la actualización.")
            actual = _sha256(zip_path)
            if actual != expected:
                zip_path.unlink(missing_ok=True)
                return _fail(f"El paquete descargado no coincide con su SHA-256 "
                             f"(esperado {expected[:12]}…, obtenido {actual[:12]}…).")
        else:
            print("[updater] El release no publica .sha256; se omite la verificación.")

        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad:
                return _fail(f"El zip está corrupto (entrada dañada: {bad}).")
            _safe_extract(zf, staged)

        if not (staged / "app").is_dir():
            return _fail("El paquete no contiene la carpeta 'app'.")

        (staged / STAGED_MARKER).write_text(str(version), encoding="utf-8")
        zip_path.unlink(missing_ok=True)

        _set(status="staged", progress=100)
        print(f"[updater] Actualización {version} lista; se aplica al reiniciar.")
    except Exception as exc:
        return _fail(f"{type(exc).__name__}: {exc}")

    return get_state()


def _fail(message: str) -> Dict[str, Any]:
    _set(status="error", error=message)
    print(f"[updater] {message}")
    return get_state()


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extrae rechazando rutas que se escapen del destino.

    Un zip puede traer entradas tipo '../../evil.py'. Acá el contenido viene de
    un release propio, pero un extract sin validar sobre una carpeta de
    instalación es una primitiva de escritura arbitraria y no cuesta nada
    cerrarla."""
    root = dest.resolve()
    for member in zf.infolist():
        target = (root / member.filename).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Entrada con ruta insegura en el zip: {member.filename}")
    zf.extractall(dest)


# ── Aplicación de la actualización (al arrancar) ────────────────────────────


def staged_version() -> Optional[str]:
    """Versión preparada esperando aplicarse, si la hay."""
    marker = updates_dir() / "staged" / STAGED_MARKER
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# Directorios que se reemplazan ENTEROS. Son código propio: un .py de la
# versión anterior que quedara suelto podría importarse en lugar del nuevo.
#
# Todo lo demás se fusiona archivo por archivo. `bin/` es el caso que obliga a
# esta distinción: contiene ffmpeg.exe (196 MB) que NO viaja en el paquete
# liviano, así que reemplazar la carpeta entera lo borraría y dejaría la
# instalación sin poder convertir audio.
REPLACE_WHOLE = {"app"}


def apply_staged_update() -> bool:
    """Reemplaza los archivos de la instalación con los preparados.

    Pensada para llamarse al arrancar, ANTES de importar el código de la app.
    Devuelve True si aplicó algo, en cuyo caso conviene relanzar el proceso
    para no quedar con módulos viejos en memoria y archivos nuevos en disco.

    Ante cualquier error, restaura lo anterior: es preferible seguir en la
    versión vieja que dejar la instalación a medio actualizar.
    """
    work = updates_dir()
    staged = work / "staged"
    version = staged_version()
    if not version:
        return False

    target = install_dir()
    backup = work / "backup"
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)

    # (ruta relativa, si existía antes) en orden de aplicación, para poder
    # deshacer exactamente lo que se hizo.
    hechos: list = []

    def reemplazar(src: Path, rel: Path) -> None:
        dst = target / rel
        existia = dst.exists()
        if existia:
            destino_backup = backup / rel
            destino_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(destino_backup))
        hechos.append((rel, existia))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    try:
        for src in staged.iterdir():
            if src.name == STAGED_MARKER:
                continue
            if src.is_dir() and src.name not in REPLACE_WHOLE:
                # Fusión: solo se tocan los archivos que el paquete trae.
                for archivo in sorted(p for p in src.rglob("*") if p.is_file()):
                    reemplazar(archivo, archivo.relative_to(staged))
            else:
                reemplazar(src, Path(src.name))

        shutil.rmtree(staged, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        print(f"[updater] Actualizado a {version}.")
        return True

    except Exception as exc:
        print(f"[updater] Falló la actualización ({exc}); restaurando la versión anterior.")
        for rel, existia in reversed(hechos):
            dst = target / rel
            try:
                if dst.exists():
                    shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
                if existia:
                    shutil.move(str(backup / rel), str(dst))
            except Exception as rollback_exc:
                print(f"[updater] ERROR restaurando {rel}: {rollback_exc}")
        # El marcador se borra igual: reintentar en cada arranque un paquete
        # que ya falló sería un bucle.
        shutil.rmtree(staged, ignore_errors=True)
        return False


def download_in_background() -> threading.Thread:
    thread = threading.Thread(target=download_update, daemon=True, name="vr-update-dl")
    thread.start()
    return thread


def check_in_background() -> threading.Thread:
    """Dispara el chequeo sin bloquear a quien llama.

    Hilo propio a propósito: el executor de la app tiene un solo worker y lo
    ocupa la carga del modelo, así que el chequeo quedaría encolado detrás de
    una descarga de 640 MB."""
    thread = threading.Thread(target=check_for_update, daemon=True, name="vr-updater")
    thread.start()
    return thread
