import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict

from .job_store import JobStatus

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
DEFAULT_MODEL = os.environ.get("DEMUCS_MODEL", "mdx_extra")
DEMUCS_DEVICE = os.environ.get("DEMUCS_DEVICE", "auto").strip().lower()

# mdx_extra_q (cuantizado) se omite: necesita diffq, que requiere compilador C
# en Windows. mdx_extra ofrece la misma calidad sin esa dependencia.
ALLOWED_MODELS = {"htdemucs", "htdemucs_ft", "mdx_extra"}


def _resolve_binary(name: str, env_var: str) -> str:
    """Ubica un ejecutable externo (ffmpeg, yt-dlp) con esta prioridad:

    1. Variable de entorno explícita (p. ej. FFMPEG_BINARY con ruta completa).
    2. Carpeta `bin/` empaquetada con la app (VR_BIN_DIR, la setea desktop.py).
    3. PATH del sistema (fallback para desarrollo).

    Así el instalador puede traer sus propios binarios sin depender de que el
    usuario tenga ffmpeg/yt-dlp instalados."""
    explicit = os.environ.get(env_var)
    if explicit and Path(explicit).exists():
        return explicit

    bin_dir = os.environ.get("VR_BIN_DIR")
    if bin_dir:
        exe = Path(bin_dir) / (f"{name}.exe" if os.name == "nt" else name)
        if exe.exists():
            return str(exe)

    return name  # fallback: se resuelve vía PATH


FFMPEG = _resolve_binary("ffmpeg", "FFMPEG_BINARY")
YTDLP = _resolve_binary("yt-dlp", "YTDLP_BINARY")

# La app corre bajo pythonw.exe, que no tiene consola. Cuando un proceso sin
# consola lanza un ejecutable de consola (ffmpeg, yt-dlp), Windows le crea una
# ventana negra propia que aparece y desaparece sola en medio del procesamiento.
# CREATE_NO_WINDOW la suprime. En otras plataformas no aplica.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def get_runtime_info() -> Dict[str, Any]:
    requested = DEMUCS_DEVICE if DEMUCS_DEVICE in {"auto", "cpu", "cuda"} else "auto"

    try:
        import torch
    except Exception as exc:
        return {
            "requested_device": requested,
            "selected_device": "cpu",
            "cuda_available": False,
            "gpu_name": None,
            "reason": f"torch no disponible ({exc})",
        }

    cuda_available = bool(torch.cuda.is_available())
    gpu_name = torch.cuda.get_device_name(0) if cuda_available else None

    if requested == "cpu":
        return {
            "requested_device": requested,
            "selected_device": "cpu",
            "cuda_available": cuda_available,
            "gpu_name": gpu_name,
            "reason": "CPU forzada por configuración",
        }

    if requested == "cuda":
        if cuda_available:
            return {
                "requested_device": requested,
                "selected_device": "cuda",
                "cuda_available": True,
                "gpu_name": gpu_name,
                "reason": "GPU NVIDIA disponible",
            }
        return {
            "requested_device": requested,
            "selected_device": "cpu",
            "cuda_available": False,
            "gpu_name": None,
            "reason": "CUDA solicitada pero no disponible; usando CPU",
        }

    if cuda_available:
        return {
            "requested_device": requested,
            "selected_device": "cuda",
            "cuda_available": True,
            "gpu_name": gpu_name,
            "reason": "GPU NVIDIA detectada automáticamente",
        }

    return {
        "requested_device": requested,
        "selected_device": "cpu",
        "cuda_available": False,
        "gpu_name": None,
        "reason": "GPU no disponible; usando CPU",
    }


def _safe_filename(name: str) -> str:
    """Turn a video title into a safe cross-platform filename (no extension)."""
    # Drop characters that are invalid in Windows/Unix filenames or headers
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", name)
    # Collapse whitespace and trim leading/trailing dots and spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    # Keep filenames reasonable
    return cleaned[:150].strip()


