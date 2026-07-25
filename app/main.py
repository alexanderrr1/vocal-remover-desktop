import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import updater
from .job_store import JobStatus, jobs
from .processor import ALLOWED_MODELS, DEFAULT_MODEL, get_runtime_info, run_pipeline

# Single-worker executor: prevents two Demucs jobs competing for the same GPU
_executor = ThreadPoolExecutor(max_workers=1)


# Estado de la precarga del modelo, consultable desde la UI vía /model-status.
_model_state: Dict[str, Any] = {"status": "loading", "model": None, "error": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranca el servidor de inmediato y precarga el modelo en segundo plano.

    La precarga NO puede bloquear el arranque: la primera vez descarga ~640 MB
    de pesos, y el usuario se quedaría mirando una ventana con error de conexión
    porque desktop.py deja de esperar a los 60 segundos."""
    loop = asyncio.get_event_loop()
    model = os.environ.get("DEMUCS_MODEL", DEFAULT_MODEL)
    runtime = get_runtime_info()
    device = runtime["selected_device"]
    gpu_name = runtime.get("gpu_name")
    details = f" ({gpu_name})" if gpu_name else ""
    print(f"[startup] Runtime device: {device} - {runtime['reason']}{details}")

    _model_state["model"] = model
    print(f"[startup] Pre-loading model '{model}' en segundo plano...")
    # Sin await a propósito: uvicorn empieza a atender ya mismo.
    loop.run_in_executor(_executor, _warm_model_guarded, model)

    # Chequeo de actualizaciones: hilo propio, no el executor, que está ocupado
    # con la carga del modelo. Falla en silencio si no hay internet.
    updater.check_in_background()

    yield
    _executor.shutdown(wait=False)


def _warm_model_guarded(model_name: str) -> None:
    """Precarga el modelo dejando el resultado en _model_state.

    Corre en el executor de un solo worker, así que un job enviado mientras
    tanto espera su turno detrás de la carga — que es lo correcto, porque sin
    modelo no hay nada que procesar. Atrapa todo: si esto propagara una
    excepción quedaría en un future que nadie observa."""
    try:
        _warm_model(model_name)
    except Exception as exc:
        _model_state["status"] = "error"
        _model_state["error"] = str(exc)
        print(f"[startup] Falló la carga del modelo: {exc}")
        return
    _model_state["status"] = "ready"
    print("[startup] Model ready.")


def _warm_model(model_name: str) -> None:
    """Load Demucs model into GPU VRAM so the first job starts instantly."""
    from demucs.pretrained import get_model
    get_model(model_name)


app = FastAPI(title="Vocal Remover", lifespan=lifespan)

# Serve static files (index.html lives here)
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/runtime")
async def runtime() -> Dict[str, Any]:
    return get_runtime_info()


@app.get("/update-status")
async def update_status() -> Dict[str, Any]:
    """Resultado del chequeo de versión: up-to-date | update-available | error.

    Se consulta una vez al arrancar; este endpoint solo lee el resultado."""
    return updater.get_state()


@app.post("/check-update")
async def check_update() -> Dict[str, Any]:
    """Re-consulta a demanda, para no depender de reiniciar la app."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, updater.check_for_update)


@app.post("/download-update")
async def download_update() -> Dict[str, Any]:
    """Descarga el paquete liviano y lo deja listo para el próximo arranque.

    Devuelve enseguida: el avance se sigue por `progress` en /update-status."""
    updater.download_in_background()
    return updater.get_state()


@app.get("/model-status")
async def model_status() -> Dict[str, Any]:
    """Estado de la precarga: loading | ready | error.

    La UI lo consulta hasta que sale de 'loading' para no dejar procesar sin
    modelo, que se traduciría en un job encolado sin explicación."""
    return dict(_model_state)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(_static_dir / "index.html"))


@app.post("/process")
async def process(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Body: { "youtube_url": "https://...", "model": "htdemucs" }
    Returns: { "job_id": "<uuid>" }
    The job runs asynchronously; track progress via WebSocket /ws/{job_id}.
    """
    url = str(payload.get("youtube_url", "")).strip()
    if not url:
        raise HTTPException(status_code=422, detail="youtube_url es requerido")

    model = str(payload.get("model", DEFAULT_MODEL)).strip()
    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=422, detail=f"Modelo inválido. Opciones: {sorted(ALLOWED_MODELS)}")

    semitones = int(payload.get("semitones", 0))
    if not (-12 <= semitones <= 12):
        raise HTTPException(status_code=422, detail="semitones debe estar entre -12 y 12")

    tempo = float(payload.get("tempo", 1.0))
    if not (0.5 <= tempo <= 2.0):
        raise HTTPException(status_code=422, detail="tempo debe estar entre 0.5 y 2.0")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": JobStatus.QUEUED,
        "progress": 0,
        "message": "En cola...",
        "output_path": None,
        "title": None,
        "error": None,
    }

    asyncio.create_task(_run_job(job_id, url, model, semitones, tempo))
    return {"job_id": job_id}


async def _run_job(job_id: str, url: str, model: str, semitones: int = 0, tempo: float = 1.0) -> None:
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(_executor, run_pipeline, job_id, url, model, jobs, semitones, tempo)
    except Exception:
        # run_pipeline already sets the FAILED state; nothing more to do here
        pass


@app.websocket("/ws/{job_id}")
async def ws_progress(websocket: WebSocket, job_id: str) -> None:
    """Stream job progress as JSON every 500ms until done or failed."""
    await websocket.accept()
    try:
        while True:
            if job_id not in jobs:
                await websocket.send_json({"error": "job_id desconocido"})
                break

            job = jobs[job_id]
            await websocket.send_json({
                "status": job["status"],
                "progress": job["progress"],
                "message": job["message"],
            })

            if job["status"] in (JobStatus.DONE, JobStatus.FAILED):
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


@app.get("/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    """Download the processed instrumental MP3."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    job = jobs[job_id]
    if job["status"] != JobStatus.DONE:
        raise HTTPException(status_code=409, detail="El job no ha terminado aún")

    path = job.get("output_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Archivo de salida no encontrado")

    # Name the download after the YouTube video title (falls back to a default).
    # Starlette encodes non-ASCII filenames correctly (RFC 5987) via the filename param.
    title = job.get("title") or "instrumental"
    filename = f"{title}.mp3"

    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=filename,
    )
