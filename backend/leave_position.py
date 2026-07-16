"""
leave_position.py
--------------------
Remembers where the calibrated Leave button is, saved as a percentage
of the window's size (like "73% across, 91% down") instead of an
exact pixel spot. That way, the same saved position still works
correctly even if you're using a different monitor or screen size,
since it always converts back to the right spot based on wherever the
window actually is right now.
"""

import json
import os

import app_paths

POSITION_FILE = app_paths.path("leave_button_position.json")


def save_fraction(x_frac, y_frac):
    with open(POSITION_FILE, "w") as f:
        json.dump({"x_frac": x_frac, "y_frac": y_frac}, f, indent=2)


def resolve_absolute(bbox):
    """Converts the saved fraction into absolute screen coordinates
    using the given (left, top, width, height) bbox - pass in THIS
    session's actual Roblox window rect (e.g. from ui.get_roblox_bbox())
    so this works correctly regardless of what monitor/resolution it's
    docked on right now. Returns None if not calibrated yet, or if bbox
    is None (Roblox not currently docked)."""
    if bbox is None:
        return None
    if not os.path.exists(POSITION_FILE):
        return None
    try:
        with open(POSITION_FILE, "r") as f:
            data = json.load(f)
        x_frac, y_frac = data["x_frac"], data["y_frac"]
    except Exception:
        return None

    left, top, width, height = bbox
    return int(left + x_frac * width), int(top + y_frac * height)
