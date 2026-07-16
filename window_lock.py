"""
window_lock.py
----------------
Utilities for finding, moving, and locking a window in place on Windows.
Used to dock the Roblox window next to the macro's control panel and keep
it from being dragged or resized while the macro is actively running.

This is a separate file from the macro logic on purpose, so the
window-docking feature can be reused, tested, or swapped out independently.

Requires: pywin32   (pip install pywin32)
Windows only - uses the Win32 API directly.
"""

import threading
import time

import win32gui
import win32con
import win32process
import win32api

EDGE_OVERLAP = 8  # compensates for Windows' invisible resize-border margin -
                   # used only to nudge a UI panel's position closer to the
                   # docked window, never to change Roblox's own size/position
                   # (which must stay identical between capture-time and
                   # run-time, or captured icons drift out of alignment).

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_BORDER = 0x00800000
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004

_saved_styles = {}


def remove_borders(hwnd):
    """Strips the title bar and resize border off a window, so its outer
    window rect and its actual client (content) area become identical.

    NOT called automatically by dock_roblox() anymore - forcibly changing
    another application's window style at the OS level turned out to be
    risky in practice (it can desync the game's renderer from what
    Windows thinks the window looks like). Kept here only in case you
    specifically want it for a one-off experiment; call it yourself if so,
    and watch closely for any instability."""
    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
    _saved_styles[hwnd] = style
    new_style = style & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_BORDER
    win32gui.SetWindowLong(hwnd, GWL_STYLE, new_style)
    win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)


def restore_borders(hwnd):
    """Undoes remove_borders(), restoring the window's normal title bar
    and resize border."""
    style = _saved_styles.pop(hwnd, None)
    if style is None:
        return
    win32gui.SetWindowLong(hwnd, GWL_STYLE, style)
    win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)


def titlebar_height():
    """Returns the height (in pixels) of a standard window's title bar +
    top border, for this system. Used to size a cosmetic overlay that
    visually covers Roblox's title bar WITHOUT touching Roblox's window
    itself - just drawing over it from a separate topmost window."""
    SM_CYCAPTION = 4
    SM_CYSIZEFRAME = 33
    SM_CXPADDEDBORDER = 92
    return (win32api.GetSystemMetrics(SM_CYCAPTION)
            + win32api.GetSystemMetrics(SM_CYSIZEFRAME)
            + win32api.GetSystemMetrics(SM_CXPADDEDBORDER))


def get_window_rect(hwnd):
    """Returns (left, top, width, height) for a window handle."""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return left, top, right - left, bottom - top


def find_window(title_substring):
    """Find the first visible top-level window whose title contains
    title_substring (case-insensitive). Returns an hwnd, or None if not found."""
    target = title_substring.lower()
    result = {"hwnd": None}

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if title and target in title.lower():
            result["hwnd"] = hwnd
            return False  # stop enumerating, we found it
        return True

    win32gui.EnumWindows(callback, None)
    return result["hwnd"]


def move_window(hwnd, x, y, width, height):
    """Move and resize a window to an exact position."""
    win32gui.MoveWindow(hwnd, x, y, width, height, True)


def dock_roblox(ui_width, title_substring="Roblox", log_height=0):
    """Finds the Roblox window and resizes/repositions it to fill the
    screen minus a reserved strip on the right (for a UI panel) and,
    optionally, a strip along the bottom.

    Both capture_icons.py and launcher_ui.py call this SAME
    function with the SAME ui_width/log_height, so the game window ends
    up at the identical size/position in both cases. If capturing and
    running ever use different window geometry, every captured icon
    shifts relative to where the game actually draws it - which looks
    like everything "not being detected" even though nothing about the
    icons themselves is wrong.

    This does NOT touch Roblox's window style/border - only its size and
    position. Forcibly changing another application's window style at
    the OS level turned out to be risky in practice.

    Returns (hwnd, roblox_width, roblox_height, screen_w, screen_h), or
    (None, None, None, screen_w, screen_h) if the window wasn't found.
    """
    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)

    hwnd = find_window(title_substring)
    if hwnd is None:
        return None, None, None, screen_w, screen_h

    roblox_width = screen_w - ui_width
    roblox_height = screen_h - log_height
    move_window(hwnd, 0, 0, roblox_width, roblox_height)
    return hwnd, roblox_width, roblox_height, screen_w, screen_h


def bring_to_front(hwnd):
    """Reliably brings a window to the foreground - but does nothing at
    all if it's already the foreground window.

    Windows normally blocks background processes from stealing focus
    (SetForegroundWindow silently fails in that case - no exception, it
    just doesn't work). The standard workaround is to temporarily attach
    our input thread to the target window's thread, which grants
    permission to switch focus - but that attach/detach synchronizes
    input state between the two threads, and doing it repeatedly (e.g.
    once per click) can cause visible hitches/freezes in the target app.
    Checking first and skipping when focus is already correct avoids
    that entirely in the common case.
    """
    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return  # already focused - nothing to do, avoid the attach entirely

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
        current_thread = win32api.GetCurrentThreadId()

        attached = False
        if target_thread != current_thread:
            win32process.AttachThreadInput(current_thread, target_thread, True)
            attached = True

        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)

        if attached:
            win32process.AttachThreadInput(current_thread, target_thread, False)
    except Exception:
        pass  # best-effort - a failed focus attempt shouldn't crash the sequence


class WindowLock:
    """Keeps a window pinned to a fixed position/size while active.

    This doesn't disable Windows' native drag/resize - it works by
    checking the window's actual position several times a second and
    snapping it back immediately if it's changed. In practice this makes
    the window feel "locked" since any drag gets reverted almost instantly.

    Call start() to begin enforcing the position, stop() to release it
    (the window becomes freely movable again).
    """

    def __init__(self, hwnd, x, y, width, height, check_interval=0.15):
        self.hwnd = hwnd
        self.rect = (x, y, width, height)
        self.check_interval = check_interval
        self._active = False
        self._thread = None

    def start(self):
        if self._active:
            return
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._active = False

    def is_active(self):
        return self._active

    def _loop(self):
        x, y, w, h = self.rect
        while self._active:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
                cur_w, cur_h = right - left, bottom - top
                if (left, top) != (x, y) or (cur_w, cur_h) != (w, h):
                    win32gui.MoveWindow(self.hwnd, x, y, w, h, True)
            except Exception:
                # The window handle can become invalid if the game closes
                # mid-session - just stop quietly instead of crashing.
                self._active = False
                break
            time.sleep(self.check_interval)
