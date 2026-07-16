"""
reset_clock.py
-----------------
Keeps track of when the game's Trait Shards reset for the day (5pm
Pacific time by default) and notices exactly once per day when that
happens, so the tracked shard totals can be cleared automatically
right when the game itself resets - not just once whenever the app
happens to be opened.

This correctly handles Daylight Saving Time changes on its own. On
Windows, if the clock ever shows an error about missing timezone
info, just run:  pip install tzdata
"""

import json
import os
from datetime import datetime, timedelta

import app_paths

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

RESET_TIMEZONE = "America/Los_Angeles"  # handles PST/PDT automatically
RESET_HOUR = 17    # 5 PM
RESET_MINUTE = 0

STATE_FILE = app_paths.path("last_shard_reset.json")


def _reset_tz():
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(RESET_TIMEZONE)
    except Exception:
        return None


def get_reset_timezone_time():
    """Returns the current time in the reset timezone (Pacific), or
    None if zoneinfo/tzdata isn't available."""
    tz = _reset_tz()
    if tz is None:
        return None
    return datetime.now(tz)


def get_local_time():
    """Returns the current LOCAL time (whatever timezone this computer
    is set to) - used for the UI clock display."""
    return datetime.now()


def seconds_until_next_reset():
    """Returns seconds until the next 5pm-Pacific reset, or None if
    timezone info isn't available."""
    now = get_reset_timezone_time()
    if now is None:
        return None
    today_reset = now.replace(hour=RESET_HOUR, minute=RESET_MINUTE, second=0, microsecond=0)
    next_reset = today_reset if now < today_reset else today_reset + timedelta(days=1)
    return (next_reset - now).total_seconds()


def _most_recent_reset_boundary(now_pacific):
    """The most recent reset time (today's 5pm Pacific, or yesterday's
    if it hasn't hit 5pm yet today)."""
    today_reset = now_pacific.replace(hour=RESET_HOUR, minute=RESET_MINUTE, second=0, microsecond=0)
    if now_pacific >= today_reset:
        return today_reset
    return today_reset - timedelta(days=1)


def _load_last_reset_marker():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f).get("last_reset_boundary")
    except Exception:
        return None


def _save_last_reset_marker(boundary_iso):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_reset_boundary": boundary_iso}, f, indent=2)
    # Read it back to actually confirm the save took - a silent failure
    # here would mean the reset never gets "remembered" as handled and
    # could otherwise go unnoticed.
    saved = _load_last_reset_marker()
    if saved != boundary_iso:
        raise RuntimeError(
            f"Wrote the reset marker but reading it back gave a different value "
            f"({saved!r} instead of {boundary_iso!r}) - the save may not have worked."
        )


def check_and_consume_reset():
    """Call this periodically (e.g. every 30s). Returns True exactly
    once per actual reset boundary crossed - the first call after 5pm
    Pacific on a given day returns True (and remembers that boundary as
    handled); every other call returns False until the NEXT day's
    reset boundary passes. Returns False (never triggers) if timezone
    info isn't available, rather than guessing wrong and clearing
    progress at an incorrect time."""
    now = get_reset_timezone_time()
    if now is None:
        return False
    boundary_iso = _most_recent_reset_boundary(now).isoformat()
    if _load_last_reset_marker() == boundary_iso:
        return False
    _save_last_reset_marker(boundary_iso)
    return True
