"""
app_logging.py
------------------
Writes every log message to a plain text file on disk (launcher_log.txt),
in addition to whatever shows up in the app's own log panel. The in-app
panel clears when you close the app or hit "Clear" - this file doesn't,
so you can look back at what happened in a previous session, or just
send the file over if something needs troubleshooting.

This never raises an exception itself - a failed disk write here should
never be able to crash the actual automation.
"""

import os
import time

import app_paths

LOG_FILE = app_paths.path("launcher_log.txt")

# Once the log file gets this big, trim it back down to the most recent
# half - keeps it from growing forever over many sessions, while still
# keeping plenty of recent history.
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def write_log_line(text, level=None):
    """Appends one timestamped line to launcher_log.txt. Call this
    alongside (not instead of) whatever shows the message in the app's
    own log panel."""
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
