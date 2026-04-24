# sync_prod_to_local.ps1
# Syncs production PostgreSQL (PythonAnywhere) to local PostgreSQL
# Usage (Windows PowerShell):  .\sync_prod_to_local.ps1
# Do NOT run with Python (python3 this_file.ps1) — that causes SyntaxError.
# On macOS/Linux use:  ./sync_prod_to_local.sh  (see that file for env vars).

$PROD_HOST = "127.0.0.1"
$PROD_PORT = "5433"   # SSH tunnel port — run: ssh -L 5433:ballerquotes-5185.postgres.pythonanywhere-services.com:15185 ballerquotes@ssh.pythonanywhere.com -N
$PROD_DB   = "tradeopss"
$PROD_USER = "tradeopss_admin"

$LOCAL_HOST = "localhost"
$LOCAL_PORT = "5432"
$LOCAL_DB   = "tradeopss"
$LOCAL_USER = "postgres"

# ── Production password ──────────────────────────────────────────────────────
# WARNING: Do NOT commit this file to Git. Add sync_prod_to_local.ps1 to .gitignore
$prodPass = "BallerAdmin123"

$localPass = "postgres123"

# ── Add PostgreSQL to PATH if not already available ───────────────────────────
$pgBin = "C:\Program Files\PostgreSQL\18\bin"
if (!(Get-Command psql -ErrorAction SilentlyContinue)) {
    $env:Path += ";$pgBin"
}

# ── Set env vars for pg tools ─────────────────────────────────────────────────
$env:PGPASSWORD = $localPass

Write-Host "`n[1/3] Dropping and recreating local database '$LOCAL_DB'..." -ForegroundColor Yellow
psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LOCAL_DB' AND pid <> pg_backend_pid();" postgres
psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -c "DROP DATABASE IF EXISTS $LOCAL_DB;" postgres
psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -c "CREATE DATABASE $LOCAL_DB;" postgres

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to recreate local database. Aborting." -ForegroundColor Red
    $env:PGPASSWORD = ""
    exit 1
}

Write-Host "[2/3] Dumping production to temp file..." -ForegroundColor Yellow
$tempFile = "$env:TEMP\prod_dump_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"
$env:PGPASSWORD = $prodPass
pg_dump -h $PROD_HOST -p $PROD_PORT -U $PROD_USER -d $PROD_DB --no-owner --no-acl -f $tempFile

if ($LASTEXITCODE -ne 0 -or !(Test-Path $tempFile)) {
    Write-Host "ERROR: pg_dump failed." -ForegroundColor Red
    $env:PGPASSWORD = ""
    exit 1
}

Write-Host "    Restoring to local database..." -ForegroundColor Yellow
$env:PGPASSWORD = $localPass
psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d $LOCAL_DB -f $tempFile

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Restore failed." -ForegroundColor Red
    Remove-Item $tempFile -Force
    $env:PGPASSWORD = ""
    exit 1
}

Remove-Item $tempFile -Force

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Sync failed during dump/restore." -ForegroundColor Red
    $env:PGPASSWORD = ""
    exit 1
}

# ── Clear passwords from environment ─────────────────────────────────────────
$env:PGPASSWORD = ""
$prodPass = ""
$localPass = ""

Write-Host "[3/3] Sync complete. Local '$LOCAL_DB' now matches production." -ForegroundColor Green
Write-Host "Completed at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

## Commands to run:
# ssh -L 5433:ballerquotes-5185.postgres.pythonanywhere-services.com:15185 ballerquotes@ssh.pythonanywhere.com -N                                              
# .\sync_prod_to_local.ps1                                                      
