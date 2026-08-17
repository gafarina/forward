<#
    Arranque local del valorizador en cualquier equipo Windows.

    El `.venv` que vive dentro de la carpeta del proyecto NO sirve: OneDrive lo
    sincroniza tal cual y su `pyvenv.cfg` apunta al intérprete absoluto del
    equipo donde se creó, de modo que en cualquier otro computador falla con
    "did not find executable at ...". Este script crea (o reutiliza) un entorno
    propio FUERA de la carpeta sincronizada, instala las dependencias, aplica
    migraciones y levanta el servidor.

    Uso:
        powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1
        powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1 -Demo
        powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1 -Puerto 8080

    -Demo carga el caso Cordada 31-05-2026 con el usuario `demo`.
#>
[CmdletBinding()]
param(
    [int]$Puerto = 8000,
    [switch]$Demo,
    [string]$ClaveDemo = 'forward-demo-2026',
    [switch]$SoloPreparar
)

$ErrorActionPreference = 'Stop'
$proyecto = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $env:USERPROFILE '.venvs\forward_v2'
$python = Join-Path $venv 'Scripts\python.exe'

Write-Host "Proyecto : $proyecto"
Write-Host "Entorno  : $venv"

# ── 1. Intérprete base ────────────────────────────────────────────────
if (-not (Test-Path $python)) {
    $base = $null
    foreach ($cmd in 'python', 'py') {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c) { $base = $c.Source; break }
    }
    if (-not $base) {
        throw 'No se encontró Python en el PATH. Instala Python 3.12 o superior desde python.org y vuelve a ejecutar.'
    }
    Write-Host "Creando entorno con $base ..."
    & $base -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno virtual.' }
}

# ── 2. Dependencias ───────────────────────────────────────────────────
$marca = Join-Path $venv '.deps-instaladas'
$req = Join-Path $proyecto 'requirements.txt'
if ((-not (Test-Path $marca)) -or ((Get-Item $req).LastWriteTime -gt (Get-Item $marca).LastWriteTime)) {
    Write-Host 'Instalando dependencias ...'
    & $python -m pip install --quiet --disable-pip-version-check --upgrade pip
    & $python -m pip install --quiet --disable-pip-version-check -r $req
    if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de dependencias.' }
    New-Item -ItemType File -Path $marca -Force | Out-Null
}

# ── 3. Configuración ──────────────────────────────────────────────────
$envFile = Join-Path $proyecto '.env'
if (-not (Test-Path $envFile)) {
    Write-Host 'No hay .env; generando uno para desarrollo local ...'
    $clave = & $python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
    @(
        "SECRET_KEY=$clave",
        'DEBUG=True',
        'ALLOWED_HOSTS=localhost,127.0.0.1',
        'LOG_LEVEL=INFO'
    ) | Set-Content -Path $envFile -Encoding utf8
}

# ── 4. Base de datos ──────────────────────────────────────────────────
Push-Location $proyecto
try {
    & $python manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) { throw 'Falló la migración de la base de datos.' }

    if ($Demo) {
        & $python manage.py cargar_demo --usuario demo --clave $ClaveDemo
        Write-Host ''
        Write-Host "Usuario de demostración: demo / $ClaveDemo" -ForegroundColor Green
    }

    if ($SoloPreparar) {
        Write-Host 'Entorno preparado. Para levantar el servidor ejecuta este script sin -SoloPreparar.'
        return
    }

    Write-Host ''
    Write-Host "Abriendo http://127.0.0.1:$Puerto  (Ctrl+C para detener)" -ForegroundColor Cyan
    & $python manage.py runserver "127.0.0.1:$Puerto"
}
finally {
    Pop-Location
}
