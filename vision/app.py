"""Application wiring and main loops."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections.abc import Sequence
from datetime import datetime

from . import __version__
from .actions import ActionExecutor, ShutdownRequested, SleepRequested
from .audio import ClapDetector, SpeechEngine, TextOnlySpeech
from .config import Config
from .llm import OllamaClient
from .logging_setup import get_logger, setup_logging
from .memory import MemoryStore, MemoryStoreError
from .parser import Intent, detect_intent, is_wake_phrase, prepare_command
from .platform_utils import create_platform
from .state import SpeakingState
from .tts import Speaker
from .ui import InterfaceController, NullInterface

logger = get_logger("app")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vision",
        description="Vision - a cross-platform voice assistant with a holographic interface.",
    )
    parser.add_argument("--version", action="version", version=f"Vision {__version__}")
    parser.add_argument("--env-file", help="Path to a .env file with configuration.")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Skip the microphone and accept typed commands (also used automatically "
        "when no audio backend is available).",
    )
    parser.add_argument("--no-mic", action="store_true", help="Disable microphone capture.")
    parser.add_argument("--no-clap", action="store_true", help="Disable double-clap activation.")
    parser.add_argument("--no-interface", action="store_true", help="Do not open the OpenCV UI.")
    parser.add_argument(
        "--test-interface",
        action="store_true",
        help="Open only the holographic interface; press Enter or Ctrl+C to stop.",
    )
    parser.add_argument("--log-level", help="Override LOG_LEVEL (DEBUG, INFO, WARNING, ERROR).")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print platform/configuration diagnostics and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load(env_file=args.env_file)
    if args.log_level:
        config = config.with_overrides(log_level=args.log_level.upper())
    config.ensure_directories()
    setup_logging(
        config.log_dir or config.data_dir / "logs",
        level=config.log_level,
        max_bytes=config.log_max_bytes,
        backups=config.log_backups,
    )

    platform = create_platform()
    logger.info("Vision %s starting on %s", __version__, platform.os_name)
    logger.info("Data directory: %s", config.data_dir)

    if args.diagnose:
        return _diagnose(config, platform)

    if args.test_interface:
        return _test_interface(config)

    memory = _open_memory(config)
    state = SpeakingState(config.state_file or config.data_dir / "state.txt")
    speaker = Speaker(config, platform, state)
    llm = OllamaClient(config, memory)
    ui = NullInterface() if args.no_interface else InterfaceController(config)
    if isinstance(ui, InterfaceController):
        logger.info("Interface: %s", "process launcher")
    speech = _build_speech(config, force_text=args.text or args.no_mic)
    executor = ActionExecutor(config, platform, memory, speaker, llm, ui, speech)
    detector = ClapDetector(config) if (config.clap_enabled and not args.no_clap) else None

    try:
        if speech.degraded:
            if args.text or args.no_mic:
                logger.info("Starting in typed-command mode.")
            else:
                logger.warning("Microphone unavailable - starting in typed-command mode.")
            return _text_loop(executor, config)
        return _voice_loop(executor, speech, speaker, ui, detector, config)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        return 0
    finally:
        state.set_idle()
        if detector is not None:
            detector.stop()
        if isinstance(ui, InterfaceController):
            ui.close()
        speech.close()
        memory.close()
        logger.info("Vision stopped.")


# --------------------------------------------------------------------- setup
def _open_memory(config: Config) -> MemoryStore:
    try:
        return MemoryStore(
            config.memory_db or config.data_dir / "memory.db",
            migrate_from=config.legacy_memory_json,
        )
    except MemoryStoreError as exc:
        logger.error("Memory database unavailable (%s); using an in-memory store.", exc)
        return MemoryStore(":memory:")


def _build_speech(config: Config, force_text: bool = False):
    if force_text:
        logger.info("Typed-command mode requested.")
        return TextOnlySpeech(config)
    try:
        return SpeechEngine(config)
    except Exception as exc:
        logger.error("Speech engine could not start (%s); using typed commands.", exc)
        return TextOnlySpeech(config)


# ----------------------------------------------------------------- main loops
def _voice_loop(
    executor: ActionExecutor,
    speech: SpeechEngine,
    speaker: Speaker,
    ui: InterfaceController | NullInterface,
    detector: ClapDetector | None,
    config: Config,
) -> int:
    speech.calibrate(force=True)

    if detector is not None and detector.available():
        logger.info("Idle. Clap twice (or press Ctrl+C to quit)...")
        activated = _wait_for_clap(detector) and _activate(
            executor, speech, speaker, ui, config, via_clap=True
        )
        if activated == "shutdown":
            return 0
    else:
        logger.info("Clap detection unavailable; use the wake phrase 'Hey Vision'.")

    while not speech.degraded:
        logger.info("Idle. Say 'Hey Vision' to resume listening.")
        heard = speech.listen_for_wake_word()
        if heard and is_wake_phrase(heard, config.wake_phrases):
            speaker.speak("Yes Sir. I am listening.")
            if _activate(executor, speech, speaker, ui, config, via_clap=False) == "shutdown":
                return 0
    return _text_loop(executor, config)


def _wait_for_clap(detector: ClapDetector) -> bool:
    triggered = threading.Event()
    finished = threading.Event()

    def worker() -> None:
        try:
            if detector.run():
                triggered.set()
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning("Clap detector crashed: %s", exc)
        finally:
            finished.set()

    threading.Thread(target=worker, name="clap-detector", daemon=True).start()
    while not triggered.is_set() and not finished.is_set():
        if triggered.wait(0.2):
            break
    detector.stop()
    return triggered.is_set()


def _activate(
    executor: ActionExecutor,
    speech: SpeechEngine,
    speaker: Speaker,
    ui: InterfaceController | NullInterface,
    config: Config,
    *,
    via_clap: bool,
) -> str:
    if via_clap:
        time.sleep(0.5)  # let the clap thread release the microphone
        ui.open()
        time.sleep(1.0)
        speaker.speak(
            f"{_time_greeting()} Sir. Vision online. All systems running at optimal "
            "performance. What is the plan?"
        )
    else:
        ui.open()

    while True:
        if speech.degraded:
            logger.warning("Microphone lost; switching to typed commands.")
            return "degraded"
        try:
            command = speech.listen_for_command()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.warning("Listen loop error: %s", exc)
            time.sleep(0.5)
            continue
        if not command:
            time.sleep(0.05)
            continue
        try:
            _process(command, executor)
        except SleepRequested:
            logger.info("Entering idle mode.")
            return "sleep"
        except ShutdownRequested:
            return "shutdown"


def _text_loop(executor: ActionExecutor, config: Config) -> int:
    print("Typed-command mode. Type 'quit' to exit.")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        try:
            _process(text, executor)
        except SleepRequested:
            print("(idle: typed commands remain available)")
        except ShutdownRequested:
            return 0


def _process(text: str, executor: ActionExecutor) -> str:
    original = text.strip()
    raw, normalized = prepare_command(original)
    intent = detect_intent(normalized, raw) or Intent("chat")
    if intent.name == "chat" and len(normalized.split()) < 2:
        logger.info("Ignoring short/noisy input: %r", normalized)
        return ""
    logger.info("Intent: %s %s", intent.name, intent.args)
    try:
        reply = executor.handle(intent, original)
    except (SleepRequested, ShutdownRequested):
        raise
    except Exception:
        logger.exception("Command failed: %r", original)
        executor.speaker.speak("Error Sir")
        reply = "Error Sir"
    executor.save_conversation(original, reply)
    return reply


# ------------------------------------------------------------------- helpers
def _time_greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def _test_interface(config: Config) -> int:
    ui = InterfaceController(config)
    if not ui.open():
        logger.error("Interface failed to start.")
        return 1
    print("Interface running. Press Enter to close (or Ctrl+C).")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        ui.close()
    return 0


def _diagnose(config: Config, platform) -> int:
    capabilities = {
        "native_tts": True,
        "audio_player": platform.os_name in {"macos", "windows"}
        or bool(platform.which("ffplay") or platform.which("paplay") or platform.which("aplay")),
        "ffmpeg": bool(platform.which("ffmpeg")),
        "sox": bool(platform.which("sox")),
        "screenshot": platform.os_name in {"macos", "windows"}
        or bool(
            platform.which("gnome-screenshot")
            or platform.which("spectacle")
            or platform.which("scrot")
        ),
        "edge_tts": _module_available("edge_tts"),
        "vosk": _module_available("vosk"),
        "sounddevice": _module_available("sounddevice"),
        "speech_recognition": _module_available("speech_recognition"),
        "opencv": _module_available("cv2"),
        "mediapipe": _module_available("mediapipe"),
    }
    report = {
        "version": __version__,
        "platform": platform.os_name,
        "python": sys.version.split()[0],
        "config": config.public_dict(),
        "capabilities": capabilities,
        "ollama_model": config.ollama_model,
        "ollama_available": OllamaClient(config).is_available(),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


def _module_available(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
