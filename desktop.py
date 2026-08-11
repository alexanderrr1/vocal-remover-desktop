"""
Vocal Remover — Desktop entry point.

Runs the existing FastAPI app on a private localhost port inside a background
thread, then opens a native window (PyWebView / WebView2) pointed at it.

Works both in development (`python desktop.py`) and when frozen into an
executable (PyInstaller / embedded-Python launcher).
"""
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "Vocal Remover"


def base_dir() -> Path:
    """Folder that holds this app's code, in dev and when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """Per-user, writable folder for the workspace and model cache."""
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(root) / "VocalRemover"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Configure the app BEFORE importing it ───────────────────────────────────
# processor.py reads these env vars at import time, so they must be set first.
DATA = data_dir()
(DATA / "workspace").mkdir(parents=True, exist_ok=True)
(DATA / "models").mkdir(parents=True, exist_ok=True)

os.environ.setdefault("WORKSPACE", str(DATA / "workspace"))
os.environ.setdefault("TORCH_HOME", str(DATA / "models"))
os.environ.setdefault("XDG_CACHE_HOME", str(DATA / "models"))
os.environ.setdefault("DEMUCS_DEVICE", "auto")

# Binarios empaquetados (ffmpeg.exe, yt-dlp.exe). processor.py los resuelve
# desde aquí; si la carpeta no existe, cae al PATH del sistema (desarrollo).
os.environ.setdefault("VR_BIN_DIR", str(base_dir() / "bin"))

# Raíces de certificados: en un Windows recién instalado el almacén del sistema
# está casi vacío (las descarga bajo demanda el navegador, y ese mecanismo no
# se dispara desde Python), lo que hace fallar cualquier HTTPS con
# CERTIFICATE_VERIFY_FAILED. certifi viaja en el paquete; apuntando estas
# variables, ssl.load_default_certs() lo suma vía set_default_verify_paths()
# y deja de depender del estado del sistema operativo.
try:
    import certifi as _certifi

    _CA = _certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", _CA)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _CA)
except Exception:
    pass  # sin certifi se sigue con el almacén del sistema

# Bajo pythonw.exe (lanzador sin consola) no hay stdout/stderr y cualquier
# print() crashea. Redirigimos a un log en la carpeta de datos del usuario.
if sys.stdout is None or sys.stderr is None:
    try:
        _log = open(DATA / "vocalremover.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = _log
        sys.stderr = _log
    except Exception:
        pass

# Make sure `app` is importable when frozen (bundled next to the executable).
sys.path.insert(0, str(base_dir()))

# ── Auto-update: aplicar antes de cargar nada de la app ─────────────────────
# Si hay una actualización descargada y verificada, este es el único momento
# seguro para reemplazar archivos: el código todavía no se importó y ningún
# archivo está en uso. Después relanzamos el proceso, porque seguir con los
# módulos viejos en memoria y los nuevos en disco es un estado mixto que da
# fallos imposibles de diagnosticar.
from app.updater import apply_staged_update  # noqa: E402

if os.environ.get("VR_UPDATE_APPLIED") != "1" and apply_staged_update():
    import subprocess

    env = dict(os.environ, VR_UPDATE_APPLIED="1")  # cinturón contra un bucle
    subprocess.Popen(
        [sys.executable, str(base_dir() / "desktop.py")],
        cwd=str(base_dir()),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    sys.exit(0)

# ── Aceleración por GPU ─────────────────────────────────────────────────────
# Si el pack CUDA está instalado, hay que anteponerlo a sys.path ACÁ: apenas se
# importe `app.main` la app carga demucs y con él torch, y una vez que torch
# está en sys.modules cambiar sys.path no sirve de nada.
from app import gpu as _gpu  # noqa: E402

# Antes de activar: barrer un pack a medio bajar o uno que el usuario desactivó
# y no se pudo borrar en caliente. Acá nada está cargado todavía.
_gpu.limpiar_overlay_incompleto()

if _gpu.activar_overlay():
    print(f"[gpu] Pack CUDA activo desde {_gpu.overlay_dir()}")

import uvicorn  # noqa: E402
import webview  # noqa: E402
from app.main import app  # noqa: E402
from app.job_store import DEFAULT_KIND  # noqa: E402

HOST = "127.0.0.1"
PORT = find_free_port()

# Tamaño con el que se crea la ventana. Se ajusta al contenido real al cargar
# (ver fit_to_content). Debe coincidir con lo pasado a create_window para que
# la medición del "chrome" (barra de título + bordes) sea correcta.
INIT_WIDTH = 640
INIT_HEIGHT = 720


def fit_to_content(window) -> None:
    """Ajusta la ventana a la altura real de la card (sin scroll).

    En pantallas chicas, capea al 92% del monitor y deja que aparezca scroll.
    Mide el chrome de la ventana de forma empírica (outer - inner) para no
    depender de constantes por backend."""
    try:
        m = window.evaluate_js(
            "(function(){"
            "var card=document.querySelector('.card')||document.body;"
            "var r=card.getBoundingClientRect();"
            "var cs=getComputedStyle(document.body);"
            "return {"
            " cardW: Math.ceil(r.width),"
            " cardH: Math.ceil(r.height),"
            " padH: Math.ceil(parseFloat(cs.paddingLeft)+parseFloat(cs.paddingRight)),"
            " padV: Math.ceil(parseFloat(cs.paddingTop)+parseFloat(cs.paddingBottom)),"
            " innerW: window.innerWidth,"
            " innerH: window.innerHeight"
            "};})()"
        )
        if not m:
            return

        chrome_w = max(0, INIT_WIDTH - int(m["innerW"]))
        chrome_h = max(0, INIT_HEIGHT - int(m["innerH"]))
        content_w = int(m["cardW"]) + int(m["padH"])
        content_h = int(m["cardH"]) + int(m["padV"])

        try:
            screen = webview.screens[0]
            max_w = int(screen.width * 0.92)
            max_h = int(screen.height * 0.92)
        except Exception:
            max_w = max_h = 10 ** 6

        target_w = min(content_w + chrome_w, max_w)
        target_h = min(content_h + chrome_h, max_h)
        window.resize(int(target_w), int(target_h))
    except Exception:
        pass


def read_clipboard_text() -> str:
    """Texto del portapapeles de Windows, vía Win32 con ctypes.

    No usamos navigator.clipboard porque en WebView2 la lectura del
    portapapeles pasa por el sistema de permisos del navegador y puede quedar
    denegada sin que la app se entere. Esto es del proceso, no del WebView, y
    no pide permiso a nadie.

    OpenClipboard falla si otra aplicación lo tiene tomado en ese instante
    (pasa, y es transitorio), así que se reintenta un puñado de veces."""
    if os.name != "nt":
        raise OSError("solo implementado en Windows")

    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    for intento in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("otra aplicación tiene tomado el portapapeles")

    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""  # hay algo, pero no es texto (una imagen, por ejemplo)
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


class Api:
    """JS API expuesta a la ventana: guardado nativo del resultado.

    WebView2 no dispara descargas HTTP como un navegador, así que en vez de
    navegar a /download usamos el diálogo nativo "Guardar como" y copiamos el
    MP3 ya generado (accesible en este mismo proceso vía el job store).

    Importante: esta clase NO debe guardar la ventana de PyWebView como atributo
    — PyWebView inspecciona recursivamente el objeto js_api y romper al tocar el
    DOM. La ventana se obtiene en el momento con webview.active_window()."""

    def save_result(self, job_id: str, kind: str = DEFAULT_KIND) -> dict:
        """Guarda una de las dos salidas del trabajo: la pista sin voz o la original."""
        from app.job_store import jobs, JobStatus, resolve_output

        job = jobs.get(job_id)
        if not job or job.get("status") != JobStatus.DONE:
            return {"ok": False, "error": "El resultado todavía no está listo."}

        try:
            src, filename = resolve_output(job, kind)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        downloads = Path.home() / "Downloads"
        directory = str(downloads if downloads.exists() else Path.home())

        window = webview.active_window()
        result = window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=directory,
            save_filename=filename,
            file_types=("Audio MP3 (*.mp3)", "Todos los archivos (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}

        dest = result[0] if isinstance(result, (list, tuple)) else result
        try:
            shutil.copy2(src, dest)
        except Exception as exc:  # p. ej. permisos / disco
            return {"ok": False, "error": f"No se pudo guardar: {exc}"}
        return {"ok": True, "path": str(dest)}

    def read_clipboard(self) -> dict:
        """Texto del portapapeles, para el botón "Pegar link"."""
        try:
            return {"ok": True, "text": read_clipboard_text()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def restart_app(self) -> dict:
        """Reinicia la app sin aplicar ninguna actualización.

        Lo usa la activación de la GPU: el pack CUDA ya está en disco, pero
        anteponerlo a sys.path sólo se puede hacer antes de importar torch, o
        sea al arrancar."""
        from app.job_store import jobs, JobStatus

        activos = [
            j for j in jobs.values()
            if j.get("status") not in (JobStatus.DONE, JobStatus.FAILED)
        ]
        if activos:
            return {"ok": False, "error": "Hay un procesamiento en curso. "
                                          "Esperá a que termine y reintentá."}

        import subprocess

        try:
            subprocess.Popen(
                [sys.executable, str(base_dir() / "desktop.py")],
                cwd=str(base_dir()),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except Exception as exc:
            return {"ok": False, "error": f"No se pudo reiniciar: {exc}"}

        webview.active_window().destroy()
        return {"ok": True}

    def restart_for_update(self) -> dict:
        """Relanza la app para que la actualización preparada se aplique.

        El reemplazo de archivos lo hace el proceso nuevo al arrancar, antes de
        importar nada: acá solo lanzamos el reemplazo y cerramos esta ventana."""
        from app.updater import staged_version

        if not staged_version():
            return {"ok": False, "error": "No hay ninguna actualización preparada."}

        from app.job_store import jobs, JobStatus

        activos = [
            j for j in jobs.values()
            if j.get("status") not in (JobStatus.DONE, JobStatus.FAILED)
        ]
        if activos:
            return {"ok": False, "error": "Hay un procesamiento en curso. "
                                          "Esperá a que termine y reintentá."}

        import subprocess

        try:
            subprocess.Popen(
                [sys.executable, str(base_dir() / "desktop.py")],
                cwd=str(base_dir()),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except Exception as exc:
            return {"ok": False, "error": f"No se pudo reiniciar: {exc}"}

        # Cerrar esta ventana termina el proceso viejo y libera los archivos
        # antes de que el nuevo llegue a reemplazarlos.
        webview.active_window().destroy()
        return {"ok": True}


def run_server() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def wait_until_ready(timeout: float = 60.0) -> bool:
    """Poll /health until the server responds or the timeout elapses."""
    deadline = time.time() + timeout
    url = f"http://{HOST}:{PORT}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> None:
    threading.Thread(target=run_server, daemon=True).start()

    if not wait_until_ready():
        # Fall back to opening the window anyway; it will show a load error.
        print("[desktop] Advertencia: el servidor no respondió a tiempo.", file=sys.stderr)

    window = webview.create_window(
        APP_NAME,
        f"http://{HOST}:{PORT}/",
        js_api=Api(),
        width=INIT_WIDTH,
        height=INIT_HEIGHT,
        min_size=(420, 420),
    )
    # Al terminar de cargar, ajustar la ventana al tamaño de la card.
    window.events.loaded += lambda: fit_to_content(window)

    # We run our own uvicorn server; PyWebView just renders it.
    webview.start()


if __name__ == "__main__":
    main()
