# Arma el paquete LIVIANO para el auto-update (unos pocos MB).
#
# La arquitectura del proyecto separa dos capas:
#   - runtime pesado (Python + PyTorch + ffmpeg) -> se instala una sola vez
#   - app liviana (codigo + yt-dlp)              -> se auto-actualiza
#
# Este script produce la segunda. Una actualizacion NO debe obligar al usuario
# a bajar de nuevo 242 MB para cambiar unas lineas de Python.
#
# Genera en dist_installer\:
#   VocalRemover-app-<version>.zip
#   VocalRemover-app-<version>.zip.sha256
#
# Ambos se suben al release. El .sha256 permite detectar una descarga
# truncada o corrupta antes de reemplazar archivos de una instalacion que
# hoy funciona.
#
# Uso:  .\scripts\build_app_package.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

$version = (Get-Content (Join-Path $root "version.txt") -Raw).Trim()
if (-not $version) { throw "version.txt esta vacio" }

$outDir = Join-Path $root "dist_installer"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$zip    = Join-Path $outDir "VocalRemover-app-$version.zip"
$sha    = "$zip.sha256"
$stage  = Join-Path $env:TEMP "vr-app-pkg-$version"

if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

Write-Host "== Armando paquete liviano $version ==" -ForegroundColor Cyan

# app/ sin __pycache__: los .pyc de la version vieja en la instalacion del
# usuario podrian ganarle al codigo nuevo si quedaran mezclados.
$appDst = Join-Path $stage "app"
robocopy (Join-Path $root "app") $appDst /E /XD "__pycache__" /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy (app) fallo con codigo $LASTEXITCODE" }
$global:LASTEXITCODE = 0

# yt-dlp cambia seguido (YouTube rompe la descarga cada tanto): es justamente
# de las cosas que uno quiere poder actualizar sin reinstalar todo.
$ytdlp = Join-Path $root "bin\yt-dlp.exe"
if (Test-Path $ytdlp) {
    New-Item -ItemType Directory -Force -Path (Join-Path $stage "bin") | Out-Null
    Copy-Item $ytdlp -Destination (Join-Path $stage "bin") -Force
} else {
    Write-Host "   AVISO: no esta bin\yt-dlp.exe, el paquete va sin el" -ForegroundColor Yellow
}

Copy-Item (Join-Path $root "desktop.py")  -Destination $stage -Force
Copy-Item (Join-Path $root "version.txt") -Destination $stage -Force

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $zip -Leaf)" | Set-Content -Path $sha -Encoding ascii -NoNewline

Remove-Item -Recurse -Force $stage

$mb = [math]::Round((Get-Item $zip).Length / 1MB, 2)
Write-Host ""
Write-Host "Paquete: $zip  ($mb MB)" -ForegroundColor Green
Write-Host "SHA-256: $hash" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Publicalo junto al instalador:" -ForegroundColor Cyan
Write-Host "  gh release create v$version dist_installer\VocalRemover-Setup-$version.exe $zip $sha" -ForegroundColor DarkGray
