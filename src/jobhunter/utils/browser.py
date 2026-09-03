"""Open a local HTML file in the OS default browser."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path


def open_in_browser(path: Path) -> bool:
    """Return True on success. Tries os.startfile on Windows, else webbrowser."""
    p = str(path.resolve())
    try:
        if sys.platform == "win32":
            os.startfile(p)  # noqa: S606 - intentional local file open
            return True
        return webbrowser.open("file://" + p)
    except OSError:
        return False
