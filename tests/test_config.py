"""Configuration and speaking-state tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

from vision.config import Config
from vision.state import IDLE, SPEAKING, SpeakingState


def test_env_overrides(tmp_path: Path) -> None:
    env = {
        "DATA_DIR": str(tmp_path / "data"),
        "VISION_OLLAMA_MODEL": "mistral",
        "CLAP_THRESHOLD": "1234",
        "SOX_EFFECT": "false",
        "INTERFACE_ARGS": "--hd --fps 30",
        "WAKE_PHRASES": "hey jarvis, vision",
        "OLLAMA_TIMEOUT": "12.5",
        "MICROPHONE_DEVICE": "1",
    }
    config = Config.load(env=env, load_env_file=False)
    assert config.ollama_model == "mistral"
    assert config.clap_threshold == 1234
    assert config.sox_effect is False
    assert config.interface_args == ("--hd", "--fps", "30")
    assert config.wake_phrases == ("hey jarvis", "vision")
    assert config.ollama_timeout == 12.5
    assert config.microphone_device == 1
    assert config.memory_db == (tmp_path / "data" / "memory.db").resolve()


def test_legacy_names_are_accepted(tmp_path: Path) -> None:
    config = Config.load(
        env={"CREATOR_NAME": "Ada", "OLLAMA_MODEL": "phi3", "DATA_DIR": str(tmp_path)},
        load_env_file=False,
    )
    assert config.creator_name == "Ada"
    assert config.ollama_model == "phi3"


def test_variable_precedence(tmp_path: Path) -> None:
    config = Config.load(
        env={
            "DATA_DIR": str(tmp_path),
            "OLLAMA_MODEL": "legacy",
            "VISION_OLLAMA_MODEL": "preferred",
        },
        load_env_file=False,
    )
    assert config.ollama_model == "preferred"


def test_ensure_directories(tmp_path: Path) -> None:
    config = Config.load(env={"DATA_DIR": str(tmp_path)}, load_env_file=False)
    config.ensure_directories()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "screenshots").is_dir()
    assert (tmp_path / "photos").is_dir()


def test_paths_are_absolute(tmp_path: Path) -> None:
    config = Config.load(env={"DATA_DIR": str(tmp_path)}, load_env_file=False)
    assert config.memory_db.is_absolute()
    assert config.state_file.is_absolute()


def test_public_dict_is_serialisable(tmp_path: Path) -> None:
    config = Config.load(env={"DATA_DIR": str(tmp_path)}, load_env_file=False)
    data = config.public_dict()
    assert data["ollama_model"] == "llama3"
    assert isinstance(data["memory_db"], str)


def test_speaking_state_roundtrip(tmp_path: Path) -> None:
    state = SpeakingState(tmp_path / "state.txt")
    state.set_speaking(True)
    assert (tmp_path / "state.txt").read_text(encoding="utf-8") == SPEAKING
    assert state.is_speaking() is True
    state.set_idle()
    assert (tmp_path / "state.txt").read_text(encoding="utf-8") == IDLE
    assert state.is_speaking() is False


def test_stale_speaking_state_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "state.txt"
    state = SpeakingState(path)
    state.set_speaking(True)
    old = time.time() - 300
    os.utime(path, (old, old))
    assert state.is_speaking() is False


def test_state_writes_are_atomic(tmp_path: Path) -> None:
    state = SpeakingState(tmp_path / "nested" / "state.txt")
    for _ in range(20):
        state.set_speaking(True)
        state.set_idle()
    assert list(tmp_path.rglob(".state-*.tmp")) == []


def test_missing_state_file_is_idle(tmp_path: Path) -> None:
    assert SpeakingState(tmp_path / "missing.txt").is_speaking() is False
