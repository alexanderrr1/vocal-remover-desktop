from enum import Enum
from pathlib import Path
from typing import Any, Dict, Tuple


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    SEPARATING = "separating"
    ENCODING = "encoding"
    DONE = "done"
    FAILED = "failed"


# Cada trabajo produce dos MP3: la pista sin voz para cantar encima y el tema
# original completo. Separar la voz es lo caro, y una vez hecho devolver también
# la original no cuesta más que un ffmpeg de segundos.
#
# El valor es el sufijo del archivo que descarga el usuario. Estas claves viajan
# tal cual entre la interfaz, el endpoint de descarga y el guardado nativo, así
# que se definen acá una sola vez en vez de repetidas en los tres.
OUTPUT_KINDS: Dict[str, str] = {
    "instrumental": "Karaoke",
    "original": "Original",
}
DEFAULT_KIND = "instrumental"


# In-memory job registry — adequate for single-user local tool.
# Keys: job_id (str UUID)
# Values: dict with keys: status, progress (0-100), message, outputs, title, error
#         donde outputs es {clave de OUTPUT_KINDS: ruta al MP3}
jobs: Dict[str, Any] = {}


def resolve_output(job: Dict[str, Any], kind: str = DEFAULT_KIND) -> Tuple[Path, str]:
    """Ruta y nombre de archivo sugerido para una de las salidas del trabajo.

    Lanza `ValueError` con un mensaje presentable al usuario: quien llama lo
    traduce a un 404 o a un cartel en la ventana, según de dónde venga."""
    if kind not in OUTPUT_KINDS:
        raise ValueError(f"Salida desconocida: {kind!r}. Opciones: {sorted(OUTPUT_KINDS)}")

    ruta = (job.get("outputs") or {}).get(kind)
    if not ruta:
        raise ValueError("Ese archivo no está disponible para este trabajo.")

    path = Path(ruta)
    if not path.exists():
        raise ValueError("No se encontró el archivo de salida.")

    # El nombre lleva sufijo porque ahora se descargan dos archivos del mismo
    # tema y, sin él, el segundo se guardaría como "... (1).mp3".
    title = job.get("title") or "audio"
    return path, f"{title} - {OUTPUT_KINDS[kind]}.mp3"
