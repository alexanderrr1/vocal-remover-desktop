# Vocal Remover

Quita la voz de un video de YouTube y te devuelve la pista instrumental, lista
para karaoke — y también el tema original, si lo querés. Aplicación de escritorio
para Windows: corre **entera en tu PC** y no sube nada a ningún servidor.

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

Copiá la dirección del video en YouTube y tocá **Pegar link** —el botón que está
al lado del campo—, o pegala a mano ahí mismo. Elegí la calidad y dale
**Procesar**. Cuando termina podés guardar dos archivos:

- **Descargar karaoke** — el tema sin la voz, para cantar encima.
- **Descargar original** — el tema completo, tal como suena.

Cualquiera de los dos abre el "Guardar como" de Windows, y el archivo toma el
nombre del video más el sufijo que corresponda. Bajar el segundo es inmediato:
los dos salen del mismo procesamiento, no hay que volver a esperar.

Podés además cambiar la **tonalidad** hasta 12 semitonos y la **velocidad**
entre 0,5x y 2x, útil para practicar. Los cambios se aplican a los dos
archivos, así que la original te sirve de referencia en la misma tonalidad en
la que vas a cantar.

El procesamiento usa el procesador de tu PC y tarda unos minutos según el largo
del tema y la máquina.

## Si tenés placa de video NVIDIA

La aplicación te lo dice sola: aparece un aviso ofreciéndote activar la
**aceleración por GPU**. Medido en una RTX 3060, el procesamiento pasa de 68 a
18 segundos por cada minuto de audio — casi cuatro veces más rápido.

Se descargan 2,4 GB una sola vez, que ocupan 4,3 GB en disco. Podés desactivarla
cuando quieras y recuperás el espacio. Si tu PC no tiene una placa NVIDIA con
driver, este aviso no aparece y no hay nada que hacer.

## Si un video no se puede descargar

De vez en cuando YouTube pide una **verificación antibot** y la descarga falla.
No es un problema de tu PC ni de la aplicación: pasa cuando YouTube desconfía de
la conexión desde la que se pide el video.

Probá de nuevo en unos minutos, o con otro video. Si estás usando una VPN,
desactivala y reintentá.

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
                                            ┌→ no_vocals → ffmpeg → karaoke.mp3
YouTube URL → yt-dlp → ffmpeg (WAV) → Demucs ┤
                                            └→ el WAV     → ffmpeg → original.mp3
