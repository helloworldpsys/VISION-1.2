"""Configuration loading for Vision.

Every user-configurable value is read from the environment (optionally seeded
from a ``.env`` file) and exposed through the immutable :class:`Config`
dataclass.  Nothing is hard-coded at the call sites any more.

Both the new ``VISION_``-prefixed names and the legacy un-prefixed names from
Vision 1.2 are accepted, e.g. ``VISION_OLLAMA_MODEL`` or ``OLLAMA_MODEL``.
"""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

try:  # optional, keeps the package importable in minimal environments
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - exercised only without python-dotenv
    load_dotenv = None  # type: ignore[assignment]

try:
    from platformdirs import user_data_dir
except ImportError:  # pragma: no cover - fallback for minimal environments
    user_data_dir = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRUTHY = {"1", "true", "yes", "on", "y"}
FALSY = {"0", "false", "no", "off", "n"}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUTHY:
        return True
    if text in FALSY:
        return False
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_path(value: Any, default: Path) -> Path:
    if value in (None, ""):
        return default
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def default_data_dir() -> Path:
    """Return a writable, per-user directory for memory, logs and captures."""
    override = os.environ.get("VISION_DATA_DIR")
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override))).resolve()
    if user_data_dir is not None:
        return Path(user_data_dir("Vision", "VisionProject"))
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Vision"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Vision"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "vision"


def default_cache_dir() -> Path:
    override = os.environ.get("VISION_CACHE_DIR")
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override))).resolve()
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Vision" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Vision"
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "vision"


