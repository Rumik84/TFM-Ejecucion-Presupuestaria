<#
.SYNOPSIS
    Verifica que el proyecto funciona correctamente tras mover/renombrar la carpeta.

.DESCRIPTION
    Ejecuta una bateria de comprobaciones:
      1. Estructura minima del proyecto.
      2. .venv presente y funcional, con interprete apuntando a la ruta actual.
      3. Carga de config.settings (resolucion dinamica de PROJECT_ROOT).
      4. Conectividad opcional con la API datos.gob.es.
      5. Lectura del catalogo SQLite y de un parquet curado de muestra.

    Cada comprobacion imprime [OK] / [WARN] / [ERROR]. El script termina con
    codigo 0 si no hubo errores criticos, 1 en caso contrario.

.PARAMETER SkipApi
    Omite la prueba de conectividad con datos.gob.es.

.EXAMPLE
    .\scripts\verify_paths.ps1
    .\scripts\verify_paths.ps1 -SkipApi
#>
[CmdletBinding()]
param(
    [switch]$SkipApi
)

$ErrorActionPreference = "Continue"
$global:errors = 0
$global:warnings = 0

function Write-Header($text) {
    Write-Host ""
    Write-Host "---------------------------------------------------------" -ForegroundColor Cyan
    Write-Host " $text" -ForegroundColor Cyan
    Write-Host "---------------------------------------------------------" -ForegroundColor Cyan
}
function Write-Ok($msg)    { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "[WARN]  $msg" -ForegroundColor Yellow; $global:warnings++ }
function Write-Err($msg)   { Write-Host "[ERROR] $msg" -ForegroundColor Red;    $global:errors++ }
function Write-Info($msg)  { Write-Host "[INFO]  $msg" -ForegroundColor White }

$projectRoot = (Get-Location).Path

Write-Host ""
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " Verificacion del proyecto Ejecucion_presupuestaria" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " Cwd: $projectRoot"

# ----- 1. Estructura minima --------------------------------------------------
Write-Header "1. Estructura minima del proyecto"
$required = @(
    "requirements.txt",
    "pyproject.toml",
    "config\settings.py",
    "config\ccaa_catalog.yaml",
    "src\ingestion",
    "src\etl",
    "src\storage",
    "scripts\pilot_validate.py",
    "data_lake"
)
foreach ($p in $required) {
    $full = Join-Path $projectRoot $p
    if (Test-Path $full) {
        Write-Ok $p
    } else {
        Write-Err "Falta: $p"
    }
}

# ----- 2. .venv y python ----------------------------------------------------
Write-Header "2. Entorno virtual .venv"
$venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Err ".venv\Scripts\python.exe no existe. Ejecuta: .\scripts\reset_venv.ps1"
} else {
    Write-Ok "Encontrado: $venvPy"

    try {
        $ver = & $venvPy --version 2>&1
        Write-Ok "Version: $ver"
    } catch {
        Write-Err "No se puede ejecutar el python del venv: $_"
    }

    # Comprobar pyvenv.cfg para detectar venv stale
    $cfg = Join-Path $projectRoot ".venv\pyvenv.cfg"
    if (Test-Path $cfg) {
        $cfgContent = Get-Content $cfg -Raw
        # La linea "command = ... -m venv <ruta>" debe contener la carpeta actual
        $expected = $projectRoot
        if ($cfgContent -match [Regex]::Escape($expected)) {
            Write-Ok "pyvenv.cfg apunta a la ruta actual del proyecto"
        } else {
            Write-Warn "pyvenv.cfg parece de una instalacion anterior. Recomendado: .\scripts\reset_venv.ps1"
        }
    }
}

