# Setup del entorno de desarrollo (Windows / PowerShell).
# Crea un venv, instala PyTorch CPU y el resto de dependencias.
#
# Uso:  .\install.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "== Creando entorno virtual (.venv) ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$py = Join-Path $here ".venv\Scripts\python.exe"

Write-Host "== Actualizando pip ==" -ForegroundColor Cyan
& $py -m pip install --upgrade pip

Write-Host "== Instalando PyTorch CPU (puede tardar) ==" -ForegroundColor Cyan
& $py -m pip install "numpy<2" torch==2.1.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cpu

Write-Host "== Instalando el resto de dependencias ==" -ForegroundColor Cyan
& $py -m pip install -r requirements.txt

Write-Host "== Listo. Para correr la app:  .\.venv\Scripts\python.exe desktop.py ==" -ForegroundColor Green
