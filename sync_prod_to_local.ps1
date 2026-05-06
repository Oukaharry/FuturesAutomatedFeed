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

# ── Passwords ────────────────────────────────────────────────────────────────
# This script is safe to commit: passwords are NOT hardcoded.
# Provide them via `.env` (recommended) or environment variables, otherwise you will be prompted:
# - PROD_PGPASSWORD / PROD_PGPASSWORD_ALT (and optional PROD_PGPASSWORD_DEFAULT)
# - LOCAL_PGPASSWORD / LOCAL_PGPASSWORD_ALT (and optional LOCAL_PGPASSWORD_DEFAULT)

function Import-DotEnvIfPresent {
    param([string]$Path)
    if (-not $Path) { return }
    if (-not (Test-Path $Path)) { return }
    try {
        $lines = Get-Content -Raw $Path -ErrorAction Stop -Encoding UTF8
        foreach ($line in ($lines -split "`r?`n")) {
            $t = ("" + $line).Trim()
            if (-not $t) { continue }
            if ($t.StartsWith("#")) { continue }
            $idx = $t.IndexOf("=")
            if ($idx -lt 1) { continue }
            $k = $t.Substring(0, $idx).Trim()
            $v = $t.Substring($idx + 1).Trim()
            if (-not $k) { continue }
            # Strip optional surrounding quotes
            if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
                $v = $v.Substring(1, $v.Length - 2)
            }
            $existing = [Environment]::GetEnvironmentVariable($k, "Process")
            if (-not $existing) {
                [Environment]::SetEnvironmentVariable($k, $v, "Process")
            }
        }
    } catch {
        # non-fatal
    }
}

# Auto-load .env from the repo root (it's already gitignored).
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-DotEnvIfPresent (Join-Path $scriptDir ".env")

