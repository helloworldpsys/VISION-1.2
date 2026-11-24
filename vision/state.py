"""Atomic speaking-state file shared with the OpenCV interface process.

The interface polls this file to fade between blue (idle) and red (speaking).
Writing directly to the final path could leave a truncated/empty file behind
if the setter is interrupted mid-write, which made the hologram stick on the
wrong colour.  Writes are now atomic (``os.replace``) and carry a heartbeat so
a crashed assistant cannot leave the UI red forever.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path

SPEAKING = "speaking"
IDLE = "idle"
MAX_AGE_SECONDS = 120.0


class SpeakingState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._last_state = IDLE

    def _write(self, state: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(state)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                with contextlib.suppress(OSError):
                    os.remove(tmp)

    def set_speaking(self, speaking: bool) -> None:
        state = SPEAKING if speaking else IDLE
        try:
            self._write(state)
            self._last_state = state
        except OSError:
            # Never let a UI cosmetic failure break speech.
            pass

    def set_idle(self) -> None:
        self.set_speaking(False)

    def is_speaking(self) -> bool:
        try:
            if not self.path.exists():
                return False
            text = self.path.read_text(encoding="utf-8").strip()
            age = time.time() - self.path.stat().st_mtime
            return text == SPEAKING and age < MAX_AGE_SECONDS
        except OSError:
            return False

    @property
    def last_state(self) -> str:
        return self._last_state