@dataclass(frozen=True)
class Config:
    """Fully resolved runtime configuration."""

    # Identity / AI
    assistant_name: str = "Vision"
    creator_name: str = "Taha"
    ollama_model: str = "llama3"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_timeout: float = 60.0
    ollama_retries: int = 2

    # Paths
    data_dir: Path = field(default_factory=default_data_dir)
    log_dir: Path | None = None
    memory_db: Path | None = None
    state_file: Path | None = None
    screenshot_dir: Path | None = None
    photo_dir: Path | None = None
    legacy_memory_json: Path | None = None

    # Text to speech
    tts_engine: str = "edge"  # edge | native | none
    edge_voice: str = "en-US-ChristopherNeural"
    edge_rate: str = "-12%"
    edge_pitch: str = "-18Hz"
    edge_volume: str = "+50%"
    play_volume: float = 2.5
    sox_effect: bool = True
    native_voice: str = ""
    native_rate: int = 150

    # Speech to text / microphone
    stt_engine: str = "auto"  # auto | google | vosk | text
    stt_language: str = "en-IN"
    prefer_offline_stt: bool = False
    vosk_model_path: Path | None = None
    microphone_enabled: bool = True
    microphone_device: int | None = None
    calibration_interval: int = 120
    wake_listen_timeout: int = 4
    wake_phrase_time: int = 3
    command_listen_timeout: int = 4
    command_phrase_time: int = 8
    max_audio_failures: int = 3

    # Clap detection
    clap_enabled: bool = True
    clap_threshold: int = 2000
    clap_min_interval: float = 0.1
    clap_max_interval: float = 0.8
    clap_debounce: float = 0.05
    audio_chunk: int = 1024
    audio_rate: int = 44100
    audio_channels: int = 1

    # Interface
    interface_args: tuple[str, ...] = ()
    interface_timeout: float = 10.0

    # Logging
    log_level: str = "INFO"
    log_max_bytes: int = 1_000_000
    log_backups: int = 5

    # Misc
    wake_phrases: tuple[str, ...] = (
        "hey vision",
        "hey visions",
        "a vision",
        "hey vishon",
        "hey vizhan",
    )

    # ------------------------------------------------------------------ paths
    def resolved_paths(self) -> Config:
        """Return a copy with derived path fields filled in."""
        data = Path(self.data_dir)
        return replace(
            self,
            data_dir=data,
            log_dir=self.log_dir or data / "logs",
            memory_db=self.memory_db or data / "memory.db",
            state_file=self.state_file or data / "state.txt",
            screenshot_dir=self.screenshot_dir or data / "screenshots",
            photo_dir=self.photo_dir or data / "photos",
        )

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.log_dir,
            self.screenshot_dir,
            self.photo_dir,
        ):
            if path is not None:
                Path(path).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ load
    @classmethod
    def load(
        cls,
        env: Mapping[str, str] | None = None,
        env_file: str | os.PathLike[str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> Config:
        """Build a config from ``env`` (defaults to ``os.environ``).

        ``.env`` is loaded from the current directory and the project root, but
        never overrides variables that are already set in the process.
        """
        if load_env_file and load_dotenv is not None:
            candidates = [Path.cwd() / ".env", PROJECT_ROOT / ".env"]
            if env_file:
                candidates.insert(0, Path(env_file))
            for candidate in candidates:
                try:
                    if candidate.is_file():
                        load_dotenv(candidate, override=False)
                except OSError:
                    pass
        source = os.environ if env is None else env

        def get(name: str, default: Any = None) -> Any:
            for key in (f"VISION_{name}", name):
                if key in source and source[key] != "":
                    return source[key]
            return default

        data_dir = _as_path(get("DATA_DIR"), default_data_dir())
        default = cls().resolved_paths()
        # Recompute defaults relative to the chosen data dir.
        log_dir = _as_path(get("LOG_DIR"), data_dir / "logs")
        memory_db = _as_path(get("MEMORY_DB"), data_dir / "memory.db")
        state_file = _as_path(get("STATE_FILE"), data_dir / "state.txt")
        screenshot_dir = _as_path(get("SCREENSHOT_DIR"), data_dir / "screenshots")
        photo_dir = _as_path(get("PHOTO_DIR"), data_dir / "photos")

        raw_args = get("INTERFACE_ARGS", "") or ""
        if isinstance(raw_args, str):
            try:
                interface_args = tuple(shlex.split(raw_args))
            except ValueError:
                interface_args = ()
        else:  # pragma: no cover - defensive
            interface_args = tuple(raw_args)

        raw_wake = get("WAKE_PHRASES")
        wake_phrases = (
            tuple(part.strip().lower() for part in str(raw_wake).split(",") if part.strip())
            if raw_wake
            else default.wake_phrases
        )

        legacy = _as_path(get("LEGACY_MEMORY_JSON"), Path.cwd() / "memory.json")
        vosk = get("VOSK_MODEL_PATH")
        device = get("MICROPHONE_DEVICE")
        device_index = _as_int(device, -1) if device not in (None, "") else -1
        microphone_device = device_index if device_index >= 0 else None

        cfg = cls(
            assistant_name=str(get("ASSISTANT_NAME", "Vision")),
            creator_name=str(get("CREATOR_NAME", "Taha")),
            ollama_model=str(get("OLLAMA_MODEL", "llama3")),
            ollama_host=str(get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/"),
            ollama_timeout=_as_float(get("OLLAMA_TIMEOUT"), 60.0),
            ollama_retries=_as_int(get("OLLAMA_RETRIES"), 2),
            data_dir=data_dir,
            log_dir=log_dir,
            memory_db=memory_db,
            state_file=state_file,
            screenshot_dir=screenshot_dir,
            photo_dir=photo_dir,
            legacy_memory_json=legacy,
            tts_engine=str(get("TTS_ENGINE", "edge")).strip().lower(),
            edge_voice=str(get("EDGE_VOICE", "en-US-ChristopherNeural")),
            edge_rate=str(get("EDGE_RATE", "-12%")),
            edge_pitch=str(get("EDGE_PITCH", "-18Hz")),
            edge_volume=str(get("EDGE_VOLUME", "+50%")),
            play_volume=_as_float(get("PLAY_VOLUME"), 2.5),
            sox_effect=_as_bool(get("SOX_EFFECT"), True),
            native_voice=str(get("NATIVE_VOICE", "")),
            native_rate=_as_int(get("NATIVE_RATE"), 150),
            stt_engine=str(get("STT_ENGINE", "auto")).strip().lower(),
            stt_language=str(get("STT_LANGUAGE", "en-IN")),
            prefer_offline_stt=_as_bool(get("PREFER_OFFLINE_STT"), False),
            vosk_model_path=_as_path(vosk, Path("")) if vosk else None,
            microphone_enabled=_as_bool(get("MICROPHONE_ENABLED"), True),
            microphone_device=microphone_device,
            calibration_interval=_as_int(get("CALIBRATION_INTERVAL"), 120),
            wake_listen_timeout=_as_int(get("WAKE_LISTEN_TIMEOUT"), 4),
            wake_phrase_time=_as_int(get("WAKE_PHRASE_TIME"), 3),
            command_listen_timeout=_as_int(get("COMMAND_LISTEN_TIMEOUT"), 4),
            command_phrase_time=_as_int(get("COMMAND_PHRASE_TIME"), 8),
            max_audio_failures=_as_int(get("MAX_AUDIO_FAILURES"), 3),
            clap_enabled=_as_bool(get("CLAP_ENABLED"), True),
            clap_threshold=_as_int(get("CLAP_THRESHOLD"), 2000),
            clap_min_interval=_as_float(get("CLAP_MIN_INTERVAL"), 0.1),
            clap_max_interval=_as_float(get("CLAP_MAX_INTERVAL"), 0.8),
            clap_debounce=_as_float(get("CLAP_DEBOUNCE"), 0.05),
            audio_chunk=_as_int(get("AUDIO_CHUNK"), 1024),
            audio_rate=_as_int(get("AUDIO_RATE"), 44100),
            audio_channels=_as_int(get("AUDIO_CHANNELS"), 1),
            interface_args=interface_args,
            interface_timeout=_as_float(get("INTERFACE_TIMEOUT"), 10.0),
            log_level=str(get("LOG_LEVEL", "INFO")).upper(),
            log_max_bytes=_as_int(get("LOG_MAX_BYTES"), 1_000_000),
            log_backups=_as_int(get("LOG_BACKUPS"), 5),
            wake_phrases=wake_phrases,
        )
        return cfg.resolved_paths()

    def with_overrides(self, **kwargs: Any) -> Config:
        """Convenience helper used by tests and the CLI."""
        return replace(self, **kwargs).resolved_paths()

    def public_dict(self) -> dict[str, Any]:
        """Configuration snapshot safe to log (no secrets are stored here)."""
        data = self.resolved_paths()
        result: dict[str, Any] = {}
        for key, value in data.__dict__.items():
            result[key] = str(value) if isinstance(value, Path) else value
        return result
