"""Aceleración por GPU: detección del hardware y pack CUDA opcional.

El instalador trae PyTorch en su variante **CPU** (`install.ps1`), que pesa
poco y anda en cualquier PC — pero no puede usar CUDA en ninguna, ni siquiera
con una GPU buena instalada: está compilado sin soporte. Traer la variante CUDA
para todo el mundo significaría un instalador diez veces más grande (la rueda de
torch cu121 sola pesa 2,36 GB contra los 242 MB del instalador completo).

De ahí este módulo: el pack CUDA se descarga **a pedido y solo si hay una GPU
NVIDIA con driver**. Quien no la tiene no ve nada; para esa persona la app es
exactamente la de antes.

Cómo se instala, y por qué así
------------------------------
Las ruedas CUDA van a un directorio aparte (`gpu-overlay`), no encima del torch
que ya está. Es la diferencia entre una operación reversible y uma que no lo es:

* Windows no deja sobrescribir un DLL cargado, y `torch_cpu.dll` está en uso
  apenas la app importa torch. Reemplazarlo exigiría el baile de stage +
  reinicio + reemplazo que ya hace el actualizador, con la app congelada varios
  minutos mientras se descomprimen 2,7 GB.
* Con el overlay no se toca un solo archivo de la instalación. Activar es
  anteponerlo a `sys.path`; desactivar es dejar de hacerlo; desinstalar es
  borrar la carpeta. Nada puede quedar a medias.

El costo es tener los dos torch en disco. Medido: la descarga son 2,4 GB pero
descomprimido el pack ocupa **4,3 GB** (las ruedas CUDA traen adentro cuDNN y
cuBLAS), que se suman a los ~250 MB del torch CPU que queda intacto. Es caro,
pero barato al lado de dejar una instalación irrecuperable si la descarga se
corta a la mitad.
"""
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# Deben coincidir con las versiones de install.ps1: el overlay reemplaza torch
# y torchaudio, pero el resto de las dependencias (numpy, sympy, demucs...) son
# las que ya están instaladas, y demucs espera esta versión de torch.
TORCH_VERSION = "2.1.2"
CUDA_TAG = "cu121"
BASE_URL = f"https://download.pytorch.org/whl/{CUDA_TAG}"

# Las ruedas se bajan acá y recién después se le pasan a pip como archivos
# locales. Dejar que pip resuelva y descargue sería menos código, pero su avance
# no se puede leer: manda el progreso por una barra que se reescribe sobre sí
# misma, y la UI quedaría clavada en el mismo número durante los 2,4 GB. Bajando
# nosotros, la barra muestra bytes reales.
PAQUETES = ("torch", "torchaudio")

# Driver mínimo para CUDA 12.1 en Windows. Por debajo, torch importa pero
# `torch.cuda.is_available()` da False y el usuario se queda sin saber por qué.
MIN_DRIVER = 527.41

# El pico de disco no es el tamaño final: durante la instalación conviven las
# ruedas descargadas (2,4 GB) con el pack ya descomprimido (4,24 GB medidos),
# o sea 6,6 GB antes de que se borren las ruedas. Con margen, 7,5. Se verifica
# ANTES de bajar nada: quedarse sin disco a mitad desperdicia la descarga entera.
ESPACIO_NECESARIO_GB = 7.5


def overlay_dir() -> Path:
    """Carpeta del pack CUDA, dentro de los datos del usuario.

    No va junto al runtime en Archivos de programa: ahí la reinstalación de la
    app lo borraría, y son 2,4 GB para volver a bajar."""
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "VocalRemover" / "gpu-overlay"


def _marker() -> Path:
    """Sello de instalación completa.

    Existe porque una carpeta con archivos no prueba nada: si la descarga se
    corta, `gpu-overlay` queda a medias y con torch adentro. El sello se
    escribe último, así que su presencia sí significa "esto está entero"."""
    return overlay_dir() / ".instalado"


def overlay_listo() -> bool:
    return _marker().exists() and (overlay_dir() / "torch").is_dir()


def activar_overlay() -> bool:
    """Antepone el overlay a sys.path para que gane sobre el torch CPU.

    Hay que llamarla ANTES de importar torch: una vez importado, el módulo
    queda en sys.modules y tocar sys.path no cambia nada."""
    if not overlay_listo():
        return False
    if "torch" in sys.modules:
        return False  # demasiado tarde; el que está cargado es el que queda
    ruta = str(overlay_dir())
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
    return True


# ── Detección del hardware ──────────────────────────────────────────────────

