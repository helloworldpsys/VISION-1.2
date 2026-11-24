"""Controller for the OpenCV holographic interface process.

The UI is deliberately a separate process rather than a thread: OpenCV's
HighGUI event loop must own the main thread on macOS, and process isolation
means a crash or a slow MediaPipe model can never freeze the voice loop.  The
two processes communicate only through the atomic speaking-state file.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from .config import PROJECT_ROOT, Config
from .logging_setup import get_logger

logger = get_logger("ui")


class InterfaceController:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def open(self) -> bool:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True
            try:
                env = os.environ.copy()
                if self.config.state_file is not None:
                    env["VISION_STATE_FILE"] = str(self.config.state_file)
                self._proc = subprocess.Popen(
                    [sys.executable, "-m", "vision.interface_ui", *self.config.interface_args],
                    cwd=str(PROJECT_ROOT),
                    env=env,
                )
            except Exception as exc:
                logger.error("Could not start the interface: %s", exc)
                self._proc = None
                return False
            pid = self._proc.pid
        logger.info("Interface started (pid %s)", pid)
        return True

    def close(self) -> bool:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            logger.warning("Interface did not exit; killing it.")
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception as exc:  # pragma: no cover - platform specific
                logger.warning("Could not kill interface: %s", exc)
        except Exception as exc:  # pragma: no cover - platform specific
            logger.warning("Could not stop interface: %s", exc)
        return True

    def wait(self, timeout: float | None = None) -> int | None:
        with self._lock:
            proc = self._proc
        if proc is None:
            return None
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None


class NullInterface:
    """No-op UI used by tests and by ``--no-interface``."""

    def is_running(self) -> bool:
        return False

    def open(self) -> bool:
        return False

    def close(self) -> bool:
        return False
