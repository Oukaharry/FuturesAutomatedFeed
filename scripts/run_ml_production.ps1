# Generate ML trade timing report from PRODUCTION PostgreSQL (SSH tunnel).
# Prerequisites: .env with PRODUCTION_* and SSH_TUNNEL_* (see .env.example)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Load .env into process environment (simple KEY=VALUE parser)
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        if ($line -match '^([^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $val = $matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($name, $val, "Process")
        }
    }
}

$required = @(
    "PRODUCTION_USE_SSH_TUNNEL",
    "PRODUCTION_DB_HOST",
    "PRODUCTION_DB_PORT",
    "PRODUCTION_DB_NAME",
    "PRODUCTION_DB_USER",
    "PRODUCTION_DB_PASSWORD",
    "SSH_TUNNEL_HOST",
    "SSH_TUNNEL_USER",
    "SSH_TUNNEL_PASSWORD"
)
$missing = $required | Where-Object { -not [Environment]::GetEnvironmentVariable($_) }
if ($missing.Count -gt 0) {
    Write-Host "Missing in .env (copy block from .env.example and fill passwords):" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    Write-Host "Then run:  .\scripts\run_ml_production.ps1"
    exit 1
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$out = Join-Path $Root "research\reports\ml_trade_timing_analysis.html"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null

$env:DB_CONNECT_TIMEOUT = "45"
$env:DB_POOL_MIN = "1"
$env:DB_POOL_MAX = "3"
$env:SSH_TUNNEL_READY_TIMEOUT = "90"

Write-Host "Connecting to production via SSH tunnel and building ML report..." -ForegroundColor Cyan
& $python (Join-Path $Root "scripts\trade_history_analysis.py") --portfolio --production -o $out
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Report: $out" -ForegroundColor Green
Write-Host "Confirm header shows data_source=production (not localhost)."
