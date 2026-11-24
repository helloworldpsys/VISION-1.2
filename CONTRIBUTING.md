# Contributing to Vision

Thanks for helping make Vision better. This guide covers the development
workflow, the project’s design rules and what reviewers look for.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Bug reports** — include OS, Python version, `python vision.py --diagnose`
  output, steps to reproduce and the relevant tail of `logs/vision.log`.
- **Platform fixes** — Windows/Linux behaviour is the most valuable area right
  now: audio, volume, screenshots and app launching.
- **Offline support** — Vosk model ergonomics, native TTS voices, packaging.
- **Tests and docs** — parser phrases, edge cases and clearer guides.

## Development setup

```bash
git clone https://github.com/helloworldpsys/VISION-1.2.git
cd VISION-1.2
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Python **3.10–3.12** is required. The unit tests do not need a microphone,
camera, OpenCV, MediaPipe or Ollama:

```bash
pytest
pytest --cov=vision
ruff check .
black --check .
```

Before opening a pull request, run all four commands. CI runs the same checks on
Linux, Windows and macOS with Python 3.10, 3.11 and 3.12.

## Project layout

| Module | Responsibility |
|---|---|
| `vision/config.py` | environment/.env → immutable `Config` |
| `vision/platform_utils.py` | the only OS-specific code |
| `vision/parser.py` | pure command grammar (no side effects) |
| `vision/actions.py` | side effects for each intent |
| `vision/audio.py` | capture backends, STT engines, clap detection |
| `vision/tts.py` | edge-tts with native fallback |
| `vision/memory.py` | SQLite persistence and JSON migration |
| `vision/llm.py` | Ollama HTTP client |
| `vision/ui.py` / `interface_ui.py` | UI process and hologram rendering |
| `vision/app.py` | wiring and main loops |

## Design rules

1. **Keep imports light.** Never import OpenCV, MediaPipe, PyAudio, Vosk or
   edge-tts at package import time. Put them inside the function/class that
   uses them. `pytest` must stay hardware-free.
2. **Separate parsing from acting.** New commands return an `Intent` from
   `parser.py`; `actions.py` performs the effect. Parser changes require parser
   tests.
3. **Never use a shell.** Pass argument lists to `subprocess.run(...,
   shell=False)` with a timeout. Do not interpolate user text into a command
   string. Escape PowerShell arguments with `_unescape_powershell`.
4. **Degrade, never crash.** Catch errors at hardware/network/file boundaries,
   log them with `get_logger`, and use the documented fallback (sounddevice,
   typed input, native TTS, Vosk, “AI is not responding”).
5. **One platform seam.** OS-specific calls belong in `platform_utils.py`; add
   implementations for all three backends and a test with the injected runner.
6. **No secrets in code.** Configuration goes through `Config` and `.env`.
   `.env`, databases, logs and captures are git-ignored.

## Adding a command

1. `vision/parser.py`: add keywords and return
   `Intent("my_intent", {"arg": value})`.
2. `vision/actions.py`: add `_do_my_intent(self, args, original)`; speak the
   reply and return it.
3. `tests/test_parser.py`: add at least one English and one Hinglish phrase.
4. If it touches the filesystem, sanitise names with `safe_filename`.

Example:

```python
# parser.py
if has_any(cmd, ["weather"]):
    return Intent("weather", {"city": strip_words(cmd, ["weather", "in"])})

# actions.py
def _do_weather(self, args, _original):
    city = str(args.get("city", "")).strip()
    reply = f"I cannot check the weather offline yet, Sir ({city})."
    self.speaker.speak(reply)
    return reply
```

## Adding an OS command

Add the abstract method to `PlatformAdapter`, then implement it in
`MacPlatform`, `WindowsPlatform` and `LinuxPlatform`. Return `False` (and log a
helpful hint) when the required tool is missing. Add a mapping test using
`RecordingRunner` — tests must never run real commands:

```python
def test_macos_open_app():
    platform, runner = mac()
    assert platform.open_app("chrome") is True
    assert runner.calls[-1] == ["open", "-a", "Google Chrome"]
```

## Testing guidelines

- Put tests in `tests/test_<module>.py`.
- Use `tmp_path` for databases and files; never write into the repository.
- Inject `urlopen`, `runner`, `which` and `url_opener` rather than monkeypatching
  the network or launching processes.
- Prefer parametrised cases for language variants.
- A bug fix should include a regression test that fails before the fix.

## Pull request checklist

- [ ] `pytest` passes locally.
- [ ] `ruff check .` and `black --check .` pass.
- [ ] New behaviour has tests.
- [ ] New configuration is documented in `.env.example` and the README table.
- [ ] Logs replace `print` for diagnostics.
- [ ] Cross-platform impact considered (macOS/Windows/Linux).
- [ ] No secrets, personal data, databases, logs or captures are committed.
- [ ] The change is focused; unrelated refactors go in a separate PR.

## Commit messages

Use a short imperative subject and explain the *why* in the body:

```
audio: fall back to sounddevice when PyAudio is unavailable

PyAudio wheels are unavailable for some Python builds, which previously
prevented Vision from starting at all. Capture now tries sounddevice and
finally typed commands.
```

## Reporting security issues

Please do not open a public issue for a vulnerability. Email the maintainer
listed in the repository profile with reproduction details and affected
versions. We aim to acknowledge within 72 hours.

## License

By contributing, you agree that your contributions are licensed under the
project’s MIT License.
