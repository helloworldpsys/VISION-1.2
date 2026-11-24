"""Cross-platform operating-system abstraction.

Vision 1.2 called ``afplay``, ``say``, ``open``, ``osascript``, ``pmset`` and
``screencapture`` directly from the assistant.  That made every feature macOS
only.  This module is the single place that knows about the host OS:

* :class:`MacPlatform`   - ``afplay`` / ``say`` / ``open`` / ``osascript`` / ...
* :class:`WindowsPlatform` - PowerShell, ``winsound``, Win32 APIs, ffmpeg
* :class:`LinuxPlatform` - ``paplay`` / ``espeak-ng`` / ``xdg-open`` / ``pactl``

All commands are executed with ``shell=False`` and a timeout.  The subprocess
runner, ``shutil.which`` and the URL opener are injectable so the command
mapping can be unit-tested on any host without touching real hardware.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger("platform")

APP_ALIASES = {
    "youtube": "youtube",
    "youtube music": "youtube",
    "safari": "safari",
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "edge": "edge",
    "microsoft edge": "edge",
    "spotify": "spotify",
    "vscode": "vscode",
    "visual studio code": "vscode",
}

YOUTUBE_URL = "https://youtube.com"


def _hide_window_kwargs() -> dict[str, int]:
    """Do not flash console windows when spawning helpers on Windows."""
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""


def run_command(
    argv: Sequence[str],
    timeout: float = 15.0,
    *,
    capture: bool = True,
) -> CommandResult:
    """Run *argv* without a shell and never raise."""
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=capture,
            text=True,
            timeout=timeout,
            check=False,
            **_hide_window_kwargs(),
        )
        return CommandResult(
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            stdout=(completed.stdout or "").strip() if capture else "",
            stderr=(completed.stderr or "").strip() if capture else "",
        )
    except FileNotFoundError as exc:
        return CommandResult(ok=False, error=f"not found: {exc}")
    except subprocess.TimeoutExpired:
        return CommandResult(ok=False, error=f"timed out after {timeout}s: {argv[0]}")
    except OSError as exc:
        return CommandResult(ok=False, error=str(exc))


def detect_os() -> str:
    """Return ``macos``, ``windows``, ``linux`` or ``unknown``."""
    override = os.environ.get("VISION_OS", "").strip().lower()
    if override in {"macos", "darwin", "mac"}:
        return "macos"
    if override in {"windows", "win", "win32"}:
        return "windows"
    if override in {"linux"}:
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _unescape_powershell(text: str) -> str:
    return text.replace("'", "''")


class PlatformAdapter(ABC):
    """Interface every OS backend implements."""

    os_name = "unknown"

    def __init__(
        self,
        runner: Callable[..., CommandResult] | None = None,
        which: Callable[[str], str | None] | None = None,
        url_opener: Callable[..., bool] | None = None,
    ) -> None:
        self._runner = runner or run_command
        self._which = which or shutil.which
        self._open_url = url_opener or webbrowser.open

    # ------------------------------------------------------------- helpers
    def which(self, name: str) -> str | None:
        try:
            return self._which(name)
        except Exception:  # pragma: no cover - defensive
            return None

    def has(self, name: str) -> bool:
        return self.which(name) is not None

    def _run(
        self,
        argv: Sequence[str],
        timeout: float = 15.0,
        **kwargs: object,
    ) -> CommandResult:
        try:
            result = self._runner(list(argv), timeout=timeout, **kwargs)
        except TypeError:
            try:
                result = self._runner(list(argv), timeout=timeout)
            except TypeError:
                # Allow very small fake runners in tests: runner(argv).
                result = self._runner(list(argv))
        if not isinstance(result, CommandResult):
            result = CommandResult(ok=bool(result))
        if not result.ok:
            logger.debug("command failed: %s (%s)", argv, result.error or result.stderr)
        return result

    def _first(self, names: Sequence[str]) -> str | None:
        for name in names:
            path = self.which(name)
            if path:
                return path
        return None

    def open_url(self, url: str) -> bool:
        try:
            try:
                result = self._open_url(url, 2)
            except TypeError:
                result = self._open_url(url)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("could not open URL %s: %s", url, exc)
            return False
        return bool(result)

    def normalize_app(self, app_name: str) -> str:
        key = str(app_name or "").strip().lower()
        return APP_ALIASES.get(key, key)

    @property
    def desktop_dir(self) -> Path:
        home = Path.home()
        xdg = os.environ.get("XDG_DESKTOP_DIR")
        if xdg:
            return Path(os.path.expandvars(os.path.expanduser(xdg)))
        for candidate in (home / "Desktop", home / "OneDrive" / "Desktop", home / "桌面"):
            if candidate.is_dir():
                return candidate
        return home / "Desktop"

    def search_roots(self) -> list[Path]:
        home = Path.home()
        roots = [
            self.desktop_dir,
            home / "Documents",
            home / "Downloads",
            home / "OneDrive",
        ]
        return [p for p in roots if p.is_dir()]

    # ---------------------------------------------------------- abstract API
    @abstractmethod
    def play_audio_file(self, path: str | Path, volume: float = 1.0) -> bool:
        """Play an audio file synchronously."""

    @abstractmethod
    def speak_native(self, text: str, voice: str = "", rate: int = 150) -> bool:
        """Use the built-in OS voice (offline fallback for edge-tts)."""

    @abstractmethod
    def open_path(self, path: str | Path) -> bool:
        """Open a file or directory in the user's default application."""

    @abstractmethod
    def open_app(self, app_name: str) -> bool:
        """Launch an application by well-known alias."""

    @abstractmethod
    def take_screenshot(self, path: str | Path) -> bool:
        """Capture the full screen to *path* (PNG)."""

    @abstractmethod
    def set_volume(self, percent: int) -> bool:
        """Set absolute output volume (0-100)."""

    @abstractmethod
    def get_volume(self) -> int | None:
        """Return current output volume (0-100), or ``None``."""

    @abstractmethod
    def set_mute(self, muted: bool) -> bool:
        """Mute/unmute the default output device."""

    @abstractmethod
    def get_battery(self) -> str:
        """Human-readable battery status."""

    @abstractmethod
    def find_folder(self, name: str) -> Path | None:
        """Locate a folder by (case-insensitive) name."""

    @abstractmethod
    def convert_audio(self, source: str | Path, target: str | Path) -> bool:
        """Convert an audio file (edge-tts emits MP3) to WAV."""


