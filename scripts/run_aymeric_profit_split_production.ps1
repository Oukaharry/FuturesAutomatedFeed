# Apply Aymeric profit-split DB overrides (Windows / local against prod DATABASE_URL).
#
#   cd C:\path\to\FuturesAutomatedFeed
#   # .env must contain production DATABASE_URL
#   .\scripts\run_aymeric_profit_split_production.ps1
#
# Deploy dashboard code first (git pull on server + reload):
#   dashboard/watermark_service.py, dashboard/templates/index.html

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $env:DATABASE_URL) {
    if (Test-Path ".env") {
        Get-Content ".env" | ForEach-Object {
            if ($_ -match '^\s*([^#=]+)=(.*)$') {
                [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
            }
        }
    }
}
if (-not $env:DATABASE_URL) {
    Write-Error "DATABASE_URL is not set."
}

Write-Host "=== Dry run ===" -ForegroundColor Cyan
python scripts/fix_aymeric_profit_split.py --dry-run
$ans = Read-Host "Apply overrides to DB? [y/N]"
if ($ans -notmatch '^y(es)?$') {
    Write-Host "Aborted."
    exit 0
}
python scripts/fix_aymeric_profit_split.py
Write-Host "Done. Reload production web app and refresh Aymeric Profit Split tab." -ForegroundColor Green
