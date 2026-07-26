# Vocal Remover

Quita la voz de un video de YouTube y te devuelve la pista instrumental, lista
para karaoke. Aplicación de escritorio para Windows: corre **entera en tu PC** y
no sube nada a ningún servidor.

## Descargar

**[⬇ Descargar la última versión](https://github.com/alexanderrr1/vocal-remover-desktop/releases/latest)**

Bajá el archivo `VocalRemover-Setup-<versión>.exe` de la sección **Assets** y
ejecutalo.

### Windows va a mostrarte una advertencia

Al abrir el instalador aparece una pantalla azul que dice que **Windows protegió
tu PC**. Hacé clic en **"Más información"** y después en **"Ejecutar de todas
formas"**.

Aparece porque el instalador no está firmado con un certificado digital, que
cuesta cientos de dólares por año. No significa que el programa sea peligroso:
significa que Microsoft no conoce al autor. Todo el código está en este
repositorio para que puedas verificarlo.

Durante la instalación se descargan unos **640 MB** del modelo de inteligencia
artificial, con barra de progreso. Es la única espera, ocurre una sola vez, y al
terminar la aplicación queda lista.

No necesitás instalar Python, ffmpeg ni nada más: viene todo adentro. Se instala
solo para tu usuario y **no pide permisos de administrador**.

## Cómo se usa

Pegá la URL del video, elegí el modelo y dale **Procesar**. Cuando termina,
**Descargar Instrumental** abre el "Guardar como" de Windows y el archivo toma
el nombre del video.

Podés además cambiar la **tonalidad** hasta 12 semitonos y la **velocidad**
entre 0,5x y 2x, útil para practicar.

El procesamiento usa el procesador de tu PC y tarda unos minutos según el largo
del tema y la máquina.

## Se actualiza sola

Cuando haya una versión nueva, la aplicación te avisa dentro de la ventana y la
instalás con un clic: descarga unos 17 MB en vez de los 242 MB del instalador
completo, y se reinicia sola. Si en ese momento no tenés internet, no pasa nada
ni aparece ningún error.

## Requisitos

- Windows 10 u 11, 64 bits
- Unos 3 GB de espacio libre
- Conexión a internet, para bajar el modelo la primera vez y los videos después

---

# Desarrollo

Todo lo que sigue es para trabajar sobre el proyecto. Si solo querés usar la
aplicación, con lo de arriba alcanza.

Internamente usa el mismo backend FastAPI + Demucs que la versión web
(`../02_Vocal_Remover`), pero sin Docker y sin navegador.

```
YouTube URL → yt-dlp → ffmpeg (WAV) → Demucs → ffmpeg (MP3) → descarga
```

## Requisitos de desarrollo

- **Python 3.11** (x64)
- **ffmpeg** en el PATH (verificá con `ffmpeg -version`)
- Windows 10/11 (WebView2 viene incluido)
- **Inno Setup 6.1+** para compilar el instalador
- **GitHub CLI** (`gh`) autenticado, para publicar releases

## Puesta en marcha

```powershell
.\install.ps1                       # crea el venv e instala todo (CPU)
.\.venv\Scripts\python.exe desktop.py
```

La primera separación descarga los pesos del modelo Demucs (~640 MB) a
`%LOCALAPPDATA%\VocalRemover\models`. Los archivos temporales de cada trabajo
van a `%LOCALAPPDATA%\VocalRemover\workspace`.

## Diferencias con la versión web

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

## Auto-update

Al arrancar, la app consulta el último release de GitHub y compara con
`version.txt`. Si hay una versión nueva lo avisa en la ventana y la aplica con
un clic. Sin conexión no muestra nada: no poder comprobar actualizaciones no es
un problema del usuario.

Lo que se descarga es **solo el paquete liviano** (`app/` + `yt-dlp`, ~17 MB),
no el instalador completo de 242 MB. El runtime pesado y los ~640 MB del modelo
no se vuelven a bajar nunca.

El reemplazo de archivos **no ocurre con la app corriendo**. La descarga se
verifica contra su SHA-256 y queda en
`%LOCALAPPDATA%\VocalRemover\updates\staged`; `desktop.py` la aplica en el
siguiente arranque, antes de importar nada de `app/`, y relanza el proceso. Si
algo falla a mitad de camino, restaura la versión anterior.

`app/` se reemplaza entera —para que un `.py` eliminado no quede suelto y se
importe en lugar del nuevo— y el resto se fusiona archivo por archivo, porque
`bin/ffmpeg.exe` (196 MB) no viaja en el paquete liviano y borrarlo dejaría la
instalación rota.

Endpoints: `GET /update-status`, `POST /check-update`, `POST /download-update`.

Variables útiles para probar sin tocar una instalación real: `VR_VERSION`
(simula la versión instalada), `VR_INSTALL_DIR` (redirige el destino del
reemplazo) y `VR_UPDATE_REPO` (apunta a otro repositorio).

## Publicar una versión

```powershell
# 1. Subir la versión en version.txt e installer.iss (deben coincidir)
# 2. Paquete liviano para el auto-update (segundos)
.\scripts\build_app_package.ps1
# 3. Instalador completo (~9 minutos)
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
# 4. Release con los tres artefactos
gh release create v<versión> `
    dist_installer\VocalRemover-Setup-<versión>.exe `
    dist_installer\VocalRemover-app-<versión>.zip `
    dist_installer\VocalRemover-app-<versión>.zip.sha256 --latest
```

**No edites los fuentes mientras compila el instalador.** Inno lee los archivos
a medida que comprime, así que un cambio a mitad de build produce un instalador
del que no se sabe qué versión del código contiene.

Un release **tiene que llevar los tres artefactos**: sin el `.zip` las
instalaciones existentes no pueden actualizarse solas, y sin el `.exe` quien
entre al repositorio a descargar la app no encuentra instalador.

## Roadmap

- [x] Fase 1 — App de escritorio (ventana nativa)
- [x] Fase 2 — Empaquetado con instalador (Inno Setup)
- [x] Fase 3 — Auto-update vía GitHub Releases
- [ ] Fase 4 — Página de descarga en GitHub Pages

Las Fases 2 y 3 se validaron en una VM con Windows 11 limpio, sin Python ni
ffmpeg. Esa prueba destapó seis defectos que no se manifestaban en la máquina de
desarrollo —DLLs de Visual C++ ausentes, precarga bloqueante, ventanas de
consola, y validación TLS contra un almacén de certificados vacío—, cinco de los
cuales impedían que la aplicación funcionara.

Vale la pena repetirla ante cualquier cambio de empaquetado: la máquina donde se
compila tiene Visual Studio, los pesos cacheados y el almacén de certificados
poblado. La de un usuario, no.
