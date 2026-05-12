param(
    [string]$DumpPath = "",
    [string]$LocalHost = "localhost",
    [string]$LocalPort = "5432",
    [string]$LocalDb = "tradeopss",
    [string]$LocalUser = "postgres"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $DumpPath) {
    $latest = Get-ChildItem (Join-Path $scriptDir "pg_backups\pgbackup-*.dump") |
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

Import-DotEnvIfPresent (Join-Path $scriptDir ".env")

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

Write-Host "Restoring dump:" $DumpPath -ForegroundColor Yellow
Write-Host "Target local DB:" "$LocalUser@$LocalHost`:$LocalPort/$LocalDb" -ForegroundColor Yellow

psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LocalDb' AND pid <> pg_backend_pid();"

$exists = psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$LocalDb';"
if ($exists.Trim() -eq "1") {
    Write-Host "Renaming current '$LocalDb' to '$backupDb'..." -ForegroundColor Yellow
    psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE ""$LocalDb"" RENAME TO ""$backupDb"";"
}

Write-Host "Creating fresh '$LocalDb'..." -ForegroundColor Yellow
psql -U $LocalUser -h $LocalHost -p $LocalPort -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ""$LocalDb"";"

try {
    Write-Host "Running pg_restore..." -ForegroundColor Yellow
    pg_restore -U $LocalUser -h $LocalHost -p $LocalPort --dbname=$LocalDb --no-owner --no-acl --clean --if-exists $DumpPath

    if ($LASTEXITCODE -ne 0) {
        throw "pg_restore failed with exit code $LASTEXITCODE"
    }

    psql -U $LocalUser -h $LocalHost -p $LocalPort -d $LocalDb -c "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = 'public';"
    Write-Host "Restore complete. Backup DB: $backupDb" -ForegroundColor Green
} catch {
    Write-Host "Restore failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Your previous DB is still available as: $backupDb" -ForegroundColor Yellow
    exit 1
} finally {
    $env:PGPASSWORD = ""
}
