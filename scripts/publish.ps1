# Publica una version completa: version -> paquete -> instalador -> release.
#
# Reemplaza el procedimiento manual de cinco pasos, que ya produjo tres errores
# distintos en un solo dia de trabajo:
#
#   - Se editaron fuentes mientras compilaba el instalador. Inno los lee a
#     medida que comprime, asi que quedo un .exe del que no se podia saber que
#     version del codigo contenia. Hubo que descartarlo y recompilar.
#   - Se publicaron releases incompletos. Sin el .zip las instalaciones
#     existentes no pueden auto-actualizarse; sin el .exe quien entra al
#     repositorio no encuentra que descargar.
#   - Se compilo un instalador que nunca se publico.
#
# De ahi las tres reglas del script: exige el arbol de git limpio, commitea la
# version ANTES de compilar, y verifica contra la API que el release quedo con
# los tres artefactos.
#
# Uso:
#   .\scripts\publish.ps1 -Version 1.0.9
#   .\scripts\publish.ps1 -Version 1.0.9 -DryRun     # muestra que haria
#   .\scripts\publish.ps1 -Version 1.0.9 -NotesFile notas.md

param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$NotesFile,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
Set-Location $root

$REPO = "alexanderrr1/vocal-remover-desktop"
$ISCC = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
$GH   = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\gh.exe"
if (-not (Test-Path $GH)) { $GH = (Get-Command gh -ErrorAction SilentlyContinue).Source }

function Paso($n, $texto) { Write-Host "`n[$n] $texto" -ForegroundColor Cyan }
function Ok($texto)       { Write-Host "    $texto" -ForegroundColor DarkGray }

# ── 1. Validaciones ─────────────────────────────────────────────────────────
Paso 1 "Validaciones previas"

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "La version debe tener el formato X.Y.Z (recibido: '$Version'). Sin la 'v' inicial."
}
if (-not (Test-Path $ISCC)) { throw "No se encuentra ISCC.exe en $ISCC" }
if (-not $GH)               { throw "No se encuentra gh. Instalalo con: winget install GitHub.cli" }

& $GH auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "gh no esta autenticado. Corre: gh auth login" }

# El arbol limpio es lo que evita la carrera entre el compilador y las
# ediciones: si nadie puede tocar los fuentes sin commitear, el instalador
# siempre corresponde a un commit identificable.
$sucio = git status --porcelain
if ($sucio) {
    Write-Host $sucio -ForegroundColor Yellow
    throw "El arbol de git tiene cambios sin commitear. Commitealos o descartalos antes de publicar."
}
Ok "arbol de git limpio"

$tagExiste = git tag -l "v$Version"
if ($tagExiste) { throw "El tag v$Version ya existe localmente." }
& $GH release view "v$Version" --repo $REPO 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { throw "El release v$Version ya existe en GitHub." }
Ok "la version v$Version esta libre"

$actual = (Get-Content (Join-Path $root "version.txt") -Raw).Trim()
Ok "version actual: $actual  ->  nueva: $Version"

if (-not $NotesFile) { $NotesFile = Join-Path $here "release-notes-template.md" }
if (-not (Test-Path $NotesFile)) { throw "No existe el archivo de notas: $NotesFile" }

if ($DryRun) {
    Write-Host "`n== DRY RUN: hasta aca llegan las validaciones, no se toco nada ==" -ForegroundColor Yellow
    Write-Host "   Se publicaria v$Version con las notas de $NotesFile" -ForegroundColor DarkGray
    exit 0
}

# ── 2. Version ──────────────────────────────────────────────────────────────
Paso 2 "Actualizando la version en los dos archivos"

Set-Content -Path (Join-Path $root "version.txt") -Value $Version -Encoding ascii -NoNewline
$iss = Join-Path $root "installer.iss"
(Get-Content $iss -Raw) -replace '#define AppVersion "[^"]*"', "#define AppVersion `"$Version`"" |
    Set-Content -Path $iss -Encoding utf8 -NoNewline
Ok "version.txt e installer.iss actualizados"

# Se commitea ANTES de compilar: el instalador tiene que corresponder a un
# commit concreto, no a un estado intermedio del disco.
git add version.txt installer.iss | Out-Null
git commit -q -m "Version $Version"
git push -q origin main
Ok "commiteado y pusheado"

# ── 3. Artefactos ───────────────────────────────────────────────────────────
Paso 3 "Construyendo el paquete liviano"
& (Join-Path $here "build_app_package.ps1") | Out-Null
$zip = Join-Path $root "dist_installer\VocalRemover-app-$Version.zip"
$sha = "$zip.sha256"
if (-not (Test-Path $zip)) { throw "No se genero $zip" }
Ok "$(Split-Path $zip -Leaf)  ($([math]::Round((Get-Item $zip).Length/1MB,1)) MB)"

Paso 4 "Compilando el instalador (varios minutos)"
& $ISCC $iss | Out-Null
if ($LASTEXITCODE -ne 0) { throw "ISCC fallo con codigo $LASTEXITCODE" }
$exe = Join-Path $root "dist_installer\VocalRemover-Setup-$Version.exe"
if (-not (Test-Path $exe)) { throw "No se genero $exe" }
Ok "$(Split-Path $exe -Leaf)  ($([math]::Round((Get-Item $exe).Length/1MB,1)) MB)"

# ── 4. Release ──────────────────────────────────────────────────────────────
Paso 5 "Publicando el release"

$notas = (Get-Content $NotesFile -Raw) -replace '\{\{VERSION\}\}', $Version
$notasTmp = Join-Path $env:TEMP "vr-notes-$Version.md"
Set-Content -Path $notasTmp -Value $notas -Encoding utf8

& $GH release create "v$Version" $exe $zip $sha `
    --repo $REPO --title "Vocal Remover $Version" --notes-file $notasTmp --latest
if ($LASTEXITCODE -ne 0) { throw "gh release create fallo" }
Remove-Item $notasTmp -Force -ErrorAction SilentlyContinue

# ── 5. Verificacion ─────────────────────────────────────────────────────────
Paso 6 "Verificando que el release quedo completo"

$rel = Invoke-RestMethod "https://api.github.com/repos/$REPO/releases/latest"
if ($rel.tag_name -ne "v$Version") {
    throw "La API devuelve '$($rel.tag_name)' como ultimo release, se esperaba 'v$Version'."
}

$faltan = @()
foreach ($n in @("VocalRemover-Setup-$Version.exe",
                 "VocalRemover-app-$Version.zip",
                 "VocalRemover-app-$Version.zip.sha256")) {
    if ($rel.assets.name -notcontains $n) { $faltan += $n }
}
if ($faltan.Count -gt 0) {
    throw ("El release quedo INCOMPLETO, faltan: {0}. Subilos con 'gh release upload v{1} <archivo>'." -f ($faltan -join ", "), $Version)
}
Ok "los tres artefactos estan publicados"

# Que el asset exista no garantiza que se pueda bajar.
$urlExe = ($rel.assets | Where-Object { $_.name -like "*.exe" }).browser_download_url
$r = Invoke-WebRequest -Uri $urlExe -Method Head -MaximumRedirection 5 -TimeoutSec 60
if ($r.StatusCode -ne 200) { throw "El instalador no se puede descargar (HTTP $($r.StatusCode))." }
Ok "el instalador se descarga (HTTP 200)"

Write-Host "`n== v$Version publicada ==" -ForegroundColor Green
Write-Host "   $($rel.html_url)" -ForegroundColor DarkGray
Write-Host "   La landing y el auto-update la toman solos: no hay que tocar nada mas." -ForegroundColor DarkGray
