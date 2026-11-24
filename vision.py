"""Vision entry point (backwards-compatible).

Vision 1.2 users ran ``python vision.py``.  That still works; the implementation
now lives in the :mod:`vision` package:

    python vision.py                 # voice assistant
    python -m vision                 # same thing
    vision                           # console entry point after pip install

Typed mode (no microphone needed)::

    python vision.py --text
"""

from __future__ import annotations

from vision.app import main

if __name__ == "__main__":
    raise SystemExit(main())
