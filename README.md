# Vision – Voice Assistant with a Holographic Interface (Windows)

Windows port of Vision. Clap twice (or say **"Hey Vision"**) and an animated hologram opens.
It is **blue while idle** and **red while Vision speaks**. English, Hindi and Hinglish work.

## Features
- Wake: double clap or "Hey Vision"
- Hologram window (`interface.py`) with mouse control and optional webcam hand control
- Commands: open YouTube/Chrome/Edge/Notepad/Calculator..., Google/YouTube search, play a song,
  screenshot, photo, create/open Desktop folder, volume, battery, time/date
- Memory: your name, notes, recent conversations (`memory.json`)
- AI chat through a local LLM (Ollama) – no API key
- Voice: `edge-tts` neural voice, falls back to the built-in Windows voice (offline)

## Setup
1. Install **Python 3.10 – 3.12** from python.org (tick "Add Python to PATH").
2. Open PowerShell in this folder:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   (If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`)
3. Install [Ollama for Windows](https://ollama.com/download), then:
   ```powershell
   ollama pull llama3
   ```
4. Windows Settings → Privacy & security → **Microphone** (and **Camera**) → allow desktop apps.
5. Run: `python vision.py`

Test only the hologram: `python interface.py` (`--sd` lighter, `--hd` Full HD, `--hands` webcam control).

## Example commands
| Say | What happens |
|---|---|
| "Open YouTube" / "youtube kholo" | opens YouTube |
| "Play Believer" / "believer gana sunao" | YouTube results |
| "Search Python tutorials on Google" | Google search |
| "Open Chrome" / "open notepad" | launches the app |
| "Take a screenshot" / "Take a photo" | saved in `screenshots/` / `photos/` |
| "Create a folder named projects" | creates it on your Desktop |
| "Volume 40" / "increase volume" / "mute" | volume control |
| "Battery" | battery status |
| "My name is Alex" / "What is my name" | memory |
| "Remember that my exam is on Friday" | saves a note |
| "Close interface" / "Open interface" | controls the hologram |
| "Go to sleep" | waits for "Hey Vision" |
| "Stop Vision" | shuts down |
| anything else | answered by the local AI |

## Hologram controls
Mouse drag = rotate · scroll or `+`/`-` = zoom · `[` `]` = glow · `R` reset · `F` fullscreen · `Q`/`Esc` quit.
With `--hands`: one hand rotates, two hands apart/together zoom.
> Hand tracking keeps the webcam busy, so the "take a photo" command won't work while `--hands` is on.
> To use it, put `INTERFACE_ARGS = ["--hands"]` at the top of `vision.py`.

## Configuration (top of `vision.py`)
`CREATOR_NAME`, `EDGE_VOICE`/`EDGE_RATE`/`EDGE_PITCH`, `CLAP_THRESHOLD`, `OLLAMA_MODEL`, `INTERFACE_ARGS`.

## Troubleshooting
- **PyAudio won't install:** make sure Python is 3.10–3.12 (wheels exist), then `pip install PyAudio` again.
- **Claps not detected / triggers by itself:** lower / raise `CLAP_THRESHOLD`.
- **"AI is not responding":** start Ollama and check `ollama list`.
- **Voice sounds robotic:** `edge-tts` needs internet; offline it uses the Windows voice.
- **Speech recognition fails:** it uses Google's free web service, so it needs internet.
- **Volume command fails:** `pip install --upgrade pycaw comtypes`.
- **Camera not found:** close Zoom/Teams/Camera app and check Windows camera privacy settings.

## License
MIT
