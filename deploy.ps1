# =============================================================================
# PowerShell Deployment Script for MT5 Hedging Dashboard (Windows)
# =============================================================================
# For Windows Server or local development deployment
#
# Usage:
#   .\deploy.ps1 setup
#   .\deploy.ps1 start
#   .\deploy.ps1 stop
# =============================================================================

param(
    [Parameter(Position=0)]
    [ValidateSet("setup", "start", "stop", "restart", "status", "test")]
    [string]$Command = "status"
)

# Configuration
$AppName = "MT5-Dashboard"
$AppDir = $PSScriptRoot
$VenvDir = Join-Path $AppDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$GunicornExe = Join-Path $VenvDir "Scripts\gunicorn.exe"
$WaitressExe = Join-Path $VenvDir "Scripts\waitress-serve.exe"
$LogDir = Join-Path $AppDir "logs"
$Port = 8000

# Colors
function Write-Info { Write-Host "[INFO] $args" -ForegroundColor Green }
function Write-Warn { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err { Write-Host "[ERROR] $args" -ForegroundColor Red }

# =============================================================================
# Setup Functions
# =============================================================================

function Setup-Environment {
    Write-Info "Setting up $AppName..."
    
    # Create logs directory
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir | Out-Null
        Write-Info "Created logs directory"
    }
    
    # Create virtual environment if not exists
    if (-not (Test-Path $VenvDir)) {
        Write-Info "Creating virtual environment..."
        python -m venv $VenvDir
    }
    
    # Activate and install dependencies
    Write-Info "Installing dependencies..."
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r requirements-production.txt
    
    # Install waitress for Windows (alternative to Gunicorn)
    & $PythonExe -m pip install waitress
    
    # Create .env if not exists
    if (-not (Test-Path (Join-Path $AppDir ".env"))) {
        Write-Info "Creating .env from template..."
        Copy-Item (Join-Path $AppDir ".env.example") (Join-Path $AppDir ".env")
        Write-Warn "Please edit .env with your production values!"
    }
    
    Write-Info "Setup complete!"
}

function Start-Dashboard {
    Write-Info "Starting $AppName on port $Port..."
    
    # Check if already running
    $existing = Get-Process -Name "waitress*" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Warn "Dashboard may already be running. Use 'stop' first."
    }
    
    # Set environment variables
    $env:FLASK_ENV = "production"
    
    # Start with waitress (Windows-friendly WSGI server)
    Write-Info "Starting Waitress server..."
    Start-Process -FilePath $WaitressExe `
        -ArgumentList "--listen=0.0.0.0:$Port", "wsgi:app" `
        -WorkingDirectory $AppDir `
        -NoNewWindow
    
    Start-Sleep -Seconds 2
    
    # Check if started
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 5
        Write-Info "Dashboard is running at http://localhost:$Port"
    } catch {
        Write-Err "Failed to start. Check logs for details."
    }
}

function Stop-Dashboard {
    Write-Info "Stopping $AppName..."
    
    # Find and stop waitress processes
    $processes = Get-Process | Where-Object { $_.ProcessName -like "*waitress*" -or $_.ProcessName -like "*python*" }
    
    foreach ($proc in $processes) {
        try {
            # Check if it's our app
            if ($proc.Path -like "*$AppDir*") {
                Stop-Process -Id $proc.Id -Force
                Write-Info "Stopped process $($proc.Id)"
            }
        } catch {
            # Ignore errors
        }
    }
    
    Write-Info "Dashboard stopped"
}

function Restart-Dashboard {
    Stop-Dashboard
    Start-Sleep -Seconds 2
    Start-Dashboard
}

function Get-DashboardStatus {
    Write-Info "Checking $AppName status..."
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 5
        $data = $response.Content | ConvertFrom-Json
        Write-Host ""
        Write-Host "Status: " -NoNewline; Write-Host $data.status -ForegroundColor Green
        Write-Host "Service: $($data.service)"
        Write-Host "Version: $($data.version)"
        Write-Host "URL: http://localhost:$Port"
    } catch {
        Write-Err "Dashboard is not running or not responding"
    }
}

function Test-Dashboard {
    Write-Info "Running quick tests..."
    
    # Activate venv and run tests
    & $PythonExe -c "from dashboard.database import init_database; print('Database: OK')"
    & $PythonExe -c "from dashboard.app import app; print('Flask App: OK')"
    
    Write-Info "Tests complete"
}

# =============================================================================
# Main Script
# =============================================================================

switch ($Command) {
    "setup" {
        Setup-Environment
    }
    "start" {
        Start-Dashboard
    }
    "stop" {
        Stop-Dashboard
    }
    "restart" {
        Restart-Dashboard
    }
    "status" {
        Get-DashboardStatus
    }
    "test" {
        Test-Dashboard
    }
    default {
        Write-Host "MT5 Hedging Dashboard - Windows Deployment Script"
        Write-Host ""
        Write-Host "Usage: .\deploy.ps1 <command>"
        Write-Host ""
        Write-Host "Commands:"
        Write-Host "  setup   - Set up virtual environment and dependencies"
        Write-Host "  start   - Start the dashboard server"
        Write-Host "  stop    - Stop the dashboard server"
        Write-Host "  restart - Restart the dashboard server"
        Write-Host "  status  - Check if dashboard is running"
        Write-Host "  test    - Run quick tests"
    }
}