# ===================================================================== macOS
class MacPlatform(PlatformAdapter):
    os_name = "macos"

    def _osascript(self, script: str) -> CommandResult:
        return self._run(["osascript", "-e", script], timeout=10.0)

    def play_audio_file(self, path: str | Path, volume: float = 1.0) -> bool:
        return self._run(
            ["afplay", "-v", f"{max(0.0, float(volume)):.2f}", str(path)],
            timeout=300.0,
        ).ok

    def speak_native(self, text: str, voice: str = "", rate: int = 150) -> bool:
        argv = ["say"]
        if voice:
            argv += ["-v", voice]
        argv += ["-r", str(int(rate)), str(text)]
        return self._run(argv, timeout=300.0).ok

    def open_path(self, path: str | Path) -> bool:
        return self._run(["open", str(path)], timeout=20.0).ok

    def open_app(self, app_name: str) -> bool:
        app = self.normalize_app(app_name)
        if app == "youtube":
            return self.open_url(YOUTUBE_URL)
        if app == "safari":
            return self._run(["open", "-a", "Safari"]).ok
        if app == "chrome":
            return self._run(["open", "-a", "Google Chrome"]).ok
        if app == "firefox":
            return self._run(["open", "-a", "Firefox"]).ok
        if app == "edge":
            return self._run(["open", "-a", "Microsoft Edge"]).ok
        if app == "spotify":
            return self._run(["open", "-a", "Spotify"]).ok
        if app == "vscode":
            return self._run(["open", "-a", "Visual Studio Code"]).ok
        return bool(app) and self._run(["open", "-a", app]).ok

    def take_screenshot(self, path: str | Path) -> bool:
        return self._run(["screencapture", "-x", str(path)], timeout=30.0).ok

    def get_volume(self) -> int | None:
        result = self._osascript("output volume of (get volume settings)")
        if not result.ok:
            return None
        try:
            return max(0, min(100, int(float(result.stdout))))
        except (TypeError, ValueError):
            return None

    def set_volume(self, percent: int) -> bool:
        target = max(0, min(100, int(percent)))
        result = self._osascript(f"set volume output volume {target}")
        if result.ok and target > 0:
            self._osascript("set volume without output muted")
        return result.ok

    def set_mute(self, muted: bool) -> bool:
        state = "with" if muted else "without"
        return self._osascript(f"set volume {state} output muted").ok

    def get_battery(self) -> str:
        result = self._run(["pmset", "-g", "batt"], timeout=5.0)
        if not result.ok:
            return "I could not read the battery level"
        match = re.search(r"(\d+)%", result.stdout)
        if not match:
            return "I could not read the battery level"
        charging = bool(re.search(r"\b(charging|finishing charge|AC Power)\b", result.stdout))
        if re.search(r"\bdischarging\b", result.stdout):
            charging = False
        return (
            f"Battery is at {match.group(1)} percent and "
            f"{'charging' if charging else 'not charging'}"
        )

    def find_folder(self, name: str) -> Path | None:
        query = f"kMDItemFSName == '*{name}*'c && kMDItemContentType == 'public.folder'"
        result = self._run(["mdfind", query], timeout=15.0)
        if result.ok:
            for line in result.stdout.splitlines():
                candidate = Path(line.strip())
                if candidate.is_dir():
                    return candidate
        return _walk_for_folder(self.search_roots(), name)

    def convert_audio(self, source: str | Path, target: str | Path) -> bool:
        if not self.has("afconvert"):
            return False
        return self._run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@44100", str(source), str(target)],
            timeout=60.0,
        ).ok


