"""Side effects for parsed intents.

The parser decides *what* the user wants; this module does it.  Keeping the
two apart means the command grammar can be tested without a microphone,
speaker, camera or Ollama running.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import Config
from .llm import OllamaClient
from .logging_setup import get_logger
from .memory import MemoryStore
from .parser import Intent
from .platform_utils import PlatformAdapter
from .tts import Speaker

if TYPE_CHECKING:  # pragma: no cover
    from .audio import SpeechEngine
    from .ui import InterfaceController

logger = get_logger("actions")

VOLUME_STEP = 10


class ShutdownRequested(Exception):
    """Raised when the user asks Vision to stop."""


class SleepRequested(Exception):
    """Raised when the user asks Vision to go idle."""


def safe_filename(name: str) -> str:
    """Strip directory components and characters that are invalid on Windows."""
    cleaned = str(name or "").strip().strip("/\\")
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    for char in '<>:"|?*':
        cleaned = cleaned.replace(char, "_")
    cleaned = "".join(ch for ch in cleaned if ch.isprintable()).strip(" .")
    if cleaned in {"", ".", ".."}:
        return ""
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if cleaned.split(".")[0].upper() in reserved:
        cleaned = f"_{cleaned}"
    return cleaned[:120]


class ActionExecutor:
    def __init__(
        self,
        config: Config,
        platform: PlatformAdapter,
        memory: MemoryStore,
        speaker: Speaker,
        llm: OllamaClient,
        ui: InterfaceController,
        speech: SpeechEngine,
    ) -> None:
        self.config = config
        self.platform = platform
        self.memory = memory
        self.speaker = speaker
        self.llm = llm
        self.ui = ui
        self.speech = speech

    # ------------------------------------------------------------------ public
    def handle(self, intent: Intent, original: str) -> str:
        name = intent.name
        args = intent.args

        if name == "chat":
            return self.chat(original)

        handler = getattr(self, f"_do_{name}", None)
        if handler is None:
            logger.warning("No handler for intent %r", name)
            self.speaker.speak("I do not know how to do that yet, Sir.")
            return ""
        reply = handler(args, original)
        return reply or ""

    def chat(self, prompt: str) -> str:
        self.speaker.speak("Thinking Sir")
        reply = self.llm.chat(prompt)
        self.speaker.speak(reply)
        return reply

    def ask_followup(self, question: str, timeout: int = 8, phrase_time: int = 8) -> str:
        self.speaker.speak(question)
        if self.speech.degraded:
            return self.speech.read_text("You: ")
        return self.speech.listen(timeout, phrase_time)

    # ------------------------------------------------------------------- apps
    def _do_open_app(self, args: dict[str, Any], _original: str) -> str:
        app = str(args.get("app", "")).strip()
        labels = {
            "youtube": "Opening YouTube",
            "safari": "Opening Safari",
            "chrome": "Opening Chrome",
        }
        reply = labels.get(app, f"Opening {app}")
        self.speaker.speak(reply)
        if not self.platform.open_app(app):
            reply = f"Sorry Sir, I could not open {app}"
            self.speaker.speak(reply)
        return reply

    # -------------------------------------------------------------- interface
    def _do_interface(self, args: dict[str, Any], _original: str) -> str:
        action = str(args.get("action", "open")).lower()
        if action == "close":
            closed = self.ui.close()
            reply = "Interface closed" if closed else "The interface is not running"
            self.speaker.speak(reply)
            return reply
        if self.ui.is_running():
            reply = "The interface is already running"
            self.speaker.speak(reply)
            return reply
        reply = "Activating interface"
        self.speaker.speak(reply)
        if not self.ui.open():
            reply = "Sir, the interface failed to start"
            self.speaker.speak(reply)
        return reply

    # ---------------------------------------------------------------- folders
    def _do_open_folder(self, args: dict[str, Any], _original: str) -> str:
        name = str(args.get("name", "")).strip() or self.ask_followup("Which folder should I open?")
        if not name:
            reply = "I did not get the folder name"
            self.speaker.speak(reply)
            return reply
        folder = self.platform.find_folder(name.lower())
        if folder is None:
            reply = "Folder not found Sir"
            self.speaker.speak(reply)
            return reply
        self.speaker.speak("Opening folder")
        self.platform.open_path(folder)
        return f"Opened folder {folder}"

    def _do_create_folder(self, args: dict[str, Any], _original: str) -> str:
        raw = str(args.get("name", "")).strip() or self.ask_followup(
            "What should I name the folder?"
        )
        name = safe_filename(raw)
        if not name:
            reply = "I did not get a valid folder name"
            self.speaker.speak(reply)
            return reply
        target = self.platform.desktop_dir / name
        try:
            if target.exists():
                reply = "Folder already exists"
            else:
                target.mkdir(parents=True, exist_ok=False)
                reply = f"Folder {name} created successfully"
        except OSError as exc:
            logger.error("Could not create folder %s: %s", target, exc)
            reply = "Error creating folder"
        self.speaker.speak(reply)
        return reply

    # ------------------------------------------------------------- web actions
    def _do_play_song(self, args: dict[str, Any], _original: str) -> str:
        song = str(args.get("song", "")).strip()
        if not song:
            reply = "Please tell me the song name."
            self.speaker.speak(reply)
            return reply
        self.speaker.speak(f"Playing {song} on YouTube")
        self.platform.open_url(
            f"https://www.youtube.com/results?search_query={urllib.parse.quote(song)}"
        )
        return f"Play request processed for {song}"

    def _do_search(self, args: dict[str, Any], _original: str) -> str:
        platform_name = str(args.get("platform", "google")).lower()
        query = str(args.get("query", "")).strip() or self.ask_followup(
            "What should I search for?", 8, 10
        )
        if not query:
            reply = "I did not get the search query"
            self.speaker.speak(reply)
            return reply
        encoded = urllib.parse.quote(query)
        if platform_name == "youtube":
            self.platform.open_url(f"https://www.youtube.com/results?search_query={encoded}")
            reply = f"Searching YouTube for {query}"
        else:
            self.platform.open_url(f"https://www.google.com/search?q={encoded}")
            reply = f"Searching Google for {query}"
        self.speaker.speak(reply)
        return reply

    # --------------------------------------------------------------- captures
    def _do_screenshot(self, _args: dict[str, Any], _original: str) -> str:
        directory = Path(self.config.screenshot_dir or "screenshots")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"screenshot_{_stamp()}.png"
        if not self.platform.take_screenshot(path):
            reply = "Sorry Sir, the screenshot failed"
            self.speaker.speak(reply)
            return reply
        self.platform.open_path(path)
        self.speaker.speak("Screenshot taken")
        return f"Screenshot taken and saved at {path}"

    def _do_take_photo(self, _args: dict[str, Any], _original: str) -> str:
        directory = Path(self.config.photo_dir or "photos")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"photo_{_stamp()}.jpg"
        if not _capture_photo(path):
            reply = "Photo capture failed"
            self.speaker.speak(reply)
            return reply
        self.platform.open_path(path)
        self.speaker.speak("Photo captured successfully")
        return f"Photo captured and saved at {path}"

    # ------------------------------------------------------------------ memory
    def _do_set_name(self, args: dict[str, Any], _original: str) -> str:
        name = str(args.get("name", "")).strip().title()
        if not name:
            reply = "Please tell me your name properly"
        else:
            self.memory.set_name(name)
            reply = f"Okay Sir, I will remember that your name is {name}"
        self.speaker.speak(reply)
        return reply

    def _do_get_name(self, _args: dict[str, Any], _original: str) -> str:
        name = self.memory.get_name()
        reply = f"Your name is {name}" if name else "I do not know your name yet"
        self.speaker.speak(reply)
        return reply

    def _do_add_note(self, args: dict[str, Any], _original: str) -> str:
        note = str(args.get("note", "")).strip()
        if not note:
            reply = "Please say something to remember"
        else:
            self.memory.add_note(note)
            reply = "Okay Sir, I saved that in memory"
        self.speaker.speak(reply)
        return reply

    def _do_show_notes(self, _args: dict[str, Any], _original: str) -> str:
        notes = self.memory.get_notes()
        if not notes:
            reply = "You do not have any saved notes"
            self.speaker.speak(reply)
            return reply
        self.speaker.speak("Your saved notes are")
        for index, note in enumerate(notes, start=1):
            self.speaker.speak(f"Note {index}: {note}")
        return "Notes read"

    def _do_clear_notes(self, _args: dict[str, Any], _original: str) -> str:
        self.memory.clear_notes()
        reply = "All your notes have been cleared"
        self.speaker.speak(reply)
        return reply

    def _do_history(self, _args: dict[str, Any], _original: str) -> str:
        conversations = self.memory.recent_conversations(10)
        if not conversations:
            reply = "No previous conversation found"
            self.speaker.speak(reply)
            return reply
        self.speaker.speak("Here are your last conversations. Check the terminal.")
        for item in conversations:
            print("-" * 50)
            print("Time:", item.get("created_at", "Unknown"))
            print("You:", item.get("user_text", ""))
            print("Vision:", item.get("assistant_text", ""))
        return "Conversations shown"

    def _do_clear_memory(self, _args: dict[str, Any], _original: str) -> str:
        self.memory.clear_all()
        reply = "Memory cleared successfully"
        self.speaker.speak(reply)
        return reply

    # ---------------------------------------------------------------- identity
    def _do_introduce(self, _args: dict[str, Any], _original: str) -> str:
        name = self.memory.get_name()
        known = f" I remember you, {name}." if name else ""
        self.speaker.speak(
            f"Hello. I am {self.config.assistant_name}. Created by {self.config.creator_name}."
            f"{known} I am not just an assistant. I am fast, intelligent, and always watching. "
            "What is your command?"
        )
        return "Introduction completed"

    # ------------------------------------------------------------------ system
    def _do_volume(self, args: dict[str, Any], _original: str) -> str:
        mode = str(args.get("mode") or "").lower()
        value = args.get("value")
        try:
            step = int(value) if value is not None else None
        except (TypeError, ValueError):
            step = None

        if mode == "mute":
            self.speaker.speak("Muting")
            return "Muted" if self.platform.set_mute(True) else "Volume change failed"
        if mode == "unmute":
            ok = self.platform.set_mute(False)
            self.speaker.speak("Unmuted" if ok else "I could not unmute")
            return "Unmuted" if ok else "Volume change failed"

        current = self.platform.get_volume()
        current = 50 if current is None else current
        if mode == "set":
            target = step if step is not None else current
        elif mode == "up":
            target = current + (step if step is not None else VOLUME_STEP)
        elif mode == "down":
            target = current - (step if step is not None else VOLUME_STEP)
        else:
            self.speaker.speak("Should I increase or decrease the volume?")
            return "Volume direction not clear"

        target = max(0, min(100, target))
        if not self.platform.set_volume(target):
            reply = (
                "Sorry Sir, I could not change the volume. On Windows install pycaw "
                "or nircmd; on Linux install pulseaudio-utils."
            )
            self.speaker.speak(reply)
            return "Volume change failed"
        if target > 0:
            self.platform.set_mute(False)
        reply = f"Volume set to {target} percent"
        self.speaker.speak(reply)
        return reply

    def _do_battery(self, _args: dict[str, Any], _original: str) -> str:
        reply = self.platform.get_battery()
        self.speaker.speak(reply)
        return reply

    def _do_sleep(self, _args: dict[str, Any], _original: str) -> str:
        reply = "Understood Sir. Going to sleep. Say Hey Vision to wake me up."
        self.speaker.speak(reply)
        raise SleepRequested(reply)

    def _do_stop(self, _args: dict[str, Any], original: str) -> str:
        reply = "Shutting down. Goodbye Sir"
        self.speaker.speak(reply)
        self.save_conversation(original, reply)
        raise ShutdownRequested(reply)

    # --------------------------------------------------------------- utilities
    def save_conversation(self, user_text: str, reply: str) -> None:
        try:
            self.memory.add_conversation(user_text, reply)
        except Exception as exc:
            logger.warning("Could not save conversation: %s", exc)


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _capture_photo(path: Path) -> bool:
    """Take one webcam frame. Camera released on every path."""
    try:
        import time

        import cv2
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.error("OpenCV is required for photos: %s", exc)
        return False

    camera = None
    try:
        camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            logger.warning("Camera not found")
            return False
        time.sleep(2.0)
        for _ in range(20):
            ok, frame = camera.read()
            if ok and frame is not None and frame.size:
                return bool(cv2.imwrite(str(path), frame))
            time.sleep(0.1)
        return False
    except Exception as exc:
        logger.error("Camera error: %s", exc)
        return False
    finally:
        if camera is not None:
            camera.release()