def _set(jobs: Dict[str, Any], job_id: str, status: str, progress: int, message: str) -> None:
    """Update job state atomically (CPython dict key assignment is atomic)."""
    jobs[job_id]["status"] = status
    jobs[job_id]["progress"] = progress
    jobs[job_id]["message"] = message


def run_pipeline(job_id: str, url: str, model: str, jobs: Dict[str, Any], semitones: int = 0, tempo: float = 1.0) -> None:
    """
    Full processing pipeline (runs in a ThreadPoolExecutor thread).

    Stages:
      1. yt-dlp   — download best audio from YouTube
      2. ffmpeg   — convert to stereo 44100Hz WAV (Demucs input format)
      3. demucs   — separate vocals / no_vocals with --two-stems vocals + CUDA
      4. ffmpeg   — encode no_vocals.wav → instrumental.mp3 at 320kbps
                    (optional: pitch shift via asetrate+aresample+atempo, tempo via atempo)
    """
    if model not in ALLOWED_MODELS:
        model = DEFAULT_MODEL

    job_dir = WORKSPACE / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    raw_template = str(job_dir / "raw_audio.%(ext)s")
    converted_wav = job_dir / "audio.wav"
    demucs_out_dir = job_dir / "separated"
    output_mp3 = job_dir / "instrumental.mp3"
    runtime = get_runtime_info()
    demucs_device = str(runtime["selected_device"])

    try:
        # ── Stage 1: Download ────────────────────────────────────────────────
        _set(jobs, job_id, JobStatus.DOWNLOADING, 5, "Descargando audio de YouTube...")

        title_file = job_dir / "title.txt"
        dl = subprocess.run(
            [
                YTDLP,
                "--no-playlist",
                "--format", "bestaudio/best",
                "--output", raw_template,
                "--no-progress",
                "--no-warnings",
                # Emit the video title to a file without cancelling the download
                "--no-simulate",
                "--print-to-file", "%(title)s", str(title_file),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=NO_WINDOW,
        )
        if dl.returncode != 0:
            raise RuntimeError(f"yt-dlp falló: {dl.stderr[:600]}")

        downloaded_files = list(job_dir.glob("raw_audio.*"))
        if not downloaded_files:
            raise RuntimeError("yt-dlp terminó pero no se encontró el archivo de salida")
        downloaded = downloaded_files[0]

        # Capture the YouTube title so the download can be named after the video
        try:
            raw_title = title_file.read_text(encoding="utf-8").strip()
        except Exception:
            raw_title = ""
        jobs[job_id]["title"] = _safe_filename(raw_title) or "instrumental"
        title_file.unlink(missing_ok=True)

        # ── Stage 2: Convert to WAV ──────────────────────────────────────────
        _set(jobs, job_id, JobStatus.CONVERTING, 22, "Convirtiendo a WAV...")

        ff_conv = subprocess.run(
            [
                FFMPEG, "-y",
                "-i", str(downloaded),
                "-ac", "2",           # stereo
                "-ar", "44100",       # 44.1 kHz — required by Demucs
                "-sample_fmt", "s16", # 16-bit PCM
                str(converted_wav),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=NO_WINDOW,
        )
        if ff_conv.returncode != 0:
            raise RuntimeError(f"ffmpeg (conversión) falló: {ff_conv.stderr[:400]}")

        downloaded.unlink(missing_ok=True)

        # ── Stage 3: Demucs separation ───────────────────────────────────────
        device_label = "GPU" if demucs_device == "cuda" else "CPU"
        _set(jobs, job_id, JobStatus.SEPARATING, 30, f"Separando voces con IA ({device_label})...")

        demucs_cmd = [
            sys.executable, "-m", "demucs.separate",
            "--two-stems", "vocals",
            "-n", model,
            "--device", demucs_device,
            "-o", str(demucs_out_dir),
            str(converted_wav),
        ]
        if demucs_device == "cuda":
            demucs_cmd += ["--segment", "7"]  # limita VRAM, evita crash del driver GPU

        demucs_proc = subprocess.Popen(
            demucs_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=NO_WINDOW,
        )

        # Parse tqdm progress from stderr to update 30→88%
        progress_thread = threading.Thread(
            target=_watch_demucs_progress,
            args=(demucs_proc, jobs, job_id),
            daemon=True,
        )
        progress_thread.start()
        demucs_proc.wait(timeout=3600)
        progress_thread.join(timeout=5)

        if demucs_proc.returncode != 0:
            # Drain any remaining stderr/stdout so the UI surfaces the real failure.
            try:
                err = demucs_proc.stderr.read()
            except Exception:
                err = ""
            try:
                out = demucs_proc.stdout.read()
            except Exception:
                out = ""

            details = (err or out).strip()
            if not details:
                details = "sin salida de error"
            raise RuntimeError(f"Demucs falló (exit {demucs_proc.returncode}): {details[:1200]}")

        # Locate no_vocals.wav — path: {out}/{model}/audio/no_vocals.wav
        no_vocals = demucs_out_dir / model / "audio" / "no_vocals.wav"
        if not no_vocals.exists():
            matches = list(demucs_out_dir.rglob("no_vocals.wav"))
            if not matches:
                raise RuntimeError("Demucs terminó pero no se encontró no_vocals.wav")
            no_vocals = matches[0]

        # ── Stage 4: Encode to MP3 ───────────────────────────────────────────
        import math
        labels = []
        if semitones != 0:
            labels.append(f"{semitones:+d} st")
        if tempo != 1.0:
            labels.append(f"{tempo:.2f}x")
        extra = f" ({', '.join(labels)})" if labels else ""
        _set(jobs, job_id, JobStatus.ENCODING, 90, f"Codificando MP3 320kbps{extra}...")

        ff_enc_cmd = [FFMPEG, "-y", "-i", str(no_vocals)]
        filters = []
        if semitones != 0:
            pitch_ratio = 2 ** (semitones / 12)
            # asetrate shifts pitch; atempo corrects the tempo back to 1x
            filters += [f"asetrate=44100*{pitch_ratio}", "aresample=44100", f"atempo={1/pitch_ratio}"]
        if tempo != 1.0:
            filters.append(f"atempo={tempo}")
        if filters:
            ff_enc_cmd += ["-af", ",".join(filters)]
        ff_enc_cmd += ["-codec:a", "libmp3lame", "-b:a", "320k", str(output_mp3)]

        ff_enc = subprocess.run(
            ff_enc_cmd,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=NO_WINDOW,
        )
        if ff_enc.returncode != 0:
            raise RuntimeError(f"ffmpeg (MP3) falló: {ff_enc.stderr[:400]}")

        # Clean up intermediate WAVs to free disk space
        converted_wav.unlink(missing_ok=True)
        try:
            no_vocals.unlink(missing_ok=True)
            vocals_wav = no_vocals.parent / "vocals.wav"
            vocals_wav.unlink(missing_ok=True)
        except Exception:
            pass

        jobs[job_id]["output_path"] = str(output_mp3)
        _set(jobs, job_id, JobStatus.DONE, 100, "¡Listo! La pista instrumental está lista.")

    except Exception as exc:
        jobs[job_id]["status"] = JobStatus.FAILED
        jobs[job_id]["error"] = str(exc)
        jobs[job_id]["message"] = f"Error: {exc}"
        raise


def _watch_demucs_progress(proc: subprocess.Popen, jobs: Dict[str, Any], job_id: str) -> None:
    """
    Read Demucs stderr line-by-line and extract tqdm percentage.
    Demucs prints lines like: "  3%|███      | 1/32 [00:14<02:20]"
    We map demucs 0-100% → our display 30-88%.
    """
    pattern = re.compile(r"(\d+)%\|")
    try:
        for line in proc.stderr:
            m = pattern.search(line)
            if m:
                pct = int(m.group(1))
                scaled = 30 + int(pct * 0.58)  # 30% + up to 58pp = 88%
                jobs[job_id]["progress"] = scaled
                jobs[job_id]["message"] = f"Separando voces... {pct}%"
    except Exception:
        pass