# =================================================================== Windows
class WindowsPlatform(PlatformAdapter):
    os_name = "windows"

    def play_audio_file(self, path: str | Path, volume: float = 1.0) -> bool:
        path = Path(path)
        if path.suffix.lower() == ".wav":
            try:
                import winsound

                winsound.PlaySound(str(path), winsound.SND_FILENAME)
                return True
            except Exception as exc:  # pragma: no cover - hardware specific
                logger.debug("winsound playback failed: %s", exc)
        ffplay = self.which("ffplay")
        if ffplay:
            argv = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet"]
            if 0 < volume <= 1.0:
                argv += ["-volume", str(int(volume * 100))]
            argv.append(str(path))
            return self._run(argv, timeout=300.0).ok
        logger.warning(
            "Cannot play %s on Windows without ffmpeg/winsound; install ffmpeg "
            "or let Vision fall back to the native SAPI voice.",
            path.name,
        )
        return False

    def speak_native(self, text: str, voice: str = "", rate: int = 150) -> bool:
        safe = _unescape_powershell(str(text))
        sapi_rate = max(-10, min(10, round((int(rate) - 150) / 15)))
        voice_line = f"$s.SelectVoice('{_unescape_powershell(voice)}'); " if voice else ""
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"{voice_line}$s.Rate = {sapi_rate}; $s.Speak('{safe}');"
        )
        return self._run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=300.0,
        ).ok

    def open_path(self, path: str | Path) -> bool:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        except (AttributeError, OSError) as exc:  # pragma: no cover - Windows only
            logger.warning("could not open path %s: %s", path, exc)
            return False

    def _start(self, target: str) -> bool:
        if not target or not re.fullmatch(r"[\w .+-]+", target):
            logger.warning("Refusing to launch unsafe application target: %r", target)
            return False
        return self._run(["cmd", "/c", "start", "", target], timeout=20.0).ok

    def open_app(self, app_name: str) -> bool:
        app = self.normalize_app(app_name)
        if app == "youtube":
            return self.open_url(YOUTUBE_URL)
        commands = {
            "chrome": "chrome",
            "firefox": "firefox",
            "edge": "msedge",
            "spotify": "spotify",
            "vscode": "code",
            "safari": None,  # Safari does not exist; use the default browser.
        }
        target = commands.get(app, app)
        if target is None:
            return self.open_url("https://www.google.com")
        return bool(target) and self._start(target)

    def take_screenshot(self, path: str | Path) -> bool:
        safe = _unescape_powershell(str(Path(path).resolve()))
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
            f"$bmp.Save('{safe}', [System.Drawing.Imaging.ImageFormat]::Png); "
            "$g.Dispose(); $bmp.Dispose();"
        )
        return self._run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=30.0,
        ).ok

    # -------- Windows volume: pycaw -> nircmd -> media keys ----------------
    @staticmethod
    def _pycaw_endpoint():
        try:
            from comtypes import CLSCTX_ALL  # type: ignore
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return interface.QueryInterface(IAudioEndpointVolume)
        except Exception:
            return None

    def get_volume(self) -> int | None:
        endpoint = self._pycaw_endpoint()
        if endpoint is not None:
            try:
                return round(endpoint.GetMasterVolumeLevelScalar() * 100)
            except Exception as exc:  # pragma: no cover
                logger.debug("pycaw volume read failed: %s", exc)
        return None

    def set_volume(self, percent: int) -> bool:
        target = max(0, min(100, int(percent)))
        endpoint = self._pycaw_endpoint()
        if endpoint is not None:
            try:
                endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
                return True
            except Exception as exc:  # pragma: no cover
                logger.debug("pycaw volume set failed: %s", exc)
        nircmd = self.which("nircmd")
        if nircmd:
            value = round(target / 100.0 * 65535)
            return self._run([nircmd, "setsysvolume", str(value)]).ok
        logger.warning(
            "Absolute volume control needs pycaw or nircmd on Windows; "
            "install pycaw (`pip install pycaw`) or place nircmd.exe on PATH."
        )
        return False

    def set_mute(self, muted: bool) -> bool:
        endpoint = self._pycaw_endpoint()
        if endpoint is not None:
            try:
                endpoint.SetMute(bool(muted), None)
                return True
            except Exception as exc:  # pragma: no cover
                logger.debug("pycaw mute failed: %s", exc)
        nircmd = self.which("nircmd")
        if nircmd:
            return self._run([nircmd, "mutesysvolume", "1" if muted else "0"]).ok
        try:  # Toggle via the system media key as a last resort.
            self._media_key(0xAD)
            return True
        except Exception as exc:  # pragma: no cover - Windows only
            logger.debug("media key mute failed: %s", exc)
            return False

    @staticmethod
    def _media_key(virtual_key: int) -> None:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, 2, 0)

    def get_battery(self) -> str:
        script = (
            "Get-CimInstance Win32_Battery | "
            "Select-Object -First 1 EstimatedChargeRemaining,BatteryStatus | "
            "ConvertTo-Json -Compress"
        )
        result = self._run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=10.0,
        )
        if not result.ok or not result.stdout:
            return "I could not read the battery level"
        import json

        try:
            data = json.loads(result.stdout)
            if isinstance(data, list):
                data = data[0] if data else {}
            percent = data.get("EstimatedChargeRemaining")
            status = int(data.get("BatteryStatus") or 0)
        except (ValueError, TypeError, AttributeError):
            return "I could not read the battery level"
        if percent is None:
            return "I could not read the battery level"
        # 2 = AC, 6/7/8/9 = charging states.
        charging = status in {2, 6, 7, 8, 9}
        return (
            f"Battery is at {int(percent)} percent and "
            f"{'charging' if charging else 'not charging'}"
        )

    def find_folder(self, name: str) -> Path | None:
        return _walk_for_folder(self.search_roots(), name)

    def convert_audio(self, source: str | Path, target: str | Path) -> bool:
        ffmpeg = self.which("ffmpeg")
        if not ffmpeg:
            return False
        return self._run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), str(target)],
            timeout=60.0,
        ).ok