def _nvidia_smi() -> Optional[Dict[str, str]]:
    """Consulta nvidia-smi: nombre de la GPU y versión del driver.

    Es la prueba que importa. Que Windows liste un adaptador NVIDIA no alcanza
    —puede estar sin driver, o ser una placa vieja sin CUDA—; que nvidia-smi
    conteste significa que hay un driver NVIDIA funcionando."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None

    primera = proc.stdout.strip().splitlines()[0]
    partes = [p.strip() for p in primera.split(",")]
    if len(partes) < 2:
        return None
    return {"nombre": partes[0], "driver": partes[1]}


def _driver_suficiente(driver: str) -> bool:
    m = re.match(r"(\d+)\.(\d+)", driver or "")
    if not m:
        return True  # formato inesperado: no bloquear por no poder parsear
    return float(f"{m.group(1)}.{m.group(2)}") >= MIN_DRIVER


_hardware_cache: Optional[Dict[str, Any]] = None


def detectar_gpu() -> Dict[str, Any]:
    """Qué GPU hay y si tiene sentido ofrecer el pack CUDA.

    El resultado se cachea: nadie cambia de placa de video con la aplicación
    abierta, y la UI consulta el estado cada segundo y medio mientras baja el
    pack — lanzar nvidia-smi en cada una es gasto puro."""
    global _hardware_cache
    if _hardware_cache is not None:
        return _hardware_cache
    _hardware_cache = _detectar_gpu()
    return _hardware_cache


def _detectar_gpu() -> Dict[str, Any]:
    smi = _nvidia_smi()
    if not smi:
        return {"disponible": False, "nombre": None, "driver": None,
                "motivo": "No se detectó una GPU NVIDIA con driver instalado."}

    if not _driver_suficiente(smi["driver"]):
        return {"disponible": False, "nombre": smi["nombre"], "driver": smi["driver"],
                "motivo": f"El driver {smi['driver']} es anterior al {MIN_DRIVER} "
                          f"que necesita CUDA 12.1. Actualizalo y reintentá."}

    return {"disponible": True, "nombre": smi["nombre"], "driver": smi["driver"],
            "motivo": "GPU NVIDIA compatible detectada."}


# ── Instalación del pack ────────────────────────────────────────────────────

_estado: Dict[str, Any] = {"status": "idle", "progress": 0, "error": None}
_lock = threading.Lock()


def get_state() -> Dict[str, Any]:
    estado = dict(_estado)
    estado["instalado"] = overlay_listo()
    return estado


def _pip_ejecutable() -> list:
    """Cómo invocar pip.

    La app corre bajo `pythonw.exe` (sin consola). pip anda igual, pero se
    prefiere el `python.exe` de al lado cuando existe: es el intérprete que pip
    espera y evita rarezas con los flujos estándar."""
    exe = Path(sys.executable)
    consola = exe.with_name("python.exe")
    interprete = str(consola) if consola.exists() else sys.executable
    return [interprete, "-m", "pip"]


def espacio_libre_gb() -> float:
    import shutil as _sh

    destino = overlay_dir()
    # El disco es el de la carpeta padre: la del overlay puede no existir aún.
    referencia = destino if destino.exists() else destino.parent
    try:
        return _sh.disk_usage(str(referencia)).free / (1024 ** 3)
    except Exception:
        return float("inf")  # sin poder medir, no bloquear


def _nombre_rueda(paquete: str) -> str:
    """Nombre exacto del archivo en el índice de PyTorch.

    El tag `cp311` no se escribe a mano: se arma con la versión del intérprete
    que está corriendo. Si algún día el runtime pasa a otro Python, esto falla
    con un 404 claro en vez de instalar una rueda incompatible."""
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    return f"{paquete}-{TORCH_VERSION}+{CUDA_TAG}-{py}-{py}-win_amd64.whl"


def _descargar_ruedas(destino: Path) -> list:
    """Baja las ruedas informando avance real en bytes.

    El progreso se reparte 0–85% entre los dos archivos ponderado por tamaño,
    así la barra avanza parejo: torch pesa 2,36 GB y torchaudio 4 MB, y repartir
    por cantidad de archivos daría un salto del 42% al final."""
    import urllib.request

    destino.mkdir(parents=True, exist_ok=True)
    urls = [f"{BASE_URL}/{_nombre_rueda(p).replace('+', '%2B')}" for p in PAQUETES]

    # Un HEAD por archivo para saber el total antes de empezar.
    tamanos = []
    for url in urls:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as resp:
            tamanos.append(int(resp.headers.get("Content-Length") or 0))
    total = sum(tamanos) or 1

    archivos = []
    bajado_previo = 0
    for url, esperado in zip(urls, tamanos):
        salida = destino / url.rsplit("/", 1)[-1].replace("%2B", "+")
        with urllib.request.urlopen(url, timeout=120) as resp, open(salida, "wb") as f:
            bajado = 0
            while True:
                trozo = resp.read(1024 * 256)
                if not trozo:
                    break
                f.write(trozo)
                bajado += len(trozo)
                with _lock:
                    _estado["progress"] = int((bajado_previo + bajado) / total * 85)

        if esperado and salida.stat().st_size != esperado:
            raise RuntimeError(
                f"La descarga de {salida.name} quedó incompleta "
                f"({salida.stat().st_size} de {esperado} bytes)."
            )
        bajado_previo += bajado
        archivos.append(salida)

    return archivos


def _instalar() -> None:
    destino = overlay_dir()
    try:
        libre = espacio_libre_gb()
        if libre < ESPACIO_NECESARIO_GB:
            raise RuntimeError(
                f"Hacen falta unos {ESPACIO_NECESARIO_GB:.0f} GB libres y hay "
                f"{libre:.1f} GB. Liberá espacio y reintentá."
            )
        destino.mkdir(parents=True, exist_ok=True)
        # Si quedó basura de un intento cortado, el sello no está y esto la pisa.
        if _marker().exists():
            _marker().unlink()

        with _lock:
            _estado.update(status="downloading", progress=0, error=None)

        ruedas = _descargar_ruedas(destino / "_ruedas")

        with _lock:
            _estado.update(status="installing", progress=85)

        cmd = _pip_ejecutable() + [
            "install", "--no-deps", "--upgrade",
            "--target", str(destino),
        ] + [str(r) for r in ruedas]

        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
        )
        if proc.returncode != 0:
            salida = ((proc.stdout or "") + (proc.stderr or "")).strip()
            raise RuntimeError(f"pip falló ({proc.returncode}): {salida[-500:]}")

        # Las ruedas ya cumplieron: son 2,4 GB que no hacen falta más.
        import shutil as _sh
        _sh.rmtree(destino / "_ruedas", ignore_errors=True)
        if not (destino / "torch").is_dir():
            raise RuntimeError("la descarga terminó pero no quedó torch en el pack")

        _marker().write_text(f"{TORCH_VERSION}+{CUDA_TAG}\n", encoding="utf-8")
        with _lock:
            _estado.update(status="done", progress=100, error=None)
        print(f"[gpu] Pack CUDA instalado en {destino}")
    except Exception as exc:
        with _lock:
            _estado.update(status="error", progress=0, error=str(exc))
        print(f"[gpu] Falló la instalación del pack: {exc}")


def instalar_en_segundo_plano() -> Dict[str, Any]:
    with _lock:
        if _estado["status"] in ("downloading", "installing"):
            return get_state()
        _estado.update(status="downloading", progress=0, error=None)
    threading.Thread(target=_instalar, daemon=True, name="vr-gpu-pack").start()
    return get_state()


def limpiar_overlay_incompleto() -> bool:
    """Borra el overlay si está sin sellar. Se llama al arrancar.

    Una carpeta sin el sello significa una de dos cosas, y las dos se resuelven
    igual: o la descarga se cortó a la mitad, o el usuario desactivó la GPU y no
    se pudo borrar en el momento porque los DLL estaban cargados. Acá, antes de
    importar torch, no hay nada en uso y el borrado sí funciona."""
    import shutil

    destino = overlay_dir()
    if not destino.exists() or _marker().exists():
        return False
    try:
        shutil.rmtree(destino)
        print(f"[gpu] Se borró un pack CUDA incompleto o desactivado en {destino}")
        return True
    except Exception as exc:
        print(f"[gpu] No se pudo borrar {destino}: {exc}")
        return False


def desinstalar() -> Dict[str, Any]:
    """Desactiva el pack y libera el disco.

    Quitar el sello es lo que realmente desactiva: a partir de ahí ningún
    arranque va a anteponer el overlay. El borrado se intenta enseguida, pero si
    torch está cargado desde ahí los DLL están en uso y Windows no deja; en ese
    caso lo termina `limpiar_overlay_incompleto()` en el próximo arranque, que es
    justo cuando nadie los tiene abiertos."""
    import shutil

    destino = overlay_dir()
    try:
        if _marker().exists():
            _marker().unlink()

        borrado = True
        try:
            if destino.exists():
                shutil.rmtree(destino)
        except Exception:
            borrado = False  # en uso: queda para el próximo arranque

        with _lock:
            _estado.update(status="idle", progress=0, error=None)
        estado = get_state()
        estado["reinicio_pendiente"] = not borrado
        return estado
    except Exception as exc:
        with _lock:
            _estado.update(status="error", error=f"No se pudo desactivar: {exc}")
        return get_state()
