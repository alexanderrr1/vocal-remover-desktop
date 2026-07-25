# Construye el runtime Python portable (la "capa pesada" del instalador).
#
# Estrategia: copiar el Python 3.11 completo del sistema (standalone y
# relocalizable) SIN su site-packages global, y trasplantarle las dependencias
# ya instaladas en .venv (mismo 3.11 x64 → binariamente compatible). Así no se
# vuelve a descargar PyTorch y pythonnet/pywebview funcionan como en un Python
# normal (a diferencia del Python "embeddable", donde pythonnet suele fallar).
#
# Requiere: haber corrido install.ps1 antes (para tener .venv poblado).
# Uso:  .\scripts\build_runtime.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$runtime  = Join-Path $root "runtime"
$venvSite = Join-Path $root ".venv\Lib\site-packages"
$basePy   = Split-Path (Get-Command python).Source -Parent

if (-not (Test-Path $venvSite)) { throw "No existe $venvSite. Corré install.ps1 primero." }

if (Test-Path $runtime) { Remove-Item -Recurse -Force $runtime }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

Write-Host "== Copiando Python base (sin site-packages) desde $basePy ==" -ForegroundColor Cyan
robocopy $basePy $runtime /E /XD (Join-Path $basePy "Lib\site-packages") /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy (base) falló con código $LASTEXITCODE" }

Write-Host "== Trasplantando dependencias del venv ==" -ForegroundColor Cyan
$dest = Join-Path $runtime "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
robocopy $venvSite $dest /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy (site-packages) falló con código $LASTEXITCODE" }

$global:LASTEXITCODE = 0

# ── Runtime de Visual C++ (app-local) ───────────────────────────────────────
# c10.dll, el nucleo de PyTorch, depende de msvcp140.dll. Esa DLL viene con el
# "Visual C++ Redistributable", que en la PC de desarrollo esta en System32
# (la instala Visual Studio) pero NO existe en un Windows limpio: sin esto,
# "import torch" muere con WinError 126 y la app no arranca. Verificado en una
# instalacion real sobre Win11 25H2 limpio.
#
# Se copian junto a c10.dll porque PyTorch registra esa carpeta con
# os.add_dll_directory(). Microsoft permite esta distribucion app-local.
#
# NO se usa vc_redist.x64.exe: instala a nivel maquina, pide UAC y romperia el
# PrivilegesRequired=lowest del instalador, del que depende el auto-update.
Write-Host "== Copiando runtime de Visual C++ ==" -ForegroundColor Cyan
# vcomp140 es OpenMP: lo exige torchaudio\lib\libtorchaudio.pyd. Se descubrio
# escaneando la tabla de importaciones de los 203 modulos nativos del paquete,
# despues de que la app fallara en la VM limpia por este unico DLL.
$vcDlls  = @("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
             "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll",
             "vcomp140.dll")
$sys32   = Join-Path $env:WINDIR "System32"
$torchLib = Join-Path $runtime "Lib\site-packages\torch\lib"
$taLib    = Join-Path $runtime "Lib\site-packages\torchaudio\lib"

if (-not (Test-Path $torchLib)) { throw "No existe $torchLib. ¿Se instalo torch en el venv?" }

# Destinos: junto a los .pyd que las necesitan y en la raiz (donde vive
# pythonw.exe, que Windows usa como "application directory").
$destinos = @($torchLib, $runtime)
if (Test-Path $taLib) { $destinos += $taLib }

$faltantes = @()
foreach ($dll in $vcDlls) {
    $src = Join-Path $sys32 $dll
    if (Test-Path $src) {
        foreach ($d in $destinos) { Copy-Item $src -Destination $d -Force }
    } else {
        $faltantes += $dll
    }
}
if ($faltantes.Count -gt 0) {
    throw ("Faltan DLLs de VC++ en {0}: {1}. Instala el Visual C++ Redistributable x64 en esta PC antes de empaquetar." -f $sys32, ($faltantes -join ", "))
}
Write-Host "   $($vcDlls.Count) DLLs copiadas a $($destinos.Count) destinos" -ForegroundColor DarkGray

$mb = [math]::Round((Get-ChildItem $runtime -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 0)
Write-Host "== Runtime listo en $runtime ($mb MB) ==" -ForegroundColor Green