# ===================================================================== Linux
class LinuxPlatform(PlatformAdapter):
    os_name = "linux"

    def play_audio_file(self, path: str | Path, volume: float = 1.0) -> bool:
        players = [
            ("paplay", [str(path)]),
            ("aplay", ["-q", str(path)]),
            ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]),
            ("mpv", ["--no-video", "--really-quiet", str(path)]),
        ]
        for name, args in players:
            binary = self.which(name)
            if binary and self._run([binary, *args], timeout=300.0).ok:
                return True
        return False

    def speak_native(self, text: str, voice: str = "", rate: int = 150) -> bool:
        voices = [voice] if voice else []
        for name in ("espeak-ng", "espeak"):
            binary = self.which(name)
            if binary:
                argv = [binary, "-s", str(max(80, min(450, int(rate))))]
                for candidate in voices:
                    argv += ["-v", candidate]
                argv.append(str(text))
                if self._run(argv, timeout=300.0).ok:
                    return True
        binary = self.which("spd-say")
        if binary:
            return self._run(
                [binary, "-r", str(max(-100, min(100, int(rate) - 150))), str(text)],
                timeout=300.0,
            ).ok
        logger.warning("No TTS engine found; install espeak-ng or spd-say.")
        return False

    def open_path(self, path: str | Path) -> bool:
        binary = self.which("xdg-open")
        if binary:
            return self._run([binary, str(path)], timeout=20.0).ok
        logger.warning("xdg-open not found; install xdg-utils.")
        return False

    def open_app(self, app_name: str) -> bool:
        app = self.normalize_app(app_name)
        if app == "youtube":
            return self.open_url(YOUTUBE_URL)
        if app in {"safari", "edge"}:
            return self.open_url("https://www.google.com")
        commands = {
            "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
            "firefox": ["firefox"],
            "spotify": ["spotify"],
            "vscode": ["code"],
        }
        for name in commands.get(app, [app]):
            binary = self.which(name)
            if binary:
                return self._run([binary], timeout=20.0, capture=False).ok
        return False

    def take_screenshot(self, path: str | Path) -> bool:
        target = str(Path(path).resolve())
        candidates = [
            ("gnome-screenshot", ["-f", target]),
            ("spectacle", ["-b", "-n", "-o", target]),
            ("scrot", [target]),
            ("import", ["-window", "root", target]),
        ]
        for name, args in candidates:
            binary = self.which(name)
            if binary and self._run([binary, *args], timeout=30.0).ok:
                return True
        logger.warning(
            "No screenshot tool found; install gnome-screenshot, spectacle, "
            "scrot or imagemagick."
        )
        return False

    # -------- audio: PulseAudio/PipeWire -> ALSA --------------------------
    def _pactl(self) -> str | None:
        return self.which("pactl")

    def _amixer(self) -> str | None:
        return self.which("amixer")

    def get_volume(self) -> int | None:
        pactl = self._pactl()
        if pactl:
            result = self._run([pactl, "get-sink-volume", "@DEFAULT_SINK@"])
            if result.ok:
                match = re.search(r"(\d+)%", result.stdout)
                if match:
                    return max(0, min(100, int(match.group(1))))
        amixer = self._amixer()
        if amixer:
            result = self._run([amixer, "get", "Master"])
            if result.ok:
                values = re.findall(r"\[(\d+)%\]", result.stdout)
                if values:
                    return max(0, min(100, int(values[0])))
        return None

    def set_volume(self, percent: int) -> bool:
        target = max(0, min(100, int(percent)))
        pactl = self._pactl()
        if pactl:
            return self._run([pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{target}%"]).ok
        amixer = self._amixer()
        if amixer:
            return self._run([amixer, "set", "Master", f"{target}%"]).ok
        logger.warning("No volume mixer found; install pulseaudio-utils or alsa-utils.")
        return False

    def set_mute(self, muted: bool) -> bool:
        pactl = self._pactl()
        if pactl:
            return self._run([pactl, "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"]).ok
        amixer = self._amixer()
        if amixer:
            return self._run([amixer, "set", "Master", "mute" if muted else "unmute"]).ok
        return False

    def get_battery(self) -> str:
        supplies = Path("/sys/class/power_supply")
        try:
            batteries = [p for p in supplies.iterdir() if p.name.startswith("BAT")]
        except OSError:
            return "I could not read the battery level"
        if not batteries:
            return "This device has no battery"
        try:
            bat = batteries[0]
            percent = int((bat / "capacity").read_text(encoding="utf-8").strip())
            status = (bat / "status").read_text(encoding="utf-8").strip().lower()
        except (OSError, ValueError):
            return "I could not read the battery level"
        charging = status in {"charging", "full"}
        return (
            f"Battery is at {percent} percent and " f"{'charging' if charging else 'not charging'}"
        )

    def find_folder(self, name: str) -> Path | None:
        locate = self.which("locate")
        if locate:
            result = self._run([locate, "-b", name], timeout=10.0)
            if result.ok:
                for line in result.stdout.splitlines():
                    candidate = Path(line.strip())
                    if candidate.is_dir() and name.lower() in candidate.name.lower():
                        return candidate
        return _walk_for_folder(self.search_roots(), name)

    def convert_audio(self, source: str | Path, target: str | Path) -> bool:
        ffmpeg = self.which("ffmpeg")
        if not ffmpeg:
            return False
        return self._run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), str(target)],
            timeout=60.0,
        ).ok


