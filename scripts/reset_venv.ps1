<#
.SYNOPSIS
    Recrea el entorno virtual .venv del proyecto e instala las dependencias.

.DESCRIPTION
    Útil tras mover/renombrar la carpeta del proyecto: el .venv original guarda
    rutas absolutas en sus shebangs y deja de funcionar. Este script lo borra,
    crea uno nuevo con el Python del sistema e instala requirements.txt.

    Debe ejecutarse desde la raíz del proyecto (donde está requirements.txt).

.PARAMETER Python
    Ruta o nombre del intérprete de Python a usar. Por defecto "python".

.PARAMETER NoInstall
    No ejecuta pip install (solo crea el .venv vacío).

.EXAMPLE
    .\scripts\reset_venv.ps1
    .\scripts\reset_venv.ps1 -Python "C:\Python313\python.exe"
    .\scripts\reset_venv.ps1 -NoInstall
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

# ----- 1. Validar que estamos en la raíz del proyecto ------------------------
$projectRoot = (Get-Location).Path
$reqFile = Join-Path $projectRoot "requirements.txt"
if (-not (Test-Path $reqFile)) {
    Write-Host "[ERROR] No se encontro requirements.txt en $projectRoot" -ForegroundColor Red
    Write-Host "        Ejecuta este script desde la raiz del proyecto." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " Reset del entorno virtual del proyecto" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " Proyecto : $projectRoot"
Write-Host " Python   : $Python"
Write-Host ""

# ----- 2. Verificar Python disponible ---------------------------------------
try {
    $pyVersion = & $Python --version 2>&1
    Write-Host "[OK]   Interprete detectado: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] No se puede ejecutar '$Python'. Instala Python o pasa -Python con la ruta completa." -ForegroundColor Red
    exit 1
}

# ----- 3. Borrar .venv existente --------------------------------------------
$venvPath = Join-Path $projectRoot ".venv"
if (Test-Path $venvPath) {
    Write-Host "[INFO] Borrando .venv existente..." -ForegroundColor Yellow
    try {
        Remove-Item -Recurse -Force $venvPath
        Write-Host "[OK]   .venv borrado." -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] No se pudo borrar .venv: $_" -ForegroundColor Red
        Write-Host "        Cierra cualquier terminal o IDE que tenga el venv activo y reintenta." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[INFO] No habia .venv previo; se creara uno nuevo." -ForegroundColor Yellow
}

# ----- 4. Crear nuevo .venv -------------------------------------------------
Write-Host ""
Write-Host "[INFO] Creando .venv con $Python -m venv .venv ..." -ForegroundColor Yellow
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] python -m venv fallo (codigo $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "[OK]   .venv creado." -ForegroundColor Green

# ----- 5. Verificar que el nuevo python apunta a la nueva ruta --------------
$newPy = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $newPy)) {
    Write-Host "[ERROR] No se encontro $newPy tras crear el venv." -ForegroundColor Red
    exit 1
}
Write-Host "[OK]   Nuevo interprete: $newPy" -ForegroundColor Green

# ----- 6. Actualizar pip y dependencias --------------------------------------
if (-not $NoInstall) {
    Write-Host ""
    Write-Host "[INFO] Actualizando pip..." -ForegroundColor Yellow
    & $newPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] pip install --upgrade pip fallo." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "[INFO] Instalando dependencias de requirements.txt..." -ForegroundColor Yellow
    & $newPy -m pip install -r $reqFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] pip install -r requirements.txt fallo." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "[OK]   Dependencias instaladas." -ForegroundColor Green
} else {
    Write-Host "[INFO] -NoInstall activo: se omite pip install." -ForegroundColor Yellow
}

# ----- 7. Resumen final ------------------------------------------------------
Write-Host ""
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " Listo. Activa el entorno con:" -ForegroundColor Cyan
Write-Host "   .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host ""
Write-Host " Verifica que todo esta correcto con:" -ForegroundColor Cyan
Write-Host "   .\scripts\verify_paths.ps1" -ForegroundColor White
Write-Host "=========================================================" -ForegroundColor Cyan
