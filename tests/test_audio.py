"""Small, dependency-free audio helper tests."""

from __future__ import annotations

import struct
from pathlib import Path

from vision.audio import TextOnlySpeech, _rms_bytes
from vision.config import Config


def test_rms_silence() -> None:
    assert _rms_bytes(b"") == 0.0
    assert _rms_bytes(b"\x00\x00\x00\x00") == 0.0


def test_rms_constant_signal() -> None:
    data = struct.pack("<4h", 1000, 1000, 1000, 1000)
    assert _rms_bytes(data) == 1000.0


def test_rms_odd_length_is_safe() -> None:
    assert _rms_bytes(b"\x01") == 0.0


def test_text_only_speech(tmp_path: Path, monkeypatch) -> None:
    config = Config(data_dir=tmp_path).resolved_paths()
    speech = TextOnlySpeech(config)
    assert speech.degraded is True
    assert speech.microphone_available is False
    monkeypatch.setattr("builtins.input", lambda prompt="": "open youtube")
    assert speech.listen() == "open youtube"
    assert speech.read_text() == "open youtube"
    speech.calibrate(force=True)
    speech.close()