# ================================================================== factory
class UnsupportedPlatform(PlatformAdapter):
    """Fallback used on platforms we have no backend for (BSD, etc.)."""

    os_name = "unknown"

    def play_audio_file(self, path: str | Path, volume: float = 1.0) -> bool:
        return False

    def speak_native(self, text: str, voice: str = "", rate: int = 150) -> bool:
        return False

    def open_path(self, path: str | Path) -> bool:
        return self.open_url(Path(path).as_uri())

    def open_app(self, app_name: str) -> bool:
        return False

    def take_screenshot(self, path: str | Path) -> bool:
        return False

    def set_volume(self, percent: int) -> bool:
        return False

    def get_volume(self) -> int | None:
        return None

    def set_mute(self, muted: bool) -> bool:
        return False

    def get_battery(self) -> str:
        return "Battery status is not supported on this platform"

    def find_folder(self, name: str) -> Path | None:
        return _walk_for_folder(self.search_roots(), name)

    def convert_audio(self, source: str | Path, target: str | Path) -> bool:
        return False


def create_platform(os_name: str | None = None, **kwargs) -> PlatformAdapter:
    """Create a platform adapter; injectable for tests."""
    name = (os_name or detect_os()).lower()
    if name in {"macos", "darwin", "mac"}:
        return MacPlatform(**kwargs)
    if name in {"windows", "win32", "win"}:
        return WindowsPlatform(**kwargs)
    if name == "linux":
        return LinuxPlatform(**kwargs)
    return UnsupportedPlatform(**kwargs)


_PLATFORM: PlatformAdapter | None = None


def get_platform() -> PlatformAdapter:
    """Return the process-wide platform adapter instance."""
    global _PLATFORM
    if _PLATFORM is None:
        _PLATFORM = create_platform()
        logger.info("Platform backend: %s", _PLATFORM.os_name)
    return _PLATFORM


def reset_platform_cache() -> None:
    """Testing helper."""
    global _PLATFORM
    _PLATFORM = None


def _walk_for_folder(roots: Sequence[Path], name: str, max_depth: int = 4) -> Path | None:
    """Find a folder by name without shelling out to ``find``/``dir``."""
    needle = str(name or "").strip().lower()
    if not needle:
        return None
    skip = {"node_modules", "__pycache__", ".git", ".venv", "venv", "AppData"}
    for root in roots:
        root = Path(root)
        base_depth = len(root.parts)
        try:
            for current, dirs, _files in os.walk(root, topdown=True):
                current_path = Path(current)
                if len(current_path.parts) - base_depth > max_depth:
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if d not in skip]
                for directory in dirs:
                    if directory.lower() == needle:
                        return current_path / directory
        except OSError:
            continue
    return None
