"""Speaker and action-executor tests with fakes (no hardware)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import vision.tts as tts_module
from vision.actions import ActionExecutor, safe_filename
from vision.config import Config
from vision.state import SpeakingState
from vision.tts import Speaker


class FakePlatform:
    os_name = "linux"

    def __init__(self) -> None:
        self.spoken: list[tuple[str, str, int]] = []
        self.played: list[str] = []
        self.desktop = None
        self.volume = 50
        self.muted = False
        self.opened: list[Any] = []
        self.screenshots: list[Any] = []

    def has(self, name: str) -> bool:
        return False

    def speak_native(self, text: str, voice: str = "", rate: int = 150) -> bool:
        self.spoken.append((text, voice, rate))
        return True

    def play_audio_file(self, path, volume: float = 1.0) -> bool:
        self.played.append(str(path))
        return True

    def convert_audio(self, source, target) -> bool:
        return False

    @property
    def desktop_dir(self) -> Path:
        assert self.desktop is not None
        return self.desktop

    def get_volume(self) -> int | None:
        return self.volume

    def set_volume(self, percent: int) -> bool:
        self.volume = percent
        return True

    def set_mute(self, muted: bool) -> bool:
        self.muted = muted
        return True

    def open_path(self, path) -> bool:
        self.opened.append(path)
        return True

    def take_screenshot(self, path) -> bool:
        self.screenshots.append(path)
        return True

    def open_url(self, url: str) -> bool:
        self.opened.append(url)
        return True

    def find_folder(self, name: str):
        return None


class FakeSpeaker:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def speak(self, text: str) -> None:
        self.messages.append(str(text))


class FakeSpeech:
    degraded = True

    def listen(self, timeout=4, phrase_time=8) -> str:
        return ""

    def read_text(self, prompt="You: ") -> str:
        return ""


class FakeMemory:
    def __init__(self) -> None:
        self.name = ""
        self.notes: list[str] = []

    def get_name(self) -> str:
        return self.name

    def set_name(self, name: str) -> None:
        self.name = name

    def add_note(self, note: str) -> None:
        self.notes.append(note)

    def get_notes(self) -> list[str]:
        return self.notes

    def recent_conversations(self, limit: int = 10):
        return []


class FakeUI:
    def is_running(self) -> bool:
        return False

    def open(self) -> bool:
        return True

    def close(self) -> bool:
        return True


def make_config(tmp_path: Path, **overrides) -> Config:
    values = {"tts_engine": "native", "data_dir": tmp_path}
    values.update(overrides)
    return Config(**values).resolved_paths()


def test_native_fallback_when_edge_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tts_module, "_edge_available", lambda: False)
    platform = FakePlatform()
    config = make_config(tmp_path, tts_engine="edge")
    state = SpeakingState(tmp_path / "state.txt")
    speaker = Speaker(config, platform, state)  # type: ignore[arg-type]
    speaker.speak("hello\nworld")
    assert platform.spoken == [("hello world", "", 150)]
    assert state.is_speaking() is False


def test_none_engine_only_prints(tmp_path: Path) -> None:
    platform = FakePlatform()
    config = make_config(tmp_path, tts_engine="none")
    speaker = Speaker(config, platform, SpeakingState(tmp_path / "state.txt"))  # type: ignore[arg-type]
    speaker.speak("silent")
    assert platform.spoken == []
    assert platform.played == []


def test_clean_text() -> None:
    assert Speaker._clean(" - hello\nworld ") == "hello world"
    assert Speaker._clean("") == ""


def test_safe_filename() -> None:
    assert safe_filename("Projects") == "Projects"
    assert safe_filename("my: folder?") == "my_ folder_"
    assert safe_filename("../escape") == "_escape"
    assert safe_filename("....") == ""
    assert safe_filename("CON") == "_CON"
    assert len(safe_filename("x" * 500)) == 120


def make_executor(tmp_path: Path, platform: FakePlatform):
    config = make_config(tmp_path)
    speaker = FakeSpeaker()
    executor = ActionExecutor(
        config,
        platform,  # type: ignore[arg-type]
        FakeMemory(),  # type: ignore[arg-type]
        speaker,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        FakeUI(),  # type: ignore[arg-type]
        FakeSpeech(),  # type: ignore[arg-type]
    )
    return executor, speaker


def test_create_folder_stays_on_desktop(tmp_path: Path) -> None:
    platform = FakePlatform()
    platform.desktop = tmp_path / "Desktop"
    platform.desktop.mkdir()
    executor, speaker = make_executor(tmp_path, platform)
    reply = executor._do_create_folder({"name": "projects"}, "")
    assert "created successfully" in reply
    assert (platform.desktop / "projects").is_dir()
    assert speaker.messages


def test_create_folder_rejects_traversal(tmp_path: Path) -> None:
    platform = FakePlatform()
    platform.desktop = tmp_path / "Desktop"
    platform.desktop.mkdir()
    executor, _ = make_executor(tmp_path, platform)
    executor._do_create_folder({"name": "../escape"}, "")
    assert not (tmp_path / "escape").exists()
    assert list(platform.desktop.iterdir())


def test_create_folder_existing(tmp_path: Path) -> None:
    platform = FakePlatform()
    platform.desktop = tmp_path / "Desktop"
    (platform.desktop / "existing").mkdir(parents=True)
    executor, _ = make_executor(tmp_path, platform)
    assert executor._do_create_folder({"name": "existing"}, "") == "Folder already exists"


def test_volume_absolute(tmp_path: Path) -> None:
    platform = FakePlatform()
    executor, speaker = make_executor(tmp_path, platform)
    reply = executor._do_volume({"mode": "set", "value": 40}, "")
    assert reply == "Volume set to 40 percent"
    assert platform.volume == 40
    assert "Volume set to 40 percent" in speaker.messages


def test_volume_relative(tmp_path: Path) -> None:
    platform = FakePlatform()
    platform.volume = 30
    executor, _ = make_executor(tmp_path, platform)
    executor._do_volume({"mode": "up", "value": 10}, "")
    assert platform.volume == 40
    executor._do_volume({"mode": "down", "value": None}, "")
    assert platform.volume == 30


def test_volume_mute(tmp_path: Path) -> None:
    platform = FakePlatform()
    executor, _ = make_executor(tmp_path, platform)
    assert executor._do_volume({"mode": "mute", "value": None}, "") == "Muted"
    assert platform.muted is True


def test_screenshot_path_and_open(tmp_path: Path) -> None:
    platform = FakePlatform()
    executor, _ = make_executor(tmp_path, platform)
    reply = executor._do_screenshot({}, "")
    assert "Screenshot taken" in reply
    assert platform.screenshots
    assert platform.opened
    assert Path(platform.screenshots[0]).parent == tmp_path / "screenshots"
