"""
display_info.py
------------------
Detects monitor resolution and Windows DPI scaling, and looks up the
CURRENT Roblox window's rect on demand. This is the foundation that
makes calibration resolution-independent: leave_position.py stores the
Leave button as a FRACTION of the Roblox window's size/position (not
fixed pixels), and trait_shard.py stores the shard-count crop as a
FRACTION of the matched icon's own size - both convert back to the
right absolute pixels using whatever the window/icon actually measures
right now, on whatever monitor it's running on.

None of this works if Windows display scaling isn't 100% - scaling
changes how reported pixel coordinates relate to what's physically on
screen, in ways that throw off both clicks and template matching
regardless of any fraction-based math. check_scaling() exists to catch
that early with a clear message, since a silent mismatch here is a
frustrating thing to debug blind.
"""

import ctypes
import ctypes.wintypes

import win32api
import win32gui

from window_lock import find_window


def get_primary_monitor_size():
    """Returns (width, height) of the primary monitor in pixels."""
    return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)


def get_dpi_scaling_percent():
    """Returns the current Windows display scaling as a percentage
    (100, 125, 150, etc.) for the monitor Roblox (or the primary
    monitor, if Roblox isn't open) is on. Returns None if it can't be
    determined - some very old Windows versions don't expose this API."""
    try:
        shcore = ctypes.windll.shcore
        MONITOR_DEFAULTTOPRIMARY = 1
        monitor = ctypes.windll.user32.MonitorFromPoint(
            ctypes.wintypes.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY
        )
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        MDT_EFFECTIVE_DPI = 0
        shcore.GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return round(dpi_x.value / 96 * 100)
    except Exception:
        return None


def check_scaling(log=print):
    """Logs a clear message about whether Windows display scaling is
    100% - every calibrated position/offset in this project assumes it
    is. Call this once at launcher startup."""
    pct = get_dpi_scaling_percent()
    if pct is None:
        log("[display] Couldn't determine display scaling - make sure it's set to 100% "
            "(Settings > System > Display > Scale) for reliable clicks and detection.", "warning")
        return
    if pct != 100:
        log(f"[display] Windows display scaling is {pct}%, not 100% - this WILL throw off "
            f"clicks and icon detection regardless of anything else. Set it to 100% in "
            f"Settings > System > Display > Scale, then restart the launcher.", "error")
    else:
        log("[display] Display scaling confirmed at 100%.", "success")


def get_roblox_window_rect(title_substring="Roblox"):
    """Returns (left, top, width, height) of the CURRENT Roblox window,
    queried fresh (not cached) so it reflects the actual window
    regardless of what monitor/resolution it's on right now. Returns
    None if Roblox isn't found."""
    hwnd = find_window(title_substring)
    if hwnd is None:
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return left, top, right - left, bottom - top
