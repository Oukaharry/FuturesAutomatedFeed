<#
.SYNOPSIS
  One-shot TradeOpss AI Windows build box setup + build (run inside the Windows 11 ARM VM).

.DESCRIPTION
  Installs Git and Python 3.12 (x64 — runs under Windows-on-ARM emulation so PyInstaller
  emits the same x64 .exe the GitHub runner does), clones/updates the repo, creates the
  venv, installs requirements, and runs build.py in local mode.

  Usage (PowerShell as Administrator, first run):
      Set-ExecutionPolicy -Scope Process Bypass -Force
      irm https://raw.githubusercontent.com/Oukaharry/FuturesAutomatedFeed/main/scripts/windows_build_box.ps1 | iex

  Later builds (repo already present):
      cd $env:USERPROFILE\tradeops-ai; .\scripts\windows_build_box.ps1 -BuildOnly
      .\scripts\windows_build_box.ps1 -BuildOnly -Trader     # no-ML Tradeopss_v*.exe

.PARAMETER Repo
  Git URL to clone (default: Oukaharry/FuturesAutomatedFeed). Use a local shared folder path instead
  (e.g. Z:\tradeops-ai) to build the working tree mounted from the Mac.
#>
[CmdletBinding()]
param(
    [string]$Repo = "https://github.com/Oukaharry/FuturesAutomatedFeed.git",
    [string]$Dest = "$env:USERPROFILE\tradeops-ai",
    [string]$Branch = "main",
    [switch]$Trader,
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"
function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

if (-not $BuildOnly) {
    Step "Installing Git + Python 3.12 (x64) via winget"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget not found. Open the Microsoft Store once (installs App Installer), then re-run."
    }
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    # x64 build: PyInstaller targets the interpreter's architecture.
    winget install --id Python.Python.3.12 -e --architecture x64 --silent `
        --accept-package-agreements --accept-source-agreements `
        --override "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_tcltk=1" | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")

    Step "Fetching repository → $Dest"
    if (Test-Path (Join-Path $Repo ".git")) {
        $Dest = $Repo                     # building a shared-folder checkout in place
    } elseif (Test-Path (Join-Path $Dest ".git")) {
        git -C $Dest fetch --quiet origin
        git -C $Dest checkout --quiet $Branch
        git -C $Dest pull --quiet --ff-only origin $Branch
    } else {
        git clone --quiet --branch $Branch $Repo $Dest
    }
}

Set-Location $Dest
Step "Python interpreter"
$py = (Get-Command py -ErrorAction SilentlyContinue) ? "py -3.12" : "python"
Invoke-Expression "$py -c `"import platform,struct; print(platform.python_version(), struct.calcsize('P')*8, 'bit')`""

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Step "Creating venv"
    Invoke-Expression "$py -m venv .venv"
}
$venvPy = ".\.venv\Scripts\python.exe"

Step "Installing requirements (first time takes several minutes)"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt --quiet
& $venvPy -m playwright install chromium 2>$null | Out-Null

Step ("Building " + ($(if ($Trader) { "Tradeopss (trader, no ML)" } else { "TradeopssAI (full)" })))
$env:GITHUB_ACTIONS = "true"             # build.py: run PyInstaller locally, don't dispatch to GitHub
$args = @("build.py", "--windows"); if ($Trader) { $args += "--trader" }
& $venvPy @args

Step "Done"
Get-ChildItem dist\*.exe | ForEach-Object { "{0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB) }
