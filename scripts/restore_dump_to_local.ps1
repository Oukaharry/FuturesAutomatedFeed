param(
    [string]$DumpPath = "",
    [string]$LocalHost = "localhost",
    [string]$LocalPort = "5432",
    [string]$LocalDb = "tradeopss",
    [string]$LocalUser = "postgres"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

if (-not $DumpPath) {
    $latest = Get-ChildItem (Join-Path $repoRoot "pg_backups\pgbackup-*.dump") |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw "No dump found in pg_backups\pgbackup-*.dump"
    }
    $DumpPath = $latest.FullName
}

if (-not (Test-Path $DumpPath)) {
    throw "Dump file not found: $DumpPath"
}

function Import-DotEnvIfPresent {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    foreach ($line in (Get-Content -Raw $Path -Encoding UTF8) -split "`r?`n") {
        $t = ("" + $line).Trim()
        if (-not $t -or $t.StartsWith("#") -or -not $t.Contains("=")) { continue }
        $k, $v = $t.Split("=", 2)
        $v = $v.Trim().Trim('"').Trim("'")
        if (-not [Environment]::GetEnvironmentVariable($k.Trim(), "Process")) {
            [Environment]::SetEnvironmentVariable($k.Trim(), $v, "Process")
        }
    }
}

function ConvertFrom-SecureStringPlain {
    param([securestring]$Secure)
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Invoke-PgRestoreSection {
    param(
        [string]$Section,
        [string]$Dump,
        [string]$Db
    )
    Write-Host "  pg_restore --section=$Section ..." -ForegroundColor Cyan
    & pg_restore -U $LocalUser -h $LocalHost -p $LocalPort `
        --dbname=$Db --no-owner --no-acl --section=$Section $Dump
    if ($LASTEXITCODE -ne 0) {
        throw "pg_restore --section=$Section failed with exit code $LASTEXITCODE"
    }
}

Import-DotEnvIfPresent (Join-Path $repoRoot ".env")

$pgBinCandidates = @(
    "C:\Program Files\PostgreSQL\18\bin",
    "C:\Program Files\PostgreSQL\17\bin",
    "C:\Program Files\PostgreSQL\16\bin",
    "C:\Program Files\PostgreSQL\15\bin",
    "C:\Program Files\PostgreSQL\14\bin"
)

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    foreach ($pgBin in $pgBinCandidates) {
        if (Test-Path $pgBin) {
            $env:Path += ";$pgBin"
            break
        }
    }
}

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) { throw "psql not found. Add PostgreSQL bin to PATH." }
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) { throw "pg_restore not found. Add PostgreSQL bin to PATH." }

$localPass = ("" + ($(if ($env:LOCAL_PGPASSWORD) { $env:LOCAL_PGPASSWORD } else { $env:LOCAL_PGPASSWORD_DEFAULT }))).Trim()
if (-not $localPass) {
    $localPass = (ConvertFrom-SecureStringPlain (Read-Host "Enter LOCAL Postgres password" -AsSecureString)).Trim()
}
$env:PGPASSWORD = $localPass

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDb = "${LocalDb}__backup_$stamp"

$dedupeSql = @"
-- Prod dumps can contain duplicate user_credentials rows (same id or username+type).
DELETE FROM user_credentials a
USING user_credentials b
WHERE a.ctid < b.ctid AND a.id = b.id;

DELETE FROM user_credentials a
USING user_credentials b
WHERE a.ctid < b.ctid
  AND a.username = b.username
  AND a.user_type = b.user_type;

SELECT setval(
    pg_get_serial_sequence('user_credentials', 'id'),
    COALESCE((SELECT MAX(id) FROM user_credentials), 1)
);
"@

Write-Host "Restoring dump:" $DumpPath -ForegroundColor Yellow
Write-Host "Target local DB:" "$LocalUser@$LocalHost`:$LocalPort/$LocalDb" -ForegroundColor Yellow

psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LocalDb' AND pid <> pg_backend_pid();"

$exists = psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$LocalDb';"
if (("$(if ($exists) { $exists } else { '' })").Trim() -eq "1") {
    Write-Host "Renaming current '$LocalDb' to '$backupDb'..." -ForegroundColor Yellow
    psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE ""$LocalDb"" RENAME TO ""$backupDb"";"
}

Write-Host "Creating fresh '$LocalDb'..." -ForegroundColor Yellow
psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ""$LocalDb"";"

try {
    Write-Host "Phase 1/4: schema (pre-data)..." -ForegroundColor Yellow
    Invoke-PgRestoreSection -Section "pre-data" -Dump $DumpPath -Db $LocalDb

    Write-Host "Phase 2/4: table data..." -ForegroundColor Yellow
    Invoke-PgRestoreSection -Section "data" -Dump $DumpPath -Db $LocalDb

    Write-Host "Phase 3/4: dedupe user_credentials..." -ForegroundColor Yellow
    psql -U $LocalUser -h $LocalHost -p $LocalPort -d $LocalDb -v ON_ERROR_STOP=1 -c $dedupeSql

    Write-Host "Phase 4/4: indexes and constraints (post-data)..." -ForegroundColor Yellow
    & pg_restore -U $LocalUser -h $LocalHost -p $LocalPort `
        --dbname=$LocalDb --no-owner --no-acl --section=post-data $DumpPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  post-data reported warnings/errors (exit $LASTEXITCODE); verifying constraints..." -ForegroundColor Yellow
    }

    $verify = psql -U $LocalUser -h $LocalHost -p $LocalPort -d $LocalDb -tAc @"
SELECT CASE WHEN EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'user_credentials_pkey'
) AND EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_credentials_username_type'
) THEN 'ok' ELSE 'missing' END;
"@
    if (("$(if ($verify) { $verify } else { '' })").Trim() -ne "ok") {
        throw "Restore verification failed: user_credentials constraints missing"
    }

    psql -U $LocalUser -h $LocalHost -p $LocalPort -d $LocalDb -c @"
SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = 'public';
SELECT COUNT(*) AS user_credentials FROM user_credentials;
SELECT COUNT(*) AS clients_data FROM clients_data;
"@
    Write-Host "Restore complete. Backup DB: $backupDb" -ForegroundColor Green
} catch {
    Write-Host "Restore failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Your previous DB is still available as: $backupDb" -ForegroundColor Yellow
    exit 1
} finally {
    $env:PGPASSWORD = ""
}
