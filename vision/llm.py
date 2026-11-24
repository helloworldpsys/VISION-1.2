"""Ollama client.

Uses Ollama's local HTTP API directly (stdlib ``urllib``) instead of the
``ollama`` Python package.  That removes one dependency, gives us explicit
timeouts, and makes failure handling predictable: a dead Ollama daemon must
produce a spoken message, not a traceback.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .config import Config
from .logging_setup import get_logger
from .memory import MemoryStore

logger = get_logger("llm")

OFFLINE_REPLY = "Sorry Sir, AI is not responding."
DEFAULT_SYSTEM = (
    "You are {name}, a powerful and intelligent AI assistant created by {creator}. "
    "You speak in a calm, deep, confident tone like a futuristic AI. Address the "
    "user as Sir.\nUser name: {user}\nImportant notes: {notes}\n"
    "Reply naturally and briefly unless detail is needed."
)


class OllamaClient:
    def __init__(
        self,
        config: Config,
        memory: MemoryStore | None = None,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self._urlopen = urlopen or urllib.request.urlopen

    # ------------------------------------------------------------------ API
    def is_available(self) -> bool:
        try:
            with self._urlopen(f"{self.config.ollama_host}/api/tags", timeout=3) as resp:
                return int(getattr(resp, "status", 200)) == 200
        except Exception as exc:
            logger.debug("Ollama health check failed: %s", exc)
            return False

    def build_system_prompt(self) -> str:
        name = ""
        notes: list[str] = []
        if self.memory is not None:
            try:
                name = self.memory.get_name()
                notes = self.memory.get_notes()[-5:]
            except Exception as exc:  # memory failure should not kill chat
                logger.warning("Could not read memory for the system prompt: %s", exc)
        return DEFAULT_SYSTEM.format(
            name=self.config.assistant_name,
            creator=self.config.creator_name,
            user=name or "Unknown",
            notes=notes if notes else [],
        )

    def chat(self, prompt: str, system: str | None = None) -> str:
        """Return the model's reply, or a friendly offline message."""
        message = str(prompt or "").strip()
        if not message:
            return "I did not catch that, Sir."
        payload = {
            "model": self.config.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system or self.build_system_prompt()},
                {"role": "user", "content": message},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        attempts = max(1, self.config.ollama_retries + 1)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(
                    f"{self.config.ollama_host}/api/chat",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self._urlopen(request, timeout=self.config.ollama_timeout) as resp:
                    body = resp.read().decode("utf-8", "replace")
                parsed = json.loads(body)
                reply = parsed.get("message", {}).get("content", "")
                if not str(reply).strip():
                    raise ValueError("empty response from Ollama")
                return str(reply).strip()
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                ValueError,
                OSError,
            ) as exc:
                last_error = exc
                logger.warning("Ollama request failed (attempt %s/%s): %s", attempt, attempts, exc)
                if attempt < attempts:
                    time.sleep(min(2.0, 0.35 * (2 ** (attempt - 1))))
        logger.error("Ollama unavailable: %s", last_error)
        return OFFLINE_REPLY
