"""Holographic interface entry point (backwards-compatible).

The original standalone UI is now :mod:`vision.interface_ui`.  Running
``python interface.py`` still works:

    python interface.py            # default resolution
    python interface.py --sd       # 1280x720 (lighter)
    python interface.py --hd       # 1920x1080
"""

from __future__ import annotations

from vision.interface_ui import main

if __name__ == "__main__":
    main()
