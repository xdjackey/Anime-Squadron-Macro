"""
app_logging.py
------------------
Writes every log message to launcher_log.txt, on top of whatever shows
in the app's own log panel - so history survives after the panel clears.
Never raises; a failed write here should never crash the app.
"""

import os
import time

import app_paths

LOG_FILE = app_paths.path("launcher_log.txt")

# Trim the log back to its most recent half once it gets this big.
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def write_log_line(text, level=None):
    """Appends one timestamped line to launcher_log.txt."""
    try:
        _rotate_if_needed()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        tag = (level or "info").upper()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{tag}] {text}\n")
    except Exception:
        pass  # a failed log write should never crash the app


def _rotate_if_needed():
    try:
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) < MAX_SIZE_BYTES:
            return
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines[len(lines) // 2:])
    except Exception:
        pass
