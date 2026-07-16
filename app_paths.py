"""
app_paths.py
--------------
Works out the ONE folder all the app's data files (captured pictures,
calibration, saved progress, settings) should live in, no matter how
the app was started.

Why this matters: when you just double-click an .exe, Windows
sometimes runs it with a different "current folder" than wherever the
.exe file actually sits. If the app just used plain filenames like
"shard_progress.json", that file could end up saved in the wrong
place - or never be found again the next time you open the app. This
always points to the same folder the app itself lives in, so that
can't happen.
"""

import os
import sys

if getattr(sys, "frozen", False):
    # Running as a packaged .exe (built with PyInstaller) - use the
    # folder the .exe file itself is sitting in.
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as a plain .py file - use the folder this file is in.
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def path(filename):
    """Turns a plain filename (like 'shard_progress.json') into a full
    path inside the app's own folder, so it's always found in the same
    place no matter how the app was launched. Use this for files the
    app READS AND WRITES at runtime (settings, saved progress) - it
    needs to be the same real folder every time so those persist."""
    return os.path.join(BASE_DIR, filename)


def bundled_path(filename):
    """Same idea, but for READ-ONLY files baked in at build time (like
    capture_reference.json) instead of files the app writes to itself.

    This matters specifically for a single-file .exe: PyInstaller
    extracts bundled data files to a TEMPORARY folder (sys._MEIPASS)
    every time the exe runs - which is NOT the same folder the .exe
    itself sits in. Using path() (BASE_DIR) for a bundled file would
    silently never find it in a packaged single-file exe, since it's
    looking in the wrong place entirely. When running from plain source
    (not frozen), there's no separate extraction folder, so this just
    behaves the same as path()."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return path(filename)
