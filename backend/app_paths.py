"""
app_paths.py
--------------
Works out the one folder the app's data files (settings, saved progress,
captured pictures) should live in, regardless of how the app was
started - Windows can launch an .exe from a different "current folder"
than wherever it actually sits, so plain filenames aren't safe.
"""

import os
import sys

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)  # packaged .exe
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # plain .py, up from backend/


def path(filename):
    """Full path for a file the app reads/writes at runtime (settings,
    saved progress) - always the same real folder."""
    return os.path.join(BASE_DIR, filename)


def bundled_path(filename):
    """Full path for a READ-ONLY file baked in at build time. A single-
    file .exe extracts bundled data to a temp folder (sys._MEIPASS) that
    isn't BASE_DIR, so path() would never find it there - this handles
    that case; otherwise it's the same as path()."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return path(filename)
