<#
.SYNOPSIS
    Vision 2.0 bootstrap for Windows.

.DESCRIPTION
    Creates a Python 3.10-3.12 virtual environment, installs pinned
    dependencies, checks for ffmpeg/Ollama and prints the privacy settings
    Vision needs. Run from the repository root:

        powershell -ExecutionPolicy Bypass -File .\setup.ps1

.PARAMETER PythonExe
    Explicit Python launcher/executable (must be 3.10-3.12).

.PARAMETER SkipSystemPackages
    Do not attempt winget installs for ffmpeg/Ollama.
#>
[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [switch]$SkipSystemPackages
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Warn($Message) { Write-Host "[warning] $Message" -ForegroundColor Yellow }
function Die($Message) { Write-Host "[error] $Message" -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------- find Python
$candidates = @()
if ($PythonExe) { $candidates += $PythonExe }
$candidates += @("py -3.12", "py -3.11", "py -3.10", "python")

$python = $null
$pythonVersion = $null
foreach ($candidate in $candidates) {
    try {
        $parts = $candidate.Split(" ")
        $exe = $parts[0]
        $launcherArgs = @()
        if ($parts.Length -gt 1) { $launcherArgs = $parts[1..($parts.Length - 1)] }
        $version = & $exe @launcherArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version.Trim() -match '^3\.(10|11|12)$') {
            $python = $candidate
            $pythonVersion = $version.Trim()
            break
        }
    } catch { }
}

if (-not $python) {
    Die @"
Python 3.10, 3.11 or 3.12 was not found. MediaPipe does not support 3.13+ yet.
Install it with:
    winget install Python.Python.3.12
Then reopen PowerShell and run this script again.
"@
}
Write-Step "Using $python (Python $pythonVersion)"

# ------------------------------------------------------------ system packages
function Test-Command($Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

if (-not $SkipSystemPackages) {
    if (-not (Test-Command "ffmpeg")) {
        Write-Warn "ffmpeg not found. edge-tts needs it for speech playback on Windows."
        if (Test-Command "winget") {
            $answer = Read-Host "Install ffmpeg with winget now? [y/N]"
            if ($answer -match '^[Yy]') {
                winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
            }
        } else {
            Write-Warn "Install ffmpeg manually: https://www.gyan.dev/ffmpeg/builds/ and add it to PATH."
        }
    }
    if (-not (Test-Command "ollama")) {
        Write-Warn "Ollama is not on PATH. Install it from https://ollama.com/download"
    }
}

# ------------------------------------------------------------------- venv
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Step "Creating .venv..."
    $parts = $python.Split(" ")
    $exe = $parts[0]
    $launcherArgs = @()
    if ($parts.Length -gt 1) { $launcherArgs = $parts[1..($parts.Length - 1)] }
    & $exe @launcherArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Die "Could not create the virtual environment." }
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { Die "Virtual environment is broken; delete .venv and re-run." }

Write-Step "Installing pinned Python dependencies..."
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { Die "pip upgrade failed." }
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Die "Dependency installation failed. See the error above." }

# Optional Windows-only absolute volume control.
Write-Step "Installing optional Windows volume support (pycaw)..."
& $venvPython -m pip install "pycaw==20260927" "comtypes==1.5.0"
if ($LASTEXITCODE -ne 0) {
    Write-Warn "pycaw install failed; Vision will use nircmd or media keys for volume."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Step "Created .env from .env.example - edit it to set CREATOR_NAME, OLLAMA_MODEL, etc."
}

Write-Step "Running diagnostics..."
& $venvPython -m vision --diagnose

Write-Host @"

Vision is installed.

  Activate:             .\.venv\Scripts\Activate.ps1
  Configure:            python -m vision --setup
  Check capabilities:   python -m vision --doctor
  Start:                python -m vision
  Typed mode (no mic):  python -m vision --text
  Interface only:       python interface.py [--sd|--hd]
  Tests:                python -m pytest
  Lint/format:          ruff check . ; black --check .

Windows privacy settings (Settings > Privacy & security):
  * Microphone      -> allow desktop apps
  * Camera          -> allow desktop apps (hand tracking / photos)
  * Screen capture  -> no extra permission needed

Start Ollama and pull the model:
  ollama serve
  ollama pull llama3
"@ -ForegroundColor Green


