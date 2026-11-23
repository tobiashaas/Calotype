<#
.SYNOPSIS
  Starts the whole local stack: infrastructure, migrations, API, the four workers, Bridge.

.DESCRIPTION
  One source of truth for ports and credentials: infra/compose/.env (copy of env.example).
  DATABASE_URL, REDIS_URL and S3_* are derived from it, the API port from the Bridge's
  bridge.json (api_base_url) so Bridge and API always agree. Needs `uv sync` once.

  Processes run in the background; logs go to %LOCALAPPDATA%\Calotype\dev-logs.

.EXAMPLE
  powershell scripts/dev.ps1            # start everything
  powershell scripts/dev.ps1 -Stop      # stop API, workers and Bridge (containers keep running)
  powershell scripts/dev.ps1 -NoBridge  # e.g. when the desktop app runs the Bridge
#>
param(
  [switch]$Stop,
  [switch]$NoBridge
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $env:LOCALAPPDATA "Calotype\dev-logs"
$PidFile = Join-Path $LogDir "pids.txt"
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Stop-Stack {
  if (Test-Path $PidFile) {
    foreach ($id in Get-Content $PidFile) {
      try { Stop-Process -Id ([int]$id) -Force -ErrorAction Stop } catch {}
    }
    Remove-Item $PidFile
  }
}

if ($Stop) { Stop-Stack; Write-Host "stopped"; return }

# --- configuration ---------------------------------------------------------------------
$EnvFile = Join-Path $Root "infra\compose\.env"
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $Root "infra\compose\env.example") $EnvFile
  Write-Host "created infra/compose/.env from env.example"
}
$cfg = @{}
foreach ($line in Get-Content $EnvFile) {
  if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { $cfg[$Matches[1]] = $Matches[2] }
}
function Get-Cfg([string]$key, [string]$default) { if ($cfg.ContainsKey($key)) { $cfg[$key] } else { $default } }

$project = Get-Cfg "COMPOSE_PROJECT_NAME" "calotype"
$pgUser = Get-Cfg "LR_FF_POSTGRES_USER" "calotype"
$pgPass = Get-Cfg "LR_FF_POSTGRES_PASSWORD" "calotype"
$pgDb = Get-Cfg "LR_FF_POSTGRES_DB" "calotype"
# 127.0.0.1, never localhost: on Windows localhost tries IPv6 first and hangs ~21 s per connection.
$env:DATABASE_URL = "postgresql+psycopg://${pgUser}:${pgPass}@127.0.0.1:$(Get-Cfg 'LR_FF_POSTGRES_PORT' '5432')/$pgDb"
$env:REDIS_URL = "redis://127.0.0.1:$(Get-Cfg 'LR_FF_REDIS_PORT' '6379')/0"
$env:S3_ENDPOINT = "http://127.0.0.1:$(Get-Cfg 'LR_FF_MINIO_PORT' '9000')"
$env:S3_ACCESS_KEY = Get-Cfg "LR_FF_MINIO_USER" "minio"
$env:S3_SECRET_KEY = Get-Cfg "LR_FF_MINIO_PASSWORD" "miniosecret_changeme"
$env:S3_BUCKET = Get-Cfg "S3_BUCKET" "calotype-photos"
$env:LOG_FORMAT = "text"

$apiPort = 8080
$bridgeJson = Join-Path $(if ($env:CALOTYPE_BRIDGE_DATA_DIR) { $env:CALOTYPE_BRIDGE_DATA_DIR } else { Join-Path $env:APPDATA "Calotype" }) "bridge.json"
if (Test-Path $bridgeJson) {
  $url = (Get-Content $bridgeJson -Raw | ConvertFrom-Json).api_base_url
  if ($url -match ':(\d+)/?$') { $apiPort = [int]$Matches[1] }
}

$py = Join-Path $Root ".venv\Scripts"
if (-not (Test-Path (Join-Path $py "python.exe"))) { throw "no .venv - run 'uv sync' in $Root first" }

# --- infrastructure + migrations ---------------------------------------------------------
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker is not running - start Docker Desktop first" }
Push-Location (Join-Path $Root "infra\compose")
docker compose -p $project --env-file $EnvFile up -d --wait
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "docker compose failed" }
Pop-Location

Push-Location (Join-Path $Root "infra\migrations")
& (Join-Path $py "alembic.exe") upgrade head
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "migrations failed" }
Pop-Location

# --- processes -----------------------------------------------------------------------------
Stop-Stack
$started = @()
function Start-Logged([string]$name, [string]$exe, [string[]]$arguments = @()) {
  $opts = @{
    FilePath = $exe; WorkingDirectory = $Root; WindowStyle = "Hidden"; PassThru = $true
    RedirectStandardOutput = (Join-Path $LogDir "$name.log")
    RedirectStandardError = (Join-Path $LogDir "$name.err.log")
  }
  # Windows PowerShell 5.1 rejects an empty -ArgumentList
  if ($arguments.Count -gt 0) { $opts.ArgumentList = $arguments }
  $p = Start-Process @opts
  $script:started += $p.Id
}
Start-Logged "api" (Join-Path $py "uvicorn.exe") @("calotype_api.main:app", "--host", "127.0.0.1", "--port", "$apiPort")
foreach ($w in "feature", "train", "inference", "cull") {
  Start-Logged "$w-worker" (Join-Path $py "calotype-$w-worker.exe")
}
if (-not $NoBridge) {
  $bridge = Join-Path $Root "apps\bridge\target\release\calotype-bridge-headless.exe"
  if (Test-Path $bridge) { Start-Logged "bridge" $bridge }
  else { Write-Warning "no release Bridge build - cargo build --release -p calotype-bridge-core in apps/bridge" }
}
$started | Set-Content $PidFile

foreach ($i in 1..30) {
  try { Invoke-RestMethod "http://127.0.0.1:$apiPort/health" -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 }
}
Write-Host "Calotype dev stack ($project): API http://127.0.0.1:$apiPort, logs $LogDir"
Write-Host "stop with: powershell scripts/dev.ps1 -Stop"
