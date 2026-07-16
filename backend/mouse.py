"""
mouse.py
---------
Mouse input only - no screen detection logic lives here (see screen.py
for that). Uses the Windows SendInput API directly with absolute screen
coordinates (not pyautogui).

Movement is smoothed (several small steps with an easing curve) rather
than an instant teleport - this both looks more natural AND generates
real intermediate mouse-move events along the way, which some UIs (Roblox
included) use to detect genuine hover rather than a cursor that just
appeared at a location. Scrolling breaks a big scroll amount into several
smaller wheel ticks for the same reason - one huge wheel delta can
overshoot or get handled less reliably than a few natural-feeling ticks.

Jitter is retry-based, not purely random: each call rotates through a
small fixed set of pixel offsets and grows slightly with the retry
number, so repeated attempts at the same target land at different but
predictable nearby spots.

Requires: nothing beyond the standard library (ctypes) - no pyautogui.
Windows only.
"""

import ctypes
import ctypes.wintypes as wt
import threading
import time

user32 = ctypes.windll.user32

# All real hardware input (moves, clicks, scrolls) goes through this lock.
# Without it, a background anti-idle nudge firing at the same instant the
# main automation is mid-click could interleave two unrelated mouse
# movements/clicks - this just makes sure only one "action" ever touches
# the real cursor at a time, regardless of which thread it's called from.
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
    """Moves the cursor from wherever it currently is to (x, y) across
    several intermediate steps with an ease-out curve (fast start, slow
    finish), instead of one instant jump. This generates real mouse-move
    events along the path - a single teleport skips those entirely,
    which is part of why some hover-dependent UI buttons weren't
    registering clicks reliably."""
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


# Retry-based jitter: rotates through 4 directions rather than picking
# randomly, and nudges further out the more retries have happened. This
# is deliberately called on every click (not just retries) so consecutive
# clicks on different buttons also don't all land pixel-identical.
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
    """Public wrapper around the current cursor position - used by the
    anti-idle feature to remember where to put the cursor back."""
    return _get_cursor_pos()


def move_only(x, y):
    """Smoothly moves the cursor to (x, y) WITHOUT clicking - use this to
    hover over a scrollable list before scrolling it, since the mouse
    wheel affects whatever's under the cursor's CURRENT position. If the
    cursor is still sitting wherever the last click happened (a
    different list/column entirely), scrolling silently does nothing to
    the list you actually meant to scroll."""
    with _action_lock:
        _move_smooth(x, y)


def click_at(x, y, retry=0, clicks=1, between_clicks_pause=0.25, pre_click_pause=0.45, move_duration=0.15):
    """Smoothly moves to (x, y) - offset by a small retry-based jitter -
    and clicks. By default waits after moving before pressing so any
    hover/highlight animation the target plays (many Roblox UI buttons
    visibly grow/glow on hover before they'll register a click) has time
    to finish. Set clicks > 1 to press multiple times in a row.

    pre_click_pause: override the post-move wait. Buttons that don't
    depend on a hover animation to register - or that need to be hit
    before something else on a timer (e.g. clicking Leave before an
    auto-replay kicks back in) - can pass a much smaller value here, or
    0, to click as fast as possible.

    move_duration: override how long the cursor takes to glide to the
    target. Lower this alongside pre_click_pause for the same
    time-critical clicks - no point clicking instantly if the mouse
    itself takes 150ms to arrive."""
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
    """Anti-idle nudge: remembers the current cursor position, moves a
    small distance away, clicks once, then moves the cursor back to
    EXACTLY where it started. Meant to be called periodically (e.g.
    every ~10 minutes) while nothing else is happening, purely to keep
    the game from treating the session as AFK - the click lands wherever
    the cursor already was plus a small offset, so callers should only
    trigger this when the cursor is known to be resting somewhere
    harmless (e.g. the lobby, not mid-menu over a real button)."""
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
    """Scrolls the mouse wheel at its current position. Negative = down,
    positive = up. Breaks the total amount into several smaller ticks
    with brief pauses between them instead of one big jump - this reads
    as a more natural scroll gesture and tends to be handled more
    reliably by scrollable UI lists than a single large wheel delta."""
    with _action_lock:
        steps = max(1, steps)
        per_tick = int(amount / steps)
        remainder = amount - per_tick * steps
        for i in range(steps):
            tick = per_tick + (remainder if i == steps - 1 else 0)
            _scroll_tick(tick)
            time.sleep(step_pause)
