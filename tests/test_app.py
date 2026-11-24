"""Startup/fallback wiring tests."""

from __future__ import annotations

from pathlib import Path

from vision.app import _build_speech
from vision.audio import TextOnlySpeech
from vision.config import Config


def test_force_text_mode(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path).resolved_paths()
    speech = _build_speech(config, force_text=True)
    assert isinstance(speech, TextOnlySpeech)
    assert speech.degraded is True


def test_missing_audio_dependencies_degrade(tmp_path: Path, monkeypatch) -> None:
    """If the speech engine cannot initialise, Vision must fall back to typing."""

    def boom(*args, **kwargs):
        raise RuntimeError("no audio backend")

    monkeypatch.setattr("vision.app.SpeechEngine", boom)
    config = Config(data_dir=tmp_path, stt_engine="auto").resolved_paths()
    speech = _build_speech(config)
    assert isinstance(speech, TextOnlySpeech)
    assert speech.degraded is True
    speech.close()
