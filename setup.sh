#!/usr/bin/env bash
# Vision 2.0 bootstrap for macOS and Linux.
# Installs system audio libraries, creates .venv, installs pinned Python
# dependencies and copies .env.example -> .env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

say() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warning] %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- Python 3.10-3.12
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    case "$version" in
      3.10|3.11|3.12) PYTHON="$candidate"; break ;;
    esac
  fi
done
if [ -z "$PYTHON" ]; then
  die "Python 3.10, 3.11 or 3.12 was not found. MediaPipe does not support 3.13+ yet.
  macOS: brew install python@3.12
  Ubuntu: sudo apt install python3.12 python3.12-venv"
fi
say "Using $PYTHON ($("$PYTHON" --version 2>&1))"

# ------------------------------------------------------------ system packages
OS="$(uname -s)"
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

install_macos() {
  command -v brew >/dev/null 2>&1 || die "Homebrew is required: https://brew.sh"
  say "Installing PortAudio, sox and ffmpeg with Homebrew..."
  brew install portaudio sox ffmpeg || warn "brew reported an error; continuing."
}

install_linux() {
  say "Installing PortAudio, ALSA headers, ffmpeg, sox and espeak-ng..."
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y
    $SUDO apt-get install -y portaudio19-dev python3-dev libasound2-dev ffmpeg sox espeak-ng
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y portaudio-devel alsa-lib-devel ffmpeg sox espeak-ng
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -Sy --needed --noconfirm portaudio alsa-lib ffmpeg sox espeak-ng
  elif command -v zypper >/dev/null 2>&1; then
    $SUDO zypper install -y portaudio-devel alsa-devel ffmpeg sox espeak-ng
  else
    warn "Unknown package manager. Install portaudio, ffmpeg, sox and espeak-ng manually."
  fi
}

case "$OS" in
  Darwin) install_macos ;;
  Linux) install_linux ;;
  *)
    if [[ "$OS" == MINGW* || "$OS" == MSYS* || "$OS" == CYGWIN* ]]; then
      die "Use setup.ps1 from PowerShell on Windows."
    fi
    warn "Unsupported OS '$OS'; skipping system package installation."
    ;;
esac

# ------------------------------------------------------------------- venv
if [ ! -d .venv ]; then
  say "Creating .venv..."
  "$PYTHON" -m venv .venv
fi
VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || die "Virtual environment looks broken; delete .venv and re-run."

say "Installing pinned Python dependencies..."
"$VENV_PY" -m pip install --upgrade pip setuptools wheel
"$VENV_PY" -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  say "Created .env from .env.example - edit it to set CREATOR_NAME, OLLAMA_MODEL, etc."
fi

say "Running diagnostics..."
"$VENV_PY" -m vision --diagnose || warn "Diagnostics reported a problem; see the output above."

cat <<'EOF'

Vision is installed.

  Activate the environment:  source .venv/bin/activate
  Configure:                 python -m vision --setup
  Check capabilities:        python -m vision --doctor
  Start the assistant:       python -m vision
  Typed mode (no mic):       python -m vision --text
  Interface only:            python interface.py [--sd|--hd]
  Tests:                     python -m pytest
  Lint/format:               ruff check . && black --check .

Make sure Ollama is running and the model is pulled:
  ollama serve
  ollama pull llama3
EOF
