"""Vision - a cross-platform voice assistant with a holographic interface.

The package is intentionally import-light: importing :mod:`vision` must never
pull in OpenCV, MediaPipe, PyAudio or any other heavy/hardware dependency.
Those are imported lazily by the modules that need them so that the command
parser, memory store and platform layer remain unit-testable on any machine.
"""

from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["__version__"]