# ----- 3. Carga de config.settings ------------------------------------------
Write-Header "3. Carga de config.settings (resolucion dinamica de rutas)"
if (Test-Path $venvPy) {
    $script = @"
import sys
sys.path.insert(0, r'$projectRoot')
try:
    from config import settings
    print('PROJECT_ROOT', settings.project_root)
    print('CURATED_DIR', settings.paths.curated_dir)
    print('SQLITE_PATH', settings.paths.sqlite_path)
    print('CCAA_COUNT', len(settings.ccaa))
    print('OK')
except Exception as e:
    print('FAIL', e)
    sys.exit(2)
"@
    $tmp = Join-Path $env:TEMP "verify_settings.py"
    $script | Set-Content -Path $tmp -Encoding UTF8

    $output = & $venvPy $tmp 2>&1
    Remove-Item $tmp -ErrorAction SilentlyContinue

    if ($LASTEXITCODE -eq 0) {
        foreach ($line in $output) { Write-Info $line }
        $rootLine = ($output | Where-Object { $_ -like "PROJECT_ROOT*" }) -join ""
        if ($rootLine -like "*$projectRoot*") {
            Write-Ok "PROJECT_ROOT coincide con la ruta actual."
        } else {
            Write-Warn "PROJECT_ROOT no coincide exactamente con la cwd."
        }
    } else {
        Write-Err "config.settings no se pudo cargar:"
        foreach ($line in $output) { Write-Host "        $line" -ForegroundColor Red }
    }
} else {
    Write-Warn "Se omite la prueba: no hay .venv funcional."
}

# ----- 4. Conectividad con datos.gob.es -------------------------------------
Write-Header "4. Conectividad con datos.gob.es"
if ($SkipApi) {
    Write-Info "Se omite por -SkipApi."
} else {
    $url = "https://datos.gob.es/apidata/catalog/dataset.json?_pageSize=1"
    try {
        $resp = Invoke-WebRequest -Uri $url -Headers @{ "Accept" = "application/json" } -TimeoutSec 15
        if ($resp.StatusCode -eq 200) {
            Write-Ok "API accesible (HTTP 200)"
        } else {
            Write-Warn "Codigo HTTP inesperado: $($resp.StatusCode)"
        }
    } catch {
        Write-Warn "No se puede contactar la API (proxy/red?): $_"
    }
}

# ----- 5. Catalogo SQLite y parquets curados --------------------------------
Write-Header "5. Catalogo SQLite y parquets curados"
$sqlite = Join-Path $projectRoot "data_lake\catalog.db"
if (Test-Path $sqlite) {
    $size = (Get-Item $sqlite).Length / 1MB
    Write-Ok ("catalog.db presente ({0:N1} MB)" -f $size)
} else {
    Write-Warn "catalog.db no encontrado. Ejecuta: python scripts\init_db.py"
}

$curatedDir = Join-Path $projectRoot "data_lake\02_curated"
if (Test-Path $curatedDir) {
    $parquets = Get-ChildItem $curatedDir -Recurse -Filter *.parquet -ErrorAction SilentlyContinue
    if ($parquets.Count -gt 0) {
        Write-Ok ("Parquets curados: {0} ficheros" -f $parquets.Count)
        $byCcaa = $parquets | Group-Object { $_.FullName.Split('\')[-4] }
        foreach ($g in $byCcaa) {
            Write-Info ("  - {0,-22} {1,4} parquet(s)" -f $g.Name, $g.Count)
        }
    } else {
        Write-Warn "No hay parquets en 02_curated. Ejecuta: make etl"
    }
} else {
    Write-Warn "Carpeta 02_curated no encontrada."
}

# ----- 6. Resumen ------------------------------------------------------------
Write-Host ""
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " Resumen" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host (" Errores : {0}" -f $global:errors)   -ForegroundColor (if ($global:errors -gt 0) { "Red" } else { "Green" })
Write-Host (" Warnings: {0}" -f $global:warnings) -ForegroundColor (if ($global:warnings -gt 0) { "Yellow" } else { "Green" })

if ($global:errors -gt 0) {
    Write-Host ""
    Write-Host " VERIFICACION FALLIDA. Revisa los errores anteriores." -ForegroundColor Red
    exit 1
} elseif ($global:warnings -gt 0) {
    Write-Host ""
    Write-Host " Verificacion completada con avisos. Revisa si te afectan." -ForegroundColor Yellow
    exit 0
} else {
    Write-Host ""
    Write-Host " Todo correcto. El proyecto esta listo en la nueva ruta." -ForegroundColor Green
    exit 0
}
