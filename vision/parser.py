"""Pure, hardware-free command parsing.

Everything in this module is deterministic and dependency-free, which is why
it is the main target of the unit-test suite.  The old ``vision.py`` mixed
regex parsing with ``subprocess`` calls and speech output; that made it nearly
impossible to test.  :func:`detect_intent` now returns an :class:`Intent`
value and the :mod:`vision.actions` layer performs the side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Intent:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


FILLER_PHRASES = [
    "can you",
    "could you",
    "would you",
    "will you",
    "can u",
    "please",
    "kindly",
    "zara",
    "jara",
    "ek baar",
    "yaar",
    "bhai",
    "mere liye",
    "for me",
    "hey",
    "okay",
    "ok",
    "vision",
]
OPEN_WORDS = [
    "open",
    "launch",
    "start",
    "run",
    "kholo",
    "khol",
    "kholna",
    "kholiye",
    "kholdo",
    "khol do",
    "khol de",
    "chalu",
    "chalao",
    "chala do",
    "chalana",
]
APP_ALIASES = {
    "youtube": ["youtube", "you tube"],
    "safari": ["safari"],
    "chrome": ["google chrome", "chrome", "crome"],
}
PLAY_WORDS = ["play", "bajao", "baja do", "bajana", "sunao", "suna do", "sunna", "lagao", "laga do"]
SONG_WORDS = ["song", "songs", "gana", "gaana", "gaane", "music"]
SEARCH_WORDS = ["search", "find", "look up", "dhundo", "dhundh", "dhoondo", "khojo", "khoj"]
CREATE_WORDS = ["create", "make", "new", "generate", "banao", "bana do", "bana", "naya", "nayi"]
CLEAR_WORDS = ["clear", "reset", "delete", "erase", "wipe", "mita", "hata", "bhula", "saaf"]
INTERFACE_WORDS = ["interface", "hologram", "holo gram", "holographic", "holo"]
VOLUME_WORDS = ["volume", "sound", "awaaz", "awaz", "avaaz", "aawaz"]
UP_WORDS = [
    "increase",
    "up",
    "raise",
    "badhao",
    "badha",
    "badhana",
    "zyada",
    "jyada",
    "tez",
    "louder",
    "more",
    "higher",
    "high",
]
DOWN_WORDS = [
    "decrease",
    "down",
    "lower",
    "reduce",
    "kam",
    "kamm",
    "kum",
    "dheema",
    "dheemi",
    "less",
    "quieter",
    "low",
]
NUM_WORDS = {
    "zero": 0,
    "ten": 10,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}
QUESTION_STARTS = (
    "what",
    "why",
    "how",
    "who",
    "when",
    "where",
    "which",
    "tell me",
    "explain",
    "kya",
    "kaun",
    "kyun",
    "kyu",
    "kaise",
    "kitna",
    "kitne",
    "kab",
    "kahan",
    "batao",
)

SLEEP_RE = re.compile(
    r"\b(?:go to sleep|sleep mode|sleep now|sleep vision|vision sleep|stop listening|"
    r"so jao|so ja|chup ho jao|chup ho ja|chup raho|take a break)\b"
)
STOP_RE = re.compile(
    r"\b(?:(?:stop|exit|quit|shut ?down|terminate|close|band)\s+(?:karo\s+)?vision|"
    r"vision\s+(?:stop|exit|quit|shut ?down|terminate|band(?:\s+(?:karo|ho\s+jao|kar\s+do))?)|"
    r"exit program|quit program)\b"
)


def _pattern(words: list[str] | tuple[str, ...]) -> str:
    return r"\b(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b"


def has_any(text: str, words: list[str] | tuple[str, ...]) -> bool:
    return re.search(_pattern(words), text) is not None


def strip_words(text: str, words: list[str] | tuple[str, ...]) -> str:
    return re.sub(r"\s+", " ", re.sub(_pattern(words), " ", text)).strip()


def prepare_command(text: str) -> tuple[str, str]:
    """Return ``(raw, normalized)``: lowercase/no punctuation vs filler-free."""
    raw = re.sub(r"[.,!?;:\"]", " ", str(text).lower())
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw, strip_words(raw, FILLER_PHRASES)


def find_app(text: str) -> str | None:
    best, best_len = None, 0
    for app_name, aliases in APP_ALIASES.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", text) and len(alias) > best_len:
                best, best_len = app_name, len(alias)
    return best


def looks_like_question(cmd: str) -> bool:
    return cmd.startswith(QUESTION_STARTS) or cmd.endswith(" kya hai")


def parse_level_request(cmd: str) -> tuple[str | None, int | None]:
    """Return ``('set', 0-100)``, ``('up'|'down', step|None)`` or ``(None, None)``."""
    direction = "down" if has_any(cmd, DOWN_WORDS) else "up" if has_any(cmd, UP_WORDS) else None
    match = re.search(r"\bby\s+(\d{1,3})\b", cmd) or re.search(
        r"\b(\d{1,3})\s+(?:percent\s+)?se\b", cmd
    )
    if match and direction:
        return direction, min(100, int(match.group(1)))
    match = re.search(r"\b(\d{1,3})\b", cmd)
    if match:
        return "set", min(100, int(match.group(1)))
    for word, number in NUM_WORDS.items():
        if re.search(rf"\b{word}\b", cmd):
            return "set", number
    if has_any(cmd, ["full", "max", "maximum"]):
        return "set", 100
    if has_any(cmd, ["half"]):
        return "set", 50
    if has_any(cmd, ["min", "minimum"]):
        return "set", 0
    return (direction, None) if direction else (None, None)


def detect_intent(cmd: str, raw: str | None = None) -> Intent | None:
    """Rule-based intent detection (English + Hindi/Hinglish)."""
    raw = raw if raw is not None else cmd
    tokens = cmd.split()
    app_found = find_app(cmd)

    if SLEEP_RE.search(raw) or ("sleep" in tokens and len(tokens) <= 3):
        return Intent("sleep")
    if STOP_RE.search(raw):
        return Intent("stop")

    if has_any(cmd, ["battery"]):
        return Intent("battery")

    if has_any(cmd, INTERFACE_WORDS):
        if has_any(
            cmd,
            ["close", "stop", "exit", "quit", "hide", "off", "band", "hatao", "hata", "kill"],
        ):
            return Intent("interface", {"action": "close"})
        return Intent("interface", {"action": "open"})

    if has_any(cmd, ["unmute"]):
        return Intent("volume", {"mode": "unmute", "value": None})
    if has_any(cmd, ["mute"]):
        return Intent("volume", {"mode": "mute", "value": None})
    if has_any(cmd, VOLUME_WORDS):
        mode, value = parse_level_request(cmd)
        if mode:
            return Intent("volume", {"mode": mode, "value": value})

    # memory: name
    if has_any(cmd, ["my name", "mera naam", "mera name", "call me"]):
        if has_any(cmd, ["what", "kya", "do you know", "batao", "pata", "who"]):
            return Intent("get_name")
        match = re.search(
            r"(?:my name is|my name's|call me|mera naam|mera name)\s+(.+?)(?:\s+(?:hai|he|h|hain))?$",
            cmd,
        )
        return Intent("set_name", {"name": match.group(1).strip() if match else ""})

    # memory: notes / history
    match = re.search(
        r"\b(?:remember this|remember that|yaad rakho|yaad rakhna|note this|note down|"
        r"note kar lo|note karo|note kar)\b\s*(?:ki\s+|that\s+)?(.*)$",
        cmd,
    )
    if match:
        return Intent("add_note", {"note": match.group(1).strip()})
    if has_any(cmd, ["notes"]):
        return Intent("clear_notes") if has_any(cmd, CLEAR_WORDS) else Intent("show_notes")
    if has_any(
        cmd,
        [
            "what did we talk about",
            "last conversation",
            "previous conversation",
            "chat history",
            "humne kya baat",
            "hamne kya baat",
            "pichli baat",
            "pehle kya baat",
        ],
    ):
        return Intent("history")
    if has_any(cmd, ["memory"]) and has_any(cmd, CLEAR_WORDS):
        return Intent("clear_memory")

    if has_any(
        cmd,
        [
            "tell me about yourself",
            "introduce yourself",
            "who are you",
            "what are you",
            "apne bare mein",
            "apne baare mein",
            "apna parichay",
            "tum kaun ho",
            "aap kaun ho",
            "kaun ho tum",
            "kaun ho aap",
        ],
    ):
        return Intent("introduce")

    if has_any(
        cmd, ["screenshot", "screen shot", "screen capture", "capture screen", "capture the screen"]
    ):
        return Intent("screenshot")
    if has_any(cmd, ["photo", "picture", "selfie", "pic"]) and (
        has_any(
            cmd,
            [
                "take",
                "click",
                "capture",
                "nikalo",
                "nikal",
                "khicho",
                "kheencho",
                "le lo",
                "lo",
                "lena",
                "kar",
            ],
        )
        or "selfie" in tokens
    ):
        return Intent("take_photo")

    # folders
    if has_any(cmd, ["folder"]) and has_any(cmd, CREATE_WORDS):
        name = ""
        match = re.search(r"(?:named|called)\s+(.+)$", cmd)
        if match:
            name = match.group(1)
        else:
            match = re.search(r"(.+?)\s+(?:naam|name)\s+(?:ka|ki|se)\s+folder", cmd)
            if match:
                name = strip_words(match.group(1), [*CREATE_WORDS, "a", "the", "ek", "folder"])
        return Intent(
            "create_folder",
            {"name": strip_words(name, ["folder", "on desktop", "desktop"]) if name else ""},
        )
    if has_any(cmd, ["folder"]) and has_any(
        cmd, [*OPEN_WORDS, "show", "dikhao", "dikha do", "find", "dhundo"]
    ):
        name = strip_words(
            cmd,
            [
                *OPEN_WORDS,
                "show",
                "dikhao",
                "dikha do",
                "find",
                "dhundo",
                "folder",
                "the",
                "my",
                "a",
                "ka",
                "ki",
                "ko",
                "me",
                "mein",
                "wala",
                "mera",
                "meri",
                "mujhe",
            ],
        )
        return Intent("open_folder", {"name": name})

    # search
    if has_any(cmd, SEARCH_WORDS):
        platform = "youtube" if app_found == "youtube" else "google"
        query = strip_words(
            cmd,
            [
                *SEARCH_WORDS,
                "youtube",
                "you tube",
                "google",
                "on",
                "in",
                "for",
                "at",
                "about",
                "par",
                "pe",
                "per",
                "mein",
                "me",
                "se",
                "ko",
                "ka",
                "ki",
                "karo",
                "kar",
                "do",
                "de",
                "kardo",
                "the",
                "a",
            ],
        )
        return Intent("search", {"platform": platform, "query": query})

    # play song
    if has_any(cmd, PLAY_WORDS) or (has_any(cmd, SONG_WORDS) and has_any(cmd, OPEN_WORDS)):
        song = strip_words(
            cmd,
            PLAY_WORDS
            + OPEN_WORDS
            + SONG_WORDS
            + [
                "video",
                "youtube",
                "you tube",
                "on",
                "pe",
                "par",
                "per",
                "mujhe",
                "ek",
                "the",
                "a",
                "for",
                "me",
                "mein",
                "ka",
                "ki",
                "ko",
                "do",
                "de",
                "karo",
                "kar",
                "hai",
                "chahiye",
                "suna",
                "baja",
                "laga",
                "chala",
            ],
        )
        return Intent("play_song", {"song": song})

    # open app
    if app_found and (
        has_any(cmd, OPEN_WORDS) or cmd in [a for al in APP_ALIASES.values() for a in al]
    ):
        return Intent("open_app", {"app": app_found})

    return None


def is_wake_phrase(text: str, phrases: tuple[str, ...] | list[str] | None = None) -> bool:
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", str(text).lower())).strip()
    candidates = phrases or (
        "hey vision",
        "hey visions",
        "a vision",
        "hey vishon",
        "hey vizhan",
    )
    return any(phrase in normalized for phrase in candidates) or normalized in (
        "vision",
        "hey vision",
    )
