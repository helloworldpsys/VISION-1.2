# Vision — a cross-platform voice assistant with a holographic interface

Clap twice (or say **“Hey Vision”**) and an animated holographic interface opens.
It stays blue while idle and turns **red while Vision is speaking**. Talk to it
in English, Hindi or Hinglish. Vision answers anything else through a local LLM
running in [Ollama](https://ollama.com) — no API key required.

> **Vision 2.0 is a ground-up hardening of Vision 1.2.** The assistant is now a
> Python package, runs on **macOS, Windows and Linux**, survives missing
> microphones and offline networks, stores memory in **SQLite**, and ships with
> **120+ unit tests**, linting and a CI workflow.

---

## Highlights

| Area | Vision 1.2 | Vision 2.0 |
|---|---|---|
| Platforms | macOS only (`say`, `afplay`, `osascript`, `screencapture`) | macOS, Windows, Linux via `vision/platform_utils.py` |
| Structure | two 700–1,100-line scripts | `vision/` package with one concern per module |
| Config | edit constants in `vision.py` | `.env` / environment variables, `.env.example` |
| Memory | rewritten `memory.json` | SQLite (WAL) with JSON migration |
| Microphone | PyAudio or crash | PyAudio → sounddevice → typed commands |
| Speech-to-text | Google only (online) | Google + offline Vosk fallback |
| Errors | `print(...)` to a scrolling terminal | rotating `vision.log` + graceful degradation |
| Tests | none | parser, memory, platform, config, state, LLM, actions |
| Docs | setup guide | setup + developer guide + architecture + contributing |

## Features

- **Activation:** double clap, or the wake phrase “Hey Vision”.
- **Holographic UI:** animated OpenCV hologram; optional MediaPipe hand tracking
  (one hand rotates, a two-hand pinch zooms). Mouse and keyboard controls work
  without a camera.
- **Commands:** open apps/sites, search Google/YouTube, play a song, take a
  screenshot or photo, create/open folders, volume, battery, notes, memory,
  interface controls, sleep and shutdown. English and Hinglish are supported.
- **Local AI:** any unrecognised request is answered by Ollama.
- **Natural voice:** `edge-tts` neural voice with an automatic native fallback
  (`say` / SAPI / `espeak-ng`).
- **Privacy:** memory, screenshots and photos stay on your machine. No telemetry.

---

## Requirements

- **Python 3.10, 3.11 or 3.12** (MediaPipe does not support 3.13+ yet).
- A microphone; a camera is optional (hand tracking and photos).
- [Ollama](https://ollama.com/download) with a model pulled (`ollama pull llama3`).
- Optional system tools: `ffmpeg` (MP3 playback on Windows, audio conversion),
  `sox` (metallic voice effect), `espeak-ng` (Linux native TTS).

## Quick start

### Automated setup (recommended)

**macOS / Linux**

```bash
git clone https://github.com/helloworldpsys/VISION-1.2.git
cd VISION-1.2
bash setup.sh
source .venv/bin/activate
python vision.py
```

The script installs PortAudio, ffmpeg and sox (via Homebrew / apt / dnf / pacman),
creates `.venv`, installs the pinned requirements and copies `.env.example`.

**Windows (PowerShell)**

```powershell
git clone https://github.com/helloworldpsys/VISION-1.2.git
cd VISION-1.2
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\.venv\Scripts\Activate.ps1
python vision.py
```

The script finds Python 3.10–3.12, installs the wheels, offers to install ffmpeg
through `winget`, and installs `pycaw` for absolute volume control.

### Manual setup

```bash
# 1. System libraries
# macOS
brew install portaudio sox ffmpeg
# Debian / Ubuntu
sudo apt install portaudio19-dev python3-dev libasound2-dev ffmpeg sox espeak-ng
# Fedora
sudo dnf install portaudio-devel alsa-lib-devel ffmpeg sox espeak-ng
# Windows: ffmpeg from https://www.gyan.dev/ffmpeg/builds/ (add it to PATH)

# 2. Python environment
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env               # edit CREATOR_NAME, OLLAMA_MODEL, ...

# 4. Ollama
ollama serve
ollama pull llama3

# 5. Run
python vision.py
```

### Run modes

```bash
python vision.py                  # voice assistant (or `vision` after pip install)
python -m vision                 # module entry point
python vision.py --text           # typed commands, no microphone
python vision.py --diagnose       # print platform/config/capability report
python vision.py --no-interface   # voice only, no OpenCV window
python vision.py --test-interface # UI only, press Enter to close
python interface.py --sd          # standalone UI, 720p
python interface.py --hd          # standalone UI, 1080p
```

### OS permissions

**macOS** — *System Settings → Privacy & Security*: grant **Microphone**,
**Camera**, **Accessibility/Automation** (volume) and **Screen Recording**
(screenshots) to the terminal/IDE you launch Vision from, then fully restart it.

**Windows** — *Settings → Privacy & security*: allow desktop apps to use the
**Microphone** and **Camera**. Screenshots use the built-in .NET API and need no
extra permission.

**Linux** — make sure your user is in the `audio` group and PulseAudio/PipeWire
is running. Install `gnome-screenshot`, `spectacle`, `scrot` or ImageMagick
(`import`) for screenshots, and `pulseaudio-utils`/`alsa-utils` for volume.

## Example commands

| Say | What happens |
|---|---|
| “Open YouTube” / “youtube kholo” | opens YouTube |
| “Play Believer” / “believer gana sunao” | opens YouTube results |
| “Search Python tutorials on Google” | Google search |
| “Take a screenshot” | saves to the data directory and opens it |
| “Take a photo” / “selfie” | saves a webcam frame |
| “Create a folder named projects” | creates it on the Desktop |
| “Volume 40” / “increase volume” / “mute” | controls system volume |
| “Battery” | reads battery status |
| “My name is Alex” / “What is my name” | memory |
| “Remember that my exam is on Friday” | saves a note |
| “Close interface” / “Open interface” | controls the UI window |
| “Go to sleep” | stops listening until “Hey Vision” |
| “Stop Vision” | shuts down cleanly |
| anything else | answered by Ollama |

## Configuration

All settings are environment variables, optionally loaded from `.env`. Both
`VISION_FOO` and the legacy un-prefixed `FOO` forms are accepted. See
[`.env.example`](.env.example) for the full, commented list.

| Variable | Default | Purpose |
|---|---|---|
| `CREATOR_NAME` | `Taha` | name Vision says it was created by |
| `OLLAMA_MODEL` | `llama3` | any model pulled locally |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama endpoint |
| `TTS_ENGINE` | `edge` | `edge`, `native` or `none` |
| `EDGE_VOICE` | `en-US-ChristopherNeural` | neural voice |
| `STT_ENGINE` | `auto` | `auto`, `google`, `vosk` or `text` |
| `PREFER_OFFLINE_STT` | `false` | try Vosk before Google |
| `VOSK_MODEL_PATH` | *(empty)* | extracted Vosk model directory |
| `CLAP_THRESHOLD` | `2000` | lower if claps are missed, raise if self-triggering |
| `CLAP_ENABLED` | `true` | disable double-clap activation |
| `WAKE_PHRASES` | `hey vision,...` | comma-separated wake phrases |
| `INTERFACE_ARGS` | *(empty)* | e.g. `--hd` |
| `DATA_DIR` | per-OS user data dir | memory, logs, captures |
| `LOG_LEVEL` | `INFO` | `DEBUG` for troubleshooting |

### Where data lives

| OS | Directory |
|---|---|
| Windows | `%LOCALAPPDATA%\Vision` |
| macOS | `~/Library/Application Support/Vision` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/vision` |

`memory.db`, `state.txt`, `logs/vision.log`, `screenshots/` and `photos/` are
created there. An existing Vision 1.2 `memory.json` is imported once and renamed
to `memory.json.migrated`.

### Offline mode

Google’s free STT and `edge-tts` need internet. For a fully offline setup:

1. Download and extract a Vosk model, e.g.
   [vosk-model-small-en-us-0.15](https://alphacephei.com/vosk/models).
2. Set `VOSK_MODEL_PATH=/path/to/vosk-model-small-en-us-0.15` and
   `PREFER_OFFLINE_STT=true` (or `STT_ENGINE=vosk`).
3. Set `TTS_ENGINE=native` to use the OS voice instead of Microsoft’s service.

## Project structure

```
vision/
├── __init__.py          # version only; no heavy imports
├── __main__.py          # python -m vision
├── config.py            # .env + environment -> immutable Config
├── logging_setup.py     # rotating vision.log + console
├── platform_utils.py    # macOS / Windows / Linux command backends
├── state.py             # atomic speaking-state file shared with the UI
├── audio.py             # PyAudio/sounddevice capture, Google/Vosk STT, clap
├── tts.py               # edge-tts -> native fallback
├── memory.py            # SQLite memory + JSON migration
├── llm.py               # Ollama HTTP client (timeouts, retries)
├── parser.py            # pure intent grammar (unit-tested)
├── actions.py           # side effects for each intent
├── ui.py                # launches the UI process
├── interface_ui.py      # OpenCV hologram + MediaPipe hand tracking
└── app.py               # wiring and main loops
vision.py                # backwards-compatible entry point
interface.py             # backwards-compatible UI entry point
tests/                   # pytest suite (no hardware required)
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full component map,
thread/process model, SQLite schema and failure-handling matrix.

```mermaid
flowchart LR
    subgraph Main["Main process (voice loop)"]
        MIC[Microphone] --> STT[SpeechEngine<br/>PyAudio / sounddevice]
        STT --> PARSER[Parser<br/>rules + Hinglish]
        PARSER --> ACTIONS[ActionExecutor]
        ACTIONS --> LLM[OllamaClient]
        ACTIONS --> MEM[(SQLite memory)]
        ACTIONS --> TTS[Speaker<br/>edge-tts / native]
        ACTIONS --> PLAT[PlatformAdapter<br/>macOS / Windows / Linux]
        CLAP[ClapDetector thread] --> ACTIONS
        TTS -. atomic state.txt .-> UI
        UICTRL[InterfaceController] -. spawns .-> UI
    end
    subgraph Child["UI process (never blocks the voice loop)"]
        UI[OpenCV hologram 45 fps]
        UI --> MEDIA[MediaPipe worker thread]
        UI --> STATE[state.txt poller]
    end
    PLAT --> OS[Apps, volume, screenshots,<br/>folders, battery, TTS]
```

**Why two processes?** OpenCV’s HighGUI loop must own the main thread on macOS,
and MediaPipe model loading can take seconds. Running the UI as a child process
means a UI crash or a stalled model never freezes speech recognition, and the
only cross-process contract is one atomic text file (`state.txt`).

**Why rule-based parsing?** Voice commands must work offline and instantly.
The parser is deterministic and covered by tests; free-form language goes to the
local LLM only after the rules decline.

## Developer guide

### Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

The test suite intentionally needs **no hardware and no AI packages**:

```bash
pytest                    # 120+ tests, <1 s
pytest --cov=vision       # coverage report
ruff check .              # lint
black --check .           # formatting
```

### Design rules

1. **Import light.** `import vision` must never import OpenCV, MediaPipe,
   PyAudio or Vosk. Heavy imports live inside the methods that need them.
2. **Parse, then act.** `vision/parser.py` is pure; `vision/actions.py` performs
   side effects. New commands get a parser test and an action test.
3. **No shell.** Commands are argument lists passed to `subprocess.run` with
   `shell=False` and a timeout. Never concatenate user text into a shell string.
4. **Fail soft.** Hardware, network and file errors are logged and degrade to a
   supported fallback; they must not crash the assistant.
5. **One platform seam.** OS-specific behaviour belongs in
   `vision/platform_utils.py`, never in actions or the UI.

### Adding a command

1. Add keywords/pattern matching in `vision/parser.py` and return an
   `Intent("my_command", {...})`.
2. Add `_do_my_command()` in `vision/actions.py`; speak the reply and return it.
3. Add cases to `tests/test_parser.py` (and an action test if it touches files).

### Adding an OS command

Add a method to `PlatformAdapter` and implement it in `MacPlatform`,
`WindowsPlatform` and `LinuxPlatform` (or raise/return `False` with a helpful
warning). Then add a mapping test in `tests/test_platform_utils.py` using the
injected recording runner — never execute real commands in tests.

### Logging and diagnostics

Logs go to `<DATA_DIR>/logs/vision.log` (1 MB × 5 rotations). Use
`get_logger("module")`; never `print` for diagnostics. Run
`python vision.py --diagnose` to print resolved configuration, platform
capabilities and Ollama availability.

## Troubleshooting

| Problem | Fix |
|---|---|
| `PyAudio` will not install | Install PortAudio first: `brew install portaudio` / `sudo apt install portaudio19-dev`. Vision automatically falls back to `sounddevice`, then to typed commands. |
| No microphone found | Check OS privacy permissions, close Zoom/Teams, run `python vision.py --diagnose`, or use `--text`. |
| Clap does not trigger | Lower `CLAP_THRESHOLD` (e.g. 1200); disable `CLAP_ENABLED` and use the wake phrase. |
| Camera not found | Close other camera apps, grant camera permission, restart the terminal. Hand tracking is optional. |
| Hand model download fails | Download `hand_landmarker.task` manually and put it in the cache directory printed by the error, or next to `vision/interface_ui.py`. |
| “AI is not responding” | `ollama serve`, then `ollama list`; check `OLLAMA_HOST`/`OLLAMA_MODEL`. |
| Voice is robotic/offline | `edge-tts` needs internet and falls back to the native voice. Set `TTS_ENGINE=native` to force offline. |
| Windows volume does nothing | `pip install "pycaw>=20240210"` or put `nircmd.exe` on `PATH`. |
| Linux volume/screenshots fail | Install `pulseaudio-utils`/`alsa-utils` and a screenshot tool. |
| UI window is black / no window | Ensure a desktop session (not SSH), install `opencv-python`, try `python vision.py --test-interface`. |

## Security and privacy

- **No shell injection:** every command is an argv list with `shell=False`.
- **Folder names are sanitised** (path traversal and Windows reserved names).
- **Secrets stay in `.env`** (git-ignored); no keys are hard-coded.
- **Cloud calls are explicit:** Google STT receives audio; edge-tts receives the
  reply text. Use Vosk + native TTS for a fully offline setup.
- **Local data only:** SQLite memory, logs and captures never leave the machine.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Bug reports should include your OS,
Python version, the `--diagnose` output and the tail of `vision.log`.

## License

MIT — see [LICENSE](LICENSE).
