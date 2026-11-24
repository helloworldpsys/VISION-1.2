"""Logging setup: console output plus a rotating file handler.

Console noise used to be the only diagnostics channel in Vision 1.2; crashes
after the terminal scrolled away were impossible to debug.  Every module now
logs through :func:`get_logger`, and the file handler rotates so long-running
installs do not grow without bound.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_CONFIGURED = False
LOGGER_NAME = "vision"


def setup_logging(
    log_dir: str | Path,
    level: str = "INFO",
    max_bytes: int = 1_000_000,
    backups: int = 5,
    *,
    console: bool = True,
) -> logging.Logger:
    """Configure the ``vision`` logger exactly once and return it."""
    global _CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    resolved_level = getattr(logging, str(level).upper(), logging.INFO)

    if _CONFIGURED:
        logger.setLevel(resolved_level)
        return logger

    logger.setLevel(resolved_level)
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / "vision.log"
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max(10_000, int(max_bytes)),
            backupCount=max(1, int(backups)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(resolved_level)
        logger.addHandler(file_handler)
    except OSError as exc:  # unwritable directory: keep running, warn on console
        print(f"Warning: could not open log file {log_path}: {exc}", file=sys.stderr)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.setLevel(resolved_level)
        logger.addHandler(stream)

    _CONFIGURED = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger (``vision.audio``, ``vision.llm``...)."""
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
