# Copia ffmpeg.exe y yt-dlp.exe a bin/ para empaquetar la app.
# Los toma del PATH del sistema (donde ya los tengas instalados).
#
# Uso:  .\scripts\prepare_bin.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$bin  = Join-Path $root "bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null

function Copy-Tool($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Warning "No se encontró '$name' en el PATH. Instalalo o copialo a bin\ a mano."
        return
    }
    $dest = Join-Path $bin ("{0}.exe" -f $name)
    Copy-Item $cmd.Source $dest -Force
    $mb = [math]::Round((Get-Item $dest).Length / 1MB, 1)
    Write-Host "Copiado $name -> bin\$name.exe ($mb MB)" -ForegroundColor Green
}

Write-Host "== Poblando bin\ ==" -ForegroundColor Cyan
Copy-Tool ffmpeg
Copy-Tool yt-dlp
Write-Host "== Listo ==" -ForegroundColor Cyan
