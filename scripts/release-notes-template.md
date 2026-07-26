Quita la voz de un video de YouTube y te devuelve la pista instrumental, lista para karaoke. Corre **entero en tu PC**: no sube nada a ningún servidor.

## Instalación

1. Descargá **`VocalRemover-Setup-{{VERSION}}.exe`**, acá abajo en Assets.
2. Ejecutalo. **Windows va a mostrar una advertencia azul de SmartScreen** que dice que protegió tu PC.
3. Hacé clic en **"Más información"** y después en **"Ejecutar de todas formas"**.

Esa advertencia aparece porque el instalador no está firmado con un certificado digital, que cuesta cientos de dólares por año. No significa que el programa sea peligroso: significa que Microsoft no conoce al autor. El código completo está en este repositorio para que puedas verificarlo.

Durante la instalación se descargan unos **640 MB** del modelo de IA, con barra de progreso. Es la única espera y ocurre una sola vez.

No hace falta instalar Python, ffmpeg ni nada más: viene todo adentro. La instalación es por usuario y **no pide permisos de administrador**.

## Si ya tenés la aplicación instalada

No descargues nada: te va a avisar sola dentro de la ventana y se actualiza con un clic, bajando unos 17 MB en vez del instalador completo.

## Requisitos

- Windows 10 u 11, 64 bits
- Unos 3 GB de espacio libre
- Conexión a internet

---

`VocalRemover-app-{{VERSION}}.zip` y su `.sha256` son los artefactos que consume el actualizador automático. No hace falta descargarlos a mano.