```

Las dos salidas se generan en el mismo trabajo. Separar la voz es lo que tarda
minutos; una vez hecho, codificar además la original cuesta segundos, así que no
tiene sentido hacer elegir de antemano ni procesar dos veces. La original sale
del WAV que entró a Demucs —no del audio descargado— para que las dos pistas
queden alineadas, y comparte la cadena de filtros de tonalidad y velocidad.

Las claves de las salidas (`instrumental`, `original`) y el sufijo del archivo
que ve el usuario viven en `OUTPUT_KINDS`, en `app/job_store.py`: las usan la
interfaz, el endpoint `/download` y el guardado nativo de `desktop.py`.

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

### El botón "Pegar link"

Existe porque en el uso real la gente confundía el campo de la URL con un botón
y se quedaba mirándolo sin escribir nada. Por eso está teñido con el color de
acento y no gris como el campo: si se pareciera al campo no resolvería nada.

Lee el portapapeles por **dos caminos**, en este orden (`pasteLink()` en
`index.html`):

1. `pywebview.api.read_clipboard` → `read_clipboard_text()` en `desktop.py`,
   que llama a Win32 con `ctypes` (`OpenClipboard` / `CF_UNICODETEXT`).
2. `navigator.clipboard.readText()`, para cuando la UI se abre en un navegador
   común durante el desarrollo.

El orden importa: en WebView2 la lectura del portapapeles pasa por el sistema de
permisos del navegador y puede quedar denegada sin aviso, mientras que la vía
Win32 es del proceso y no depende de nadie. Si ninguno de los dos funciona el
botón lo dice ("No se pudo") en vez de quedarse mudo simulando que pegó algo.

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

## Aceleración por GPU (pack opcional)

El instalador trae PyTorch en su variante **CPU** (`install.ps1:21`, índice
`whl/cpu`). Pesa poco y corre en cualquier PC, pero está compilado sin CUDA: en
una máquina con GPU NVIDIA, `torch.cuda.is_available()` igual devuelve `False`.
Traer la variante CUDA para todo el mundo no era opción — la rueda de
`torch 2.1.2+cu121` sola pesa 2,36 GB contra los 242 MB del instalador entero.

Por eso el pack CUDA se baja **a pedido y sólo donde sirve**: `app/gpu.py`
consulta `nvidia-smi` y la UI muestra el banner únicamente si hay una GPU NVIDIA
con driver ≥ 527.41 (el mínimo de CUDA 12.1). En una PC sin GPU la aplicación
no menciona el tema.

### Overlay en vez de reemplazo

Las ruedas se instalan con `pip install --no-deps --target` en
`%LOCALAPPDATA%\VocalRemover\gpu-overlay`, **no** encima del torch existente.
`desktop.py` antepone esa carpeta a `sys.path` al arrancar, antes de que nada
importe torch — una vez que torch está en `sys.modules`, tocar `sys.path` ya no
cambia nada.

La razón es que Windows no deja sobrescribir un DLL cargado, y `torch_cpu.dll`
está en uso apenas la app importa torch. Reemplazarlo exigiría el baile de
stage + reinicio + reemplazo del actualizador, con la app congelada varios
minutos descomprimiendo. Con el overlay no se toca un archivo de la instalación:
activar es anteponer la carpeta, desactivar es dejar de hacerlo, desinstalar es
borrarla. Nada queda a medias.

El precio son los dos torch en disco. Medido: **2,4 GB de descarga que ocupan
4,3 GB descomprimidos** (las ruedas CUDA traen cuDNN y cuBLAS adentro), más los
~250 MB del torch CPU que queda intacto. Antes de empezar se verifica que haya
6 GB libres: quedarse sin disco a mitad de camino desperdicia la descarga entera.

### El sello `.instalado`

Una carpeta con archivos adentro no prueba nada — si la descarga se corta queda
un `gpu-overlay` a medias, con un `torch/` incompleto que rompería el arranque.
El sello se escribe **último**, así que su presencia sí significa "esto está
entero", y `activar_overlay()` no mira otra cosa.

De ahí sale gratis el borrado diferido: cuando el usuario desactiva la GPU se
quita el sello enseguida (eso ya la desactiva), y si los DLL están en uso y
Windows no deja borrar, `limpiar_overlay_incompleto()` lo termina en el próximo
arranque. Carpeta sin sello = borrar, sin importar cómo llegó a ese estado.

## YouTube y el control antibot

YouTube responde a veces con *"Sign in to confirm you're not a bot"*. No es un
fallo de la app: YouTube desafía los pedidos que le parecen automatizados, y la
decisión depende de **la IP y del cliente de su API** que se use, no del video.
Un usuario lo recibió con la 1.0.10.

Tres medidas, ninguna de las cuales lo elimina del todo:

- **Varios clientes por pedido** (`YOUTUBE_CLIENTS` en `processor.py`, hoy
  `android_vr,web_embedded,mweb`). Antes se pedía uno solo: si ese quedaba
  desafiado, no había plan B. Está verificado que un cliente bloqueado deja de
  ser fatal cuando se piden varios — `ios,android_vr` funciona aunque `ios`
  solo falle. Cuesta unos 2 s más de extracción, sobre trabajos de minutos.
- **yt-dlp se actualiza solo** al arrancar, en segundo plano
  (`update_ytdlp_in_background`). YouTube rompe la extracción cada pocas semanas
  y yt-dlp la arregla en días; sin esto, esos arreglos no llegan hasta que
  publiquemos una versión. Funciona sin permisos de administrador porque la
  instalación es por usuario. Se desactiva con `VR_NO_YTDLP_UPDATE=1`.
- **El error se explica en castellano.** El texto de yt-dlp son cuatro líneas
  que terminan en dos URLs de una wiki sobre exportar cookies del navegador: a
  un usuario no técnico no le dice qué hacer y suena a que rompió algo.

Dos detalles que no son evidentes:

`update_ytdlp` **se abstiene si yt-dlp no es la copia empaquetada** (`VR_BIN_DIR`).
Si viene del PATH puede ser una instalación de pipx, winget o scoop, y
actualizarla sería meter mano en algo que no es nuestro.

En Windows no se puede sobrescribir un `.exe` en ejecución, así que `yt-dlp -U`
lo renombra para reemplazarlo. Si eso cayera justo cuando el pipeline lo lanza,
la descarga fallaría por un motivo ajeno al video; el pipeline espera el evento
`_ytdlp_disponible` antes de usarlo.

**No se usan cookies del navegador**, aunque yt-dlp lo sugiera en el propio
error: implica leer los tokens de sesión del usuario y ligar las descargas a su
cuenta de YouTube, con riesgo real de que la marquen.

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
.\scripts\publish.ps1 -Version 1.0.9
.\scripts\publish.ps1 -Version 1.0.9 -DryRun    # solo valida, no toca nada
```

