<#
.SYNOPSIS
    Empaqueta el dashboard Streamlit en un ZIP listo para desplegar en Azure App Service.

.DESCRIPCION
    Copia SOLO lo que el servidor web necesita en tiempo de ejecución
    (src/, config/, .streamlit/) a una carpeta de staging, usa
    requirements-dashboard.txt como requirements.txt (lo que instala Oryx en Azure),
    y comprime todo en deploy.zip en la raíz del proyecto.

    NO incluye: .venv, data_lake, notebooks, tests, logs, __pycache__, catalog.db.
    (El dashboard lee los datos desde Azure PostgreSQL, no del disco.)

.USO
    ./deploy.ps1
    # luego:  az webapp deploy -g rg-tfm -n tfm-dashboard --type zip --src-path deploy.zip
#>
[CmdletBinding()]
param(
    [string]$OutFile = "deploy.zip"
)
$ErrorActionPreference = "Stop"

$root    = $PSScriptRoot
$staging = Join-Path $root ".deploy_build"
$zipPath = Join-Path $root $OutFile

Write-Host "==> Preparando staging en $staging" -ForegroundColor Cyan
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null

# --- 1) Copiar el código y la configuración que el runtime necesita ---
foreach ($item in @("src", "config", ".streamlit")) {
    $srcPath = Join-Path $root $item
    if (-not (Test-Path $srcPath)) { throw "No existe: $srcPath" }
    Write-Host "    + $item"
    Copy-Item $srcPath (Join-Path $staging $item) -Recurse -Force
}

# --- 2) requirements-dashboard.txt  ->  requirements.txt (raíz del zip) ---
Copy-Item (Join-Path $root "requirements-dashboard.txt") `
          (Join-Path $staging "requirements.txt") -Force
Write-Host "    + requirements.txt (desde requirements-dashboard.txt)"

# --- 3) Podar basura que se haya colado (cachés, parquet, sqlite) ---
Get-ChildItem $staging -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
Get-ChildItem $staging -Recurse -Include "*.pyc", "*.parquet", "*.db", "*.log" |
    Remove-Item -Force -ErrorAction SilentlyContinue

# --- 4) Comprimir el CONTENIDO de staging en la raíz del zip ---
# OJO: Compress-Archive de Windows PowerShell 5.1 escribe separadores '\' en los
# nombres de entrada, y Azure (Linux) los interpretaría como parte del nombre de
# fichero (no como carpetas). Construimos el zip a mano con separadores '/'.
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Write-Host "==> Comprimiendo -> $zipPath (rutas POSIX '/')" -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, "Create")
try {
    $base = (Resolve-Path $staging).Path.TrimEnd('\') + '\'
    foreach ($file in Get-ChildItem $staging -Recurse -File) {
        $rel = $file.FullName.Substring($base.Length).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $file.FullName, $rel,
            [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $zip.Dispose()
}

Remove-Item $staging -Recurse -Force

$sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "OK  deploy.zip listo ($sizeMB MB)" -ForegroundColor Green
Write-Host ""
Write-Host "Siguiente paso (una vez creado el App Service):" -ForegroundColor Yellow
Write-Host "  az webapp deploy -g rg-tfm -n tfm-dashboard --type zip --src-path deploy.zip"
