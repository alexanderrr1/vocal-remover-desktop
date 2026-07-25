# Genera un acceso directo (VocalRemover.lnk) en la raíz del proyecto que corre
# la app con el runtime portable vía pythonw.exe (sin ventana de consola).
# Sirve para probar la app ensamblada en el lugar, antes de tener el instalador.
#
# Uso:  .\scripts\make_launcher.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

$lnk     = Join-Path $root "VocalRemover.lnk"
$pythonw = Join-Path $root "runtime\pythonw.exe"
$icon    = Join-Path $root "assets\icon.ico"
$entry   = Join-Path $root "desktop.py"

if (-not (Test-Path $pythonw)) { throw "No existe $pythonw. Corré build_runtime.ps1 primero." }

$sh = New-Object -ComObject WScript.Shell
$s  = $sh.CreateShortcut($lnk)
$s.TargetPath       = $pythonw
$s.Arguments        = '"' + $entry + '"'
$s.WorkingDirectory = $root
$s.IconLocation     = $icon
$s.Description       = "Vocal Remover"
$s.Save()

Write-Host "Launcher creado: $lnk" -ForegroundColor Green
Write-Host "Doble clic ahi para probar la app (sin consola)." -ForegroundColor Cyan
