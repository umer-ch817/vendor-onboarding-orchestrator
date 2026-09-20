# ===========================================================================
#  Vendor Onboarding Orchestrator - first-time setup (PowerShell)
#
#  Run this ONCE on a new machine, before start.bat.
#  It creates the settings file, the Python environment, and installs
#  everything the website needs.
#
#  Right-click this file and "Run with PowerShell", or from a terminal:
#      powershell -ExecutionPolicy Bypass -File setup.ps1
#
#  Python 3.12 is required. The pinned FastAPI and Pydantic versions have no
#  installers for 3.13 or newer, so a newer Python fails partway through with
#  a confusing message. This script warns you first.
#
#  This is the PowerShell twin of setup.bat. It exists because some Windows
#  machines restrict .bat files, and because PowerShell reports failures
#  honestly instead of continuing after a command that silently failed.
# ===========================================================================
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step($text) {
    Write-Host ""
    Write-Host "  $text" -ForegroundColor Cyan
}
function Write-Note($text) {
    Write-Host "         $text" -ForegroundColor DarkGray
}
function Write-Ok($text) {
    Write-Host "  [ok] $text" -ForegroundColor Green
}
function Write-Stop($text) {
    Write-Host ""
    Write-Host "  [STOP] $text" -ForegroundColor Red
}

Write-Host ""
Write-Host " ==========================================================" -ForegroundColor White
Write-Host "   Vendor Onboarding - first-time setup" -ForegroundColor White
Write-Host " ==========================================================" -ForegroundColor White

# --- Find a Python interpreter ----------------------------------------------
# Prefer 3.12 explicitly. "py -3.12" is the Windows launcher syntax.
$PyExe = $null
$PyPre = @()

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -c "import sys" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $PyExe = "py"
        $PyPre = @("-3.12")
    }
}
if (-not $PyExe) {
    if (Get-Command python3.12 -ErrorAction SilentlyContinue) {
        $PyExe = "python3.12"
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PyExe = "python"
    }
}

if (-not $PyExe) {
    Write-Stop "Python was not found."
    Write-Note "Install Python 3.12 from https://www.python.org/downloads/"
    Write-Note "and tick 'Add python.exe to PATH' during installation."
    exit 1
}

function Invoke-Py {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PyArgs)
    $all = @() + $PyPre + $PyArgs
    & $PyExe $all
    return $LASTEXITCODE
}

# --- Warn when it is not 3.12 ------------------------------------------------
$exit = Invoke-Py "-c" "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
if ($exit -ne 0) {
    $verArgs = @() + $PyPre + @("-c", "import sys; print(sys.version.split()[0])")
    $version = (& $PyExe $verArgs | Out-String).Trim()
    Write-Host ""
    Write-Host "  [WARN] Found Python $version but this project needs 3.12." -ForegroundColor Yellow
    Write-Note "The pinned FastAPI and Pydantic versions have no installers"
    Write-Note "for newer Pythons, so the next step will probably fail."
    Write-Note "Install Python 3.12 and run this again."
    $answer = Read-Host "  Continue anyway? (y/N)"
    if ($answer -notmatch "^[Yy]") {
        exit 1
    }
}

# --- [1/4] The settings file --------------------------------------------------
# Without .env the app falls back to the Docker hostnames in app/config.py
# ("postgres:5432", "http://n8n:5678"), which a natively-run backend cannot
# resolve -- so it starts and then cannot reach its own database.
Write-Step "[1/4] Creating the settings file..."
if (Test-Path (Join-Path $Root ".env")) {
    Write-Ok "Already there, skipping."
}
elseif (Test-Path (Join-Path $Root ".env.example")) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env") -Force
    Write-Ok "Created .env from .env.example"
}
else {
    Write-Stop "There is no .env and no .env.example to copy from."
    exit 1
}

# --- [2/4] The Python environment ----------------------------------------------
Write-Step "[2/4] Creating the Python environment..."
$VenvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    Write-Ok "Already exists, skipping."
}
else {
    $target = Join-Path $Root "backend\.venv"
    $exit = Invoke-Py "-m" "venv" $target
    if ($exit -ne 0) {
        Write-Stop "Could not create the Python environment."
        exit 1
    }
    Write-Ok "Created backend\.venv"
}

# --- [3/4] Python packages -------------------------------------------------------
Write-Step "[3/4] Installing Python packages, a few minutes..."
& $VenvPython "-m" "pip" "install" "--upgrade" "pip"
& $VenvPython "-m" "pip" "install" "-r" (Join-Path $Root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Stop "Package installation failed. See the message above."
    exit 1
}
Write-Ok "Python packages installed"

# --- [4/4] Website packages --------------------------------------------------------
Write-Step "[4/4] Installing website packages, a few minutes..."
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Stop "Node.js was not found, so the website cannot be built."
    Write-Note "Install Node.js 18 or newer from https://nodejs.org/"
    exit 1
}

Push-Location (Join-Path $Root "frontend")
& npm install
$NpmExit = $LASTEXITCODE
Pop-Location

# Captured above because Pop-Location resets $LASTEXITCODE, which would
# otherwise swallow a failed install.
if ($NpmExit -ne 0) {
    Write-Stop "Website package installation failed. See the message above."
    exit 1
}
Write-Ok "Website packages installed"

Write-Host ""
Write-Host " ==========================================================" -ForegroundColor White
Write-Host "   Setup complete" -ForegroundColor White
Write-Host " ==========================================================" -ForegroundColor White
Write-Host ""
Write-Host "   Now run start.bat" -ForegroundColor White
Write-Host ""
