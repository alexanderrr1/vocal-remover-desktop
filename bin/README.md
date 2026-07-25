# bin/ — binarios externos empaquetados

Esta carpeta contiene los ejecutables que la app usa y que **no** deben asumirse
instalados en la PC del usuario final:

- `ffmpeg.exe` — conversión de audio (WAV ↔ MP3, pitch/tempo)
- `yt-dlp.exe` — descarga del audio de YouTube

## Importante

Estos `.exe` **no se versionan en git** (ffmpeg supera el límite de 100 MB de
GitHub). Se copian aquí en el momento de empaquetar con:

```powershell
.\scripts\prepare_bin.ps1
```

En **desarrollo**, si esta carpeta está vacía, la app cae automáticamente al
`ffmpeg`/`yt-dlp` del PATH del sistema (ver `_resolve_binary` en
`app/processor.py`). Por eso podés trabajar sin poblar `bin/`.

La app resuelve estos binarios en este orden:
1. Variables `FFMPEG_BINARY` / `YTDLP_BINARY` (ruta completa explícita)
2. Esta carpeta `bin/` (vía `VR_BIN_DIR`, que setea `desktop.py`)
3. PATH del sistema