Hace todo: actualiza la versión en `version.txt` e `installer.iss`, commitea y
pushea, construye el paquete liviano y el instalador, publica el release con
los tres artefactos y verifica contra la API que quedó completo y descargable.
Tarda unos 10 minutos, casi todo compilando el instalador.

Antes de tocar nada exige que **el árbol de git esté limpio**, y commitea la
versión **antes** de compilar. No es burocracia: Inno lee los fuentes a medida
que comprime, así que editar algo a mitad de build produce un instalador del
que no se sabe qué versión del código contiene. Ya pasó una vez y hubo que
descartarlo.

Las notas salen de `scripts/release-notes-template.md`, sustituyendo
`{{VERSION}}`. La explicación de SmartScreen es lo primero que lee quien
instala y no debería depender de que alguien la reescriba cada vez.

Un release **tiene que llevar los tres artefactos**: sin el `.zip` las
instalaciones existentes no pueden actualizarse solas, y sin el `.exe` quien
entra a la landing no encuentra qué descargar. Los dos casos fallan en
silencio, porque el release se ve publicado igual. Por eso además del script
hay un workflow (`.github/workflows/verificar-release.yml`) que lo comprueba
desde afuera cada vez que se publica uno, junto con que la landing responda.

**La landing no hay que actualizarla nunca.** No tiene ninguna versión escrita:
resuelve la descarga contra la API en cada visita, y GitHub Pages redespliega
solo al pushear cambios en `docs/`.

## Roadmap

- [x] Fase 1 — App de escritorio (ventana nativa)
- [x] Fase 2 — Empaquetado con instalador (Inno Setup)
- [x] Fase 3 — Auto-update vía GitHub Releases
- [x] Fase 4 — Página de descarga en GitHub Pages

Las Fases 2 y 3 se validaron en una VM con Windows 11 limpio, sin Python ni
ffmpeg. Esa prueba destapó seis defectos que no se manifestaban en la máquina de
desarrollo —DLLs de Visual C++ ausentes, precarga bloqueante, ventanas de
consola, y validación TLS contra un almacén de certificados vacío—, cinco de los
cuales impedían que la aplicación funcionara.

Vale la pena repetirla ante cualquier cambio de empaquetado: la máquina donde se
compila tiene Visual Studio, los pesos cacheados y el almacén de certificados
poblado. La de un usuario, no.
