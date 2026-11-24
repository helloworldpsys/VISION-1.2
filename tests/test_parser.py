"""Command parser tests (English + Hindi/Hinglish)."""

from __future__ import annotations

import pytest

from vision.parser import (
    detect_intent,
    is_wake_phrase,
    parse_level_request,
    prepare_command,
)


def intent_of(text: str):
    raw, cmd = prepare_command(text)
    return detect_intent(cmd, raw)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Open YouTube", "open_app"),
        ("youtube kholo", "open_app"),
        ("Open Chrome", "open_app"),
        ("Play Believer", "play_song"),
        ("believer gana sunao", "play_song"),
        ("Search Python tutorials on Google", "search"),
        ("Search cats on YouTube", "search"),
        ("Take a screenshot", "screenshot"),
        ("Take a photo", "take_photo"),
        ("selfie", "take_photo"),
        ("Create a folder named projects", "create_folder"),
        ("Open folder downloads", "open_folder"),
        ("Volume 40", "volume"),
        ("increase volume", "volume"),
        ("mute", "volume"),
        ("unmute", "volume"),
        ("Battery", "battery"),
        ("My name is Alex", "set_name"),
        ("What is my name", "get_name"),
        ("Remember that my exam is on Friday", "add_note"),
        ("Show my notes", "show_notes"),
        ("clear my notes", "clear_notes"),
        ("last conversation", "history"),
        ("clear memory", "clear_memory"),
        ("Who are you", "introduce"),
        ("Close interface", "interface"),
        ("Open interface", "interface"),
        ("go to sleep", "sleep"),
        ("Stop Vision", "stop"),
    ],
)
def test_intents(text: str, name: str) -> None:
    intent = intent_of(text)
    assert intent is not None, f"{text!r} produced no intent"
    assert intent.name == name


@pytest.mark.parametrize(
    ("text", "args"),
    [
        ("Volume 40", {"mode": "set", "value": 40}),
        ("set volume to 55 percent", {"mode": "set", "value": 55}),
        ("Increase volume by 10", {"mode": "up", "value": 10}),
        ("decrease volume by 5", {"mode": "down", "value": 5}),
        ("increase volume", {"mode": "up", "value": None}),
        ("volume max", {"mode": "set", "value": 100}),
    ],
)
def test_volume_arguments(text: str, args: dict) -> None:
    intent = intent_of(text)
    assert intent is not None and intent.name == "volume"
    assert intent.args == args


def test_mute_is_not_unmute() -> None:
    muted = intent_of("mute")
    unmuted = intent_of("unmute")
    assert muted is not None and muted.args["mode"] == "mute"
    assert unmuted is not None and unmuted.args["mode"] == "unmute"


def test_name_extraction() -> None:
    intent = intent_of("My name is Alex")
    assert intent is not None
    assert intent.args["name"] == "alex"


def test_note_extraction() -> None:
    intent = intent_of("Remember that my exam is on Friday")
    assert intent is not None
    assert intent.args["note"] == "my exam is on friday"


def test_search_query_strips_platform() -> None:
    intent = intent_of("Search Python tutorials on Google")
    assert intent is not None
    assert intent.args == {"platform": "google", "query": "python tutorials"}


def test_youtube_search_routes_to_youtube() -> None:
    intent = intent_of("Search cats on YouTube")
    assert intent is not None
    assert intent.args["platform"] == "youtube"
    assert intent.args["query"] == "cats"


def test_create_folder_name() -> None:
    intent = intent_of("Create a folder named projects")
    assert intent is not None
    assert intent.args["name"] == "projects"


def test_close_vs_open_interface() -> None:
    closed = intent_of("Close interface")
    opened = intent_of("Open interface")
    assert closed is not None and closed.args == {"action": "close"}
    assert opened is not None and opened.args == {"action": "open"}


def test_question_has_no_rule_intent() -> None:
    assert intent_of("What is the capital of France") is None


def test_short_noise_has_no_intent() -> None:
    assert intent_of("uh") is None


def test_prepare_command_removes_fillers_and_punctuation() -> None:
    raw, cmd = prepare_command("Hey Vision, can you please open YouTube?")
    assert raw == "hey vision can you please open youtube"
    assert cmd == "open youtube"


@pytest.mark.parametrize(
    ("text", "mode", "value"),
    [
        ("volume 30", "set", 30),
        ("up by 15", "up", 15),
        ("down by 200", "down", 100),
        ("half", "set", 50),
        ("minimum", "set", 0),
        ("increase", "up", None),
        ("something", None, None),
    ],
)
def test_parse_level_request(text: str, mode, value) -> None:
    assert parse_level_request(text) == (mode, value)


@pytest.mark.parametrize("text", ["Hey Vision", "hey vishon", "a vision", "VISION"])
def test_wake_phrases(text: str) -> None:
    assert is_wake_phrase(text) is True


def test_wake_phrase_negative() -> None:
    assert is_wake_phrase("open youtube") is False
