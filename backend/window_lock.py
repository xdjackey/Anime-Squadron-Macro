"""
window_lock.py
----------------
Finds, moves, and locks a window in place on Windows - used to dock
Roblox next to the control panel and keep it from being dragged/resized
while the macro runs.

Requires: pywin32. Windows only.
"""

import threading
import time

import win32gui
import win32con
import win32process
import win32api

# Compensates for Windows' invisible resize-border margin - only nudges
# the UI panel's position, never Roblox's own size (which must stay
# identical between capture-time and run-time or icons drift out of sync).
EDGE_OVERLAP = 8

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
    """Strips a window's title bar and resize border so its outer rect
    equals its content area. NOT called by dock_roblox() anymore -
    changing another app's window style turned out risky in practice;
    kept only for manual one-off use."""
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
    """Height in pixels of a standard title bar + top border, for this
    system - used to size a cosmetic overlay window that covers Roblox's
    own title bar without touching Roblox itself."""
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


def is_foreground(title_substring):
    """True if the window currently focused/on top has title_substring in
    its title (case-insensitive). A raw screen-region grab (mss) reads
    whatever's rendered on screen at those coordinates regardless of what
    window is supposed to be there - if the user tabs away to a browser
    or another app that overlaps where Roblox was docked, a color/icon
    scan would read THAT window's content instead of the game. Call this
    before trusting a scan that could misfire on unrelated on-screen
    content (e.g. any red/green pixels)."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False
    title = win32gui.GetWindowText(hwnd)
    return bool(title) and title_substring.lower() in title.lower()


def move_window(hwnd, x, y, width, height):
    """Move and resize a window to an exact position."""
    win32gui.MoveWindow(hwnd, x, y, width, height, True)


def dock_roblox(ui_width, title_substring="Roblox", log_height=0):
    """Resizes/repositions Roblox to fill the screen minus a strip on
    the right (UI panel) and, optionally, the bottom (logs). Only
    touches size/position, not window style.

    capture_icons.py and launcher_ui.py must call this with the SAME
    ui_width/log_height, or captured icons drift out of alignment with
    where the game actually draws them.

    Returns (hwnd, roblox_width, roblox_height, screen_w, screen_h), or
    (None, None, None, screen_w, screen_h) if not found."""
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
    """Reliably brings a window to the foreground; no-op if it already
    is. Windows blocks background processes from stealing focus, so this
    briefly attaches our input thread to the target's - skipped when
    already focused, since doing that attach/detach on every call causes
    visible hitches."""
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
    """Keeps a window pinned to a fixed position/size while active, by
    polling and snapping it back several times a second rather than
    disabling drag/resize. start() begins enforcing, stop() releases it."""

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
