# Vocal Remover — Desktop

Versión de escritorio (Windows) del Vocal Remover. Corre localmente en una
ventana nativa; internamente usa el mismo backend FastAPI + Demucs que la
versión web, pero sin Docker y sin navegador.

```
YouTube URL → yt-dlp → ffmpeg (WAV) → Demucs → ffmpeg (MP3) → descarga
```

## Requisitos

- **Python 3.11** (x64)
- **ffmpeg** en el PATH (verificá con `ffmpeg -version`)
- Windows 10/11 (WebView2 viene incluido)

## Puesta en marcha (desarrollo)

```powershell
.\install.ps1                       # crea el venv e instala todo (CPU)
.\.venv\Scripts\python.exe desktop.py
```

La primera separación descarga los pesos del modelo Demucs (~640 MB) a
`%LOCALAPPDATA%\VocalRemover\models`. Los archivos temporales de cada trabajo
van a `%LOCALAPPDATA%\VocalRemover\workspace`.

## Diferencias con la versión web (`../02_Vocal_Remover`)

- `desktop.py` levanta uvicorn en un puerto local privado y abre una ventana
  PyWebView en lugar de exponer el servidor en `0.0.0.0:8000`.
- PyTorch se instala en su variante **CPU** (portable a cualquier PC).
- El código de `app/` es el mismo; las rutas de datos apuntan a
  `%LOCALAPPDATA%\VocalRemover` en vez de a volúmenes de Docker.

## Empaquetado (instalador)

```powershell
.\install.ps1                   # 1. venv con las dependencias
.\scripts\build_runtime.ps1     # 2. runtime portable (~1,5 GB)
.\scripts\prepare_bin.ps1       # 3. copia ffmpeg.exe / yt-dlp.exe a bin\
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

El resultado queda en `dist_installer\VocalRemover-Setup-<versión>.exe` (~242 MB).
Instala por usuario en `%LOCALAPPDATA%\Programs\VocalRemover`, sin UAC, para que
el auto-update de la Fase 3 pueda reemplazar archivos sin permisos de admin.

`build_runtime.ps1` copia además el runtime de Visual C++ (`msvcp140`, `vcomp140`
y compañía) desde `System32` al paquete. Sin eso, PyTorch y torchaudio no cargan
en una PC que no tenga instalado Visual Studio, y la app no arranca.

Los pesos de Demucs (~640 MB) **no van dentro del `.exe`**: el instalador los
descarga durante la instalación, con barra de progreso. Es una tarea desmarcable
—para instalar sin conexión—, se omite si ya están en la caché, y si falla no
aborta la instalación: la app los baja sola en la primera ejecución.

## Roadmap

- [x] Fase 1 — App de escritorio (ventana nativa)
- [x] Fase 2 — Empaquetado con instalador (Inno Setup)
- [ ] Fase 3 — Auto-update vía GitHub Releases
- [ ] Fase 4 — Página de descarga en GitHub Pages

`version.txt` ya se empaqueta con la app, pero todavía no hay código que lo lea:
el chequeo de versión es parte de la Fase 3.
