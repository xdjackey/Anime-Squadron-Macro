"""
leave_position.py
--------------------
Remembers the calibrated Leave button as a fraction of the window's
size (e.g. 73% across, 91% down) instead of a fixed pixel, so it still
works on a different monitor/resolution.
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
    using the given (left, top, width, height) Roblox window rect.
    Returns None if not calibrated yet, or if bbox is None."""
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