function ConvertFrom-SecureStringPlain {
    param([Parameter(Mandatory=$true)][securestring]$Secure)
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

$prodPass = ("" + ($(if ($env:PROD_PGPASSWORD) { $env:PROD_PGPASSWORD } else { $env:PROD_PGPASSWORD_DEFAULT }))).Trim()
if (-not $prodPass) {
    $sec = Read-Host "Enter PROD Postgres password (input hidden)" -AsSecureString
    $prodPass = (ConvertFrom-SecureStringPlain $sec).Trim()
}

$localPass = ("" + ($(if ($env:LOCAL_PGPASSWORD) { $env:LOCAL_PGPASSWORD } else { $env:LOCAL_PGPASSWORD_DEFAULT }))).Trim()
if (-not $localPass) {
    $sec2 = Read-Host "Enter LOCAL Postgres password (input hidden)" -AsSecureString
    $localPass = (ConvertFrom-SecureStringPlain $sec2).Trim()
}

# ── Add PostgreSQL to PATH if not already available ───────────────────────────
$pgBinCandidates = @(
    "C:\Program Files\PostgreSQL\18\bin",
    "C:\Program Files\PostgreSQL\16\bin"
)
if (!(Get-Command psql -ErrorAction SilentlyContinue)) {
    foreach ($pgBin in $pgBinCandidates) {
        if (Test-Path $pgBin) {
            $env:Path += ";$pgBin"
            break
        }
    }
}

# ── Password fallback helpers ────────────────────────────────────────────────
function Invoke-PgWithPasswords {
    param(
        [Parameter(Mandatory=$true)][string]$Label,
        [Parameter(Mandatory=$true)][string[]]$Passwords,
        [Parameter(Mandatory=$true)][scriptblock]$Run
    )

    foreach ($pw in ($Passwords | Where-Object { $_ -ne $null -and $_ -ne "" })) {
        $env:PGPASSWORD = $pw
        $out = & $Run 2>&1
        if ($LASTEXITCODE -eq 0) { return $true }

        $msg = ($out | Out-String)
        $authFailed = ($msg -match "password authentication failed" -or $msg -match "no password supplied" -or $msg -match "SASL authentication failed")
        if (-not $authFailed) {
            Write-Host "ERROR: $Label failed: $msg" -ForegroundColor Red
            return $false
        }
    }

    Write-Host "ERROR: $Label failed (all password attempts rejected)." -ForegroundColor Red
    return $false
}

# ── Set env vars for pg tools ─────────────────────────────────────────────────
$localPassCandidates = @(
    $env:LOCAL_PGPASSWORD,
    $localPass,
    $env:LOCAL_PGPASSWORD_ALT,
    "password123" # fallback for other local environments that still use this
    ""
) | Where-Object { $_ -ne $null -and "$_".Trim() -ne "" } | ForEach-Object { "$_".Trim() }
$prodPassCandidates = @(
    $env:PROD_PGPASSWORD,
    $prodPass,
    $env:PROD_PGPASSWORD_ALT
) | Where-Object { $_ -ne $null -and "$_".Trim() -ne "" } | ForEach-Object { "$_".Trim() }

# ── Preflight: confirm SSH tunnel/port is reachable ───────────────────────────
Write-Host "`n[0/4] Checking production tunnel $PROD_HOST`:$PROD_PORT ..." -ForegroundColor Yellow
try {
    $tnc = Test-NetConnection -ComputerName $PROD_HOST -Port ([int]$PROD_PORT) -WarningAction SilentlyContinue
    if (-not $tnc.TcpTestSucceeded) {
        Write-Host "ERROR: Can't reach $PROD_HOST`:$PROD_PORT." -ForegroundColor Red
        Write-Host "Start your SSH tunnel first (example):" -ForegroundColor DarkGray
        Write-Host "  ssh -L 5433:ballerquotes-5185.postgres.pythonanywhere-services.com:15185 ballerquotes@ssh.pythonanywhere.com -N" -ForegroundColor DarkGray
        $env:PGPASSWORD = ""
        exit 1
    }
} catch {
    # If Test-NetConnection isn't available, we still try psql/pg_dump below.
}

Write-Host "    Tunnel looks reachable. Verifying auth..." -ForegroundColor Yellow
$ok = Invoke-PgWithPasswords -Label "Production auth check" -Passwords $prodPassCandidates -Run {
    psql -h $PROD_HOST -p $PROD_PORT -U $PROD_USER -d $PROD_DB -c "SELECT 1;" | Out-Null
}
if (-not $ok) {
    Write-Host "ERROR: Can't authenticate to production over the tunnel (wrong password/user/db, or tunnel points to wrong server)." -ForegroundColor Red
    $env:PGPASSWORD = ""
    exit 1
}

# ── Safe swap restore strategy ────────────────────────────────────────────────
# 1) Dump prod to a temp file
# 2) Restore into a NEW temporary local database (no disruption to current LOCAL_DB)
# 3) Validate the temp DB
# 4) Swap: rename current LOCAL_DB to backup, rename temp → LOCAL_DB (brief disruption only at swap time)
$stamp = (Get-Date -Format 'yyyyMMdd_HHmmss')
$tempDb = "${LOCAL_DB}__sync_tmp_$stamp"
$backupDb = "${LOCAL_DB}__backup_$stamp"

Write-Host "`n[1/4] Dumping production to temp file..." -ForegroundColor Yellow
$tempFile = "$env:TEMP\prod_dump_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"
$ok = Invoke-PgWithPasswords -Label "Production pg_dump" -Passwords $prodPassCandidates -Run {
    pg_dump -h $PROD_HOST -p $PROD_PORT -U $PROD_USER -d $PROD_DB --no-owner --no-acl -f $tempFile
}

if (-not $ok -or !(Test-Path $tempFile)) {
    Write-Host "ERROR: pg_dump failed." -ForegroundColor Red
    $env:PGPASSWORD = ""
    exit 1
}

Write-Host "[2/4] Creating temp local database '$tempDb'..." -ForegroundColor Yellow
$ok = Invoke-PgWithPasswords -Label "Local create temp database" -Passwords $localPassCandidates -Run {
    psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d postgres -c "DROP DATABASE IF EXISTS ""$tempDb"";"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d postgres -c "CREATE DATABASE ""$tempDb"";"
}

if (-not $ok) {
    Write-Host "ERROR: Failed to create temp database. Aborting." -ForegroundColor Red
    Remove-Item $tempFile -Force
    $env:PGPASSWORD = ""
    exit 1
}

Write-Host "[3/4] Restoring dump into temp database (no impact on '$LOCAL_DB')..." -ForegroundColor Yellow
$ok = Invoke-PgWithPasswords -Label "Local restore to temp DB" -Passwords $localPassCandidates -Run {
    psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d $tempDb -f $tempFile
}

if (-not $ok) {
    Write-Host "ERROR: Restore into temp database failed. Keeping existing '$LOCAL_DB' unchanged." -ForegroundColor Red
    try {
        Invoke-PgWithPasswords -Label "Local drop temp database" -Passwords $localPassCandidates -Run {
            psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d postgres -c "DROP DATABASE IF EXISTS ""$tempDb"";"
        } | Out-Null
    } catch { }
    Remove-Item $tempFile -Force
    $env:PGPASSWORD = ""
    exit 1
}

# Basic validation: ensure DB is reachable and has tables after restore.
Write-Host "    Validating temp database..." -ForegroundColor Yellow
$ok = Invoke-PgWithPasswords -Label "Validate temp DB" -Passwords $localPassCandidates -Run {
    psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d $tempDb -c "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = 'public';"
}
if (-not $ok) {
    Write-Host "ERROR: Temp database validation failed. Keeping existing '$LOCAL_DB' unchanged." -ForegroundColor Red
    try {
        Invoke-PgWithPasswords -Label "Local drop temp database" -Passwords $localPassCandidates -Run {
            psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d postgres -c "DROP DATABASE IF EXISTS ""$tempDb"";"
        } | Out-Null
    } catch { }
    Remove-Item $tempFile -Force
    $env:PGPASSWORD = ""
    exit 1
}

Write-Host "[4/4] Swapping databases (briefly interrupts local connections)..." -ForegroundColor Yellow
$ok = Invoke-PgWithPasswords -Label "Swap databases" -Passwords $localPassCandidates -Run {
    # Kick everyone off the target DB just for the swap.
    psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$LOCAL_DB', '$tempDb') AND pid <> pg_backend_pid();"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Rename existing LOCAL_DB out of the way (backup) if it exists.
    psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d postgres -c "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '$LOCAL_DB') THEN EXECUTE 'ALTER DATABASE ""$LOCAL_DB"" RENAME TO ""$backupDb""'; END IF; END $$;"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Rename temp DB into place.
    psql -U $LOCAL_USER -h $LOCAL_HOST -p $LOCAL_PORT -d postgres -c "ALTER DATABASE ""$tempDb"" RENAME TO ""$LOCAL_DB"";"
}

Remove-Item $tempFile -Force

if (-not $ok) {
    Write-Host "ERROR: Swap failed. Your previous local DB should still be available as '$backupDb' (if it existed)." -ForegroundColor Red
    $env:PGPASSWORD = ""
    exit 1
}

# ── Clear passwords from environment ─────────────────────────────────────────
$env:PGPASSWORD = ""
$prodPass = ""
$localPass = ""

Write-Host "Sync complete. Local '$LOCAL_DB' now matches production." -ForegroundColor Green
Write-Host "Previous local database (backup): $backupDb" -ForegroundColor DarkGray
Write-Host "Completed at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

## Commands to run:
# ssh -L 5433:ballerquotes-5185.postgres.pythonanywhere-services.com:15185 ballerquotes@ssh.pythonanywhere.com -N                                              
# .\sync_prod_to_local.ps1                                                      
