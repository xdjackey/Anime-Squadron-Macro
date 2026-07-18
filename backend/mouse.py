"""
mouse.py
---------
Mouse input only - screen detection lives in screen.py. Uses Windows
SendInput directly with absolute coordinates (no pyautogui).

Moves are smoothed across several steps rather than teleporting, since
some UIs (Roblox included) need real intermediate move events to
register hover. Scrolls are similarly broken into smaller ticks. Click
jitter rotates through a small fixed set of offsets (not random) so
repeated clicks on the same target land at different but predictable
nearby spots.

Windows only.
"""

import ctypes
import ctypes.wintypes as wt
import threading
import time

user32 = ctypes.windll.user32

# Serializes all real mouse input so an anti-idle nudge can't interleave
# with the main automation mid-click.
_action_lock = threading.Lock()

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("_input", _INPUT),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _send_input(inp):
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _to_absolute(x, y):
    """SendInput's MOUSEEVENTF_ABSOLUTE mode expects coordinates in a
    normalized 0-65535 range spanning the full screen, not raw pixels."""
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    return int(x * 65535 / sw), int(y * 65535 / sh)


def _get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _move_to_raw(x, y):
    ax, ay = _to_absolute(x, y)
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi.dx = ax
    inp.mi.dy = ay
    inp.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    _send_input(inp)


def _move_smooth(x, y, duration=0.15, steps=14):
    """Moves the cursor to (x, y) across several ease-out steps instead
    of one jump, so real mouse-move events fire along the path (needed
    for hover-dependent UI buttons)."""
    start_x, start_y = _get_cursor_pos()
    if steps <= 1:
        _move_to_raw(x, y)
        return
    for i in range(1, steps + 1):
        t = i / steps
        eased = 1 - (1 - t) ** 2  # ease-out: quick start, gentle settle
        ix = int(start_x + (x - start_x) * eased)
        iy = int(start_y + (y - start_y) * eased)
        _move_to_raw(ix, iy)
        time.sleep(duration / steps)


def _mouse_down():
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    _send_input(inp)


def _mouse_up():
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi.dwFlags = MOUSEEVENTF_LEFTUP
    _send_input(inp)


def _scroll_tick(amount):
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi.mouseData = ctypes.c_ulong(amount & 0xFFFFFFFF)
    inp.mi.dwFlags = MOUSEEVENTF_WHEEL
    _send_input(inp)


# Rotates through 4 directions (not random), nudging further out with
# more retries - called on every click so clicks don't land pixel-identical.
_click_count = 0
_OFFSETS = [(1, 0), (0, -1), (-1, 0), (0, 1)]


def _jitter_offset(retry=0):
    global _click_count
    idx = _click_count % 4
    _click_count += 1
    jx, jy = _OFFSETS[idx]
    extra = min(retry // 2, 5)
    if idx == 0:
        jx += extra
    elif idx == 1:
        jy -= extra
    elif idx == 2:
        jx -= extra
    else:
        jy += extra
    return jx, jy


def get_cursor_position():
    """Current cursor position - used by anti-idle to restore it after."""
    return _get_cursor_pos()


def move_only(x, y):
    """Smoothly moves the cursor to (x, y) without clicking - use before
    scrolling a list, since the wheel affects whatever's under the
    cursor's current position."""
    with _action_lock:
        _move_smooth(x, y)


def click_at(x, y, retry=0, clicks=1, between_clicks_pause=0.25, pre_click_pause=0.45, move_duration=0.15):
    """Smoothly moves to (x, y) (offset by retry jitter) and clicks. By
    default waits after moving so hover/highlight animations finish
    first. Set clicks > 1 to press multiple times.

    pre_click_pause/move_duration: lower or zero these for time-critical
    clicks that don't need to wait on a hover animation (e.g. clicking
    Leave before auto-replay kicks in)."""
    with _action_lock:
        jx, jy = _jitter_offset(retry)
        _move_smooth(x + jx, y + jy, duration=move_duration)
        if pre_click_pause > 0:
            time.sleep(pre_click_pause)
        for i in range(clicks):
            _mouse_down()
            time.sleep(0.08)
            _mouse_up()
            if i < clicks - 1:
                time.sleep(between_clicks_pause)


def jitter_and_click(offset=(15, 15), pre_click_pause=0.1, settle_pause=0.2):
    """Anti-idle nudge: moves a small distance from the current cursor
    position, clicks once, then moves back exactly to where it started.
    Only trigger this when the cursor is resting somewhere harmless
    (e.g. the lobby), since the click lands near wherever it already was."""
    with _action_lock:
        orig_x, orig_y = _get_cursor_pos()
        jx, jy = offset
        _move_smooth(orig_x + jx, orig_y + jy, duration=0.2)
        if pre_click_pause > 0:
            time.sleep(pre_click_pause)
        _mouse_down()
        time.sleep(0.08)
        _mouse_up()
        time.sleep(settle_pause)
        _move_smooth(orig_x, orig_y, duration=0.2)


def scroll(amount, steps=5, step_pause=0.04):
    """Scrolls at the cursor's current position (negative = down). Breaks
    the total into several smaller ticks instead of one big jump - reads
    as a more natural gesture and scrollable lists handle it better."""
    with _action_lock:
        steps = max(1, steps)
        per_tick = int(amount / steps)
        remainder = amount - per_tick * steps
        for i in range(steps):
            tick = per_tick + (remainder if i == steps - 1 else 0)
            _scroll_tick(tick)
            time.sleep(step_pause)
