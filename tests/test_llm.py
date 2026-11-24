"""Ollama client tests with an injected transport."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

from vision.config import Config
from vision.llm import OFFLINE_REPLY, OllamaClient
from vision.memory import MemoryStore


class FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def make_config(tmp_path: Path, **overrides) -> Config:
    values = {"ollama_retries": 0, "ollama_timeout": 1.0}
    values.update(overrides)
    return Config(data_dir=tmp_path, **values).resolved_paths()


def test_chat_success(tmp_path: Path) -> None:
    calls: list[Any] = []

    def urlopen(request, timeout=None):
        calls.append(request)
        return FakeResponse({"message": {"content": "  Hello Sir.  "}})

    client = OllamaClient(make_config(tmp_path), urlopen=urlopen)
    assert client.chat("hi") == "Hello Sir."
    assert calls
    assert calls[0].full_url.endswith("/api/chat")


def test_chat_offline(tmp_path: Path) -> None:
    def urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    client = OllamaClient(make_config(tmp_path), urlopen=urlopen)
    assert client.chat("hi") == OFFLINE_REPLY


def test_empty_prompt_is_handled(tmp_path: Path) -> None:
    client = OllamaClient(make_config(tmp_path), urlopen=lambda *a, **k: FakeResponse({}))
    assert "did not catch" in client.chat("   ")


def test_system_prompt_uses_memory(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.db")
    memory.set_name("Alex")
    memory.add_note("exam on Friday")
    try:
        client = OllamaClient(make_config(tmp_path), memory=memory)
        prompt = client.build_system_prompt()
        assert "Alex" in prompt
        assert "exam on Friday" in prompt
        assert "Taha" in prompt
    finally:
        memory.close()


def test_health_check(tmp_path: Path) -> None:
    client = OllamaClient(
        make_config(tmp_path), urlopen=lambda *a, **k: FakeResponse({"models": []})
    )
    assert client.is_available() is True

    def broken(*args, **kwargs):
        raise OSError("down")

    assert OllamaClient(make_config(tmp_path), urlopen=broken).is_available() is False
