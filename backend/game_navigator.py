"""
game_navigator.py
------------------
Combines two simpler pieces into the actions the launcher actually
uses:

  - click_icon(key)          find something on screen and click it
  - scroll_until_found(key)  scroll down bit by bit until something
                             shows up, then click it

Figuring out "is this thing on screen, and where?" lives in screen.py.
Actually moving the mouse and clicking lives in mouse.py. This file
just combines the two into "find it, then click it," plus retrying
and logging what happened.

Requires: pyautogui, mss, numpy, opencv-python
"""

import time

from screen import find_icon, DEFAULT_THRESHOLD, DEFAULT_SCALE_RANGE, _threshold_for
import mouse

# Remembers the last screen position an icon was actually seen at. The
# game window is docked to a fixed size/position for the whole session,
# so once we've seen an icon clearly, its coordinates don't change even
# if something later covers it up visually (e.g. a transient toast
# notification). See use_cache_on_miss in click_icon.
_position_cache = {}


def click_icon(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
               retries=8, retry_pause=1.5, clicks=1, confirm_key=None,
               confirm_timeout=12.0, stop_check=None, log=print,
               click_pause=None, move_duration=None, use_cache_on_miss=False):
    """Finds an icon and clicks it. Retries a few times if it's not found
    yet (the screen may still be loading). Set clicks > 1 to press the
    same button multiple times in a row. Returns True if it clicked,
    False if it never found the icon at all (or stop_check fired).

    stop_check: an optional no-argument callable returning True if the
    caller wants to abort immediately. Checked at the start of every
    retry/poll iteration, so a Stop button can interrupt mid-operation
    instead of only being noticed after the whole call finishes.

    click_pause / move_duration: passed straight through to
    mouse.click_at as pre_click_pause / move_duration. Leave these at
    None for the normal, patient click (the default). Pass small values
    (or 0) for a button that needs to be hit as fast as possible - e.g.
    Leave, which is racing an auto-replay timer.

    use_cache_on_miss: if this icon was successfully found and clicked
    before (anywhere in this run), and it's NOT found on the very first
    attempt this time, click the cached last-known position immediately
    instead of retrying/waiting. This is for buttons whose true position
    never changes (fixed window docking) but that can get visually
    covered by something transient - waiting for the cover to clear can
    lose a race against something else on a timer (e.g. auto-replay), so
    clicking blind at the known-good spot is faster and just as reliable.

    Optional confirm_key: the name of a DIFFERENT icon that should only
    appear once the click has actually taken effect (e.g. something only
    visible on the next screen). If given, after clicking this polls for
    confirm_key to show up (up to confirm_timeout seconds) - if it never
    does, the click gets retried. This is a much more reliable "did that
    actually work" check than watching whether the clicked button itself
    disappeared, since some buttons (selected tabs, toggles) are SUPPOSED
    to stay visible/highlighted after being clicked.

    retries/confirm_timeout default generously (8 attempts, 12s to
    confirm the next screen) since the game doesn't always load a
    screen instantly - these only add extra WAITING time in the slow
    case; a screen that loads quickly still gets found/confirmed
    immediately regardless of the ceiling."""
    click_kwargs = {}
    if click_pause is not None:
        click_kwargs["pre_click_pause"] = click_pause
    if move_duration is not None:
        click_kwargs["move_duration"] = move_duration

    for attempt in range(retries):
        if stop_check and stop_check():
            log(f"[nav] Stopped before finishing '{key}'.")
            return False

        found, x, y, score = find_icon(key, threshold, scale_range)
        if found:
            _position_cache[key] = (x, y)
            mouse.click_at(x, y, retry=attempt, clicks=clicks, **click_kwargs)
            click_word = "click" if clicks == 1 else f"{clicks} clicks"
            log(f"[nav] '{key}' found (score {score:.2f}) -> {click_word} at ({x}, {y})")

            if confirm_key:
                if wait_for_screen(confirm_key, confirm_timeout, log=log, stop_check=stop_check):
                    return True
                if stop_check and stop_check():
                    log(f"[nav] Stopped while confirming '{confirm_key}'.")
                    return False
                if attempt < retries - 1:
                    log(f"[nav] '{confirm_key}' never appeared after clicking '{key}' - retrying the click.")
                    continue
                log(f"[nav] Warning: '{confirm_key}' still hasn't appeared after {retries} attempts. "
                    f"The click may not be registering - check the game window is focused.")
                return False

            # No confirm_key given - informational only. Some buttons are
            # meant to stay visible after clicking (selected tabs,
            # toggles), so a lingering match here does NOT trigger a retry.
            time.sleep(0.6)
            still_there, _, _, still_score = find_icon(key, threshold, scale_range)
            if still_there:
                log(f"[nav] Note: '{key}' still visible after clicking (score {still_score:.2f}) - "
                    f"normal for tabs/toggles, but worth knowing if this button should have disappeared.")

            return True
        if attempt == 0 and use_cache_on_miss and key in _position_cache:
            cx, cy = _position_cache[key]
            log(f"[nav] '{key}' not visible right now (score {score:.2f}) - probably covered by "
                f"something transient. Clicking several spots near its last-known position "
                f"({cx}, {cy}) instead of waiting, since the window layout doesn't change.")
            # Click the cached center plus a handful of nearby offsets - a
            # button is usually clickable across its whole area, not just
            # the bit of text/icon that was actually captured, so this
            # covers the case where an overlay is only covering PART of it.
            # Stops early the moment confirm_key shows up, so if an early
            # click already worked, later ones don't land on whatever's
            # now showing on the NEW screen instead.
            for i, (ox, oy) in enumerate([(0, 0), (-10, 0), (10, 0), (0, -8), (0, 8)]):
                mouse.click_at(cx + ox, cy + oy, retry=attempt + i, clicks=clicks, **click_kwargs)
                if confirm_key and on_screen(confirm_key, threshold, scale_range):
                    return True
            if confirm_key:
                log(f"[nav] Clicked several spots near '{key}''s last-known position but never "
                    f"confirmed '{confirm_key}' afterward.")
                return False
            return True
        if attempt < retries - 1:
            time.sleep(retry_pause)
    log(f"[nav] '{key}' not found after {retries} attempt(s) (best score {score:.2f}). "
        f"Threshold may be too strict, or it's genuinely not on screen.")
    return False


def on_screen(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE):
    """Quick yes/no check: is this icon/landmark visible right now?
    Useful for confirming you're actually on the screen you think you're
    on (e.g. nav.on_screen("menu_play") to check you're at the main
    menu) before doing anything else. Just a thin, readable wrapper
    around find_icon - returns True/False only."""
    found, _, _, _ = find_icon(key, threshold, scale_range)
    return found


def wait_for_screen(key, timeout=8.0, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                     stop_check=None, log=print):
    """Polls for a screen-identifying icon to appear, up to timeout
    seconds. Use this to confirm you've actually arrived somewhere
    (e.g. the lobby, the Create Room page) before proceeding, rather
    than assuming a click worked and barrelling ahead regardless.
    Returns True the moment it's found, False if the timeout runs out
    or stop_check fires."""
    start = time.time()
    while time.time() - start < timeout:
        if stop_check and stop_check():
            return False
        if on_screen(key, threshold, scale_range):
            return True
        time.sleep(0.4)
    log(f"[nav] Never confirmed '{key}' within {timeout:.0f}s - "
        f"doesn't look like that screen loaded.")
    return False


def wait_until_gone(keys, timeout=15.0, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                     poll_pause=0.4, stop_check=None, log=print):
    """Polls until NONE of the given icons are on screen anymore. Use
    this after a result screen (victory/defeat) that the game auto-
    dismisses on its own, before polling for the NEXT result - otherwise
    the same still-visible screen would get detected again immediately
    and counted as a second match that never actually happened.

    Returns True once everything's cleared, False on timeout/stop."""
    start = time.time()
    while time.time() - start < timeout:
        if stop_check and stop_check():
            return False
        if not any(on_screen(k, threshold, scale_range) for k in keys):
            return True
        time.sleep(poll_pause)
    log(f"[nav] {keys} still on screen after {timeout:.0f}s - the auto-replay transition "
        f"may be slower than expected, or it's stuck.")
    return False


def wait_for_any_screen(keys, timeout=120.0, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                         poll_pause=0.2, stop_check=None, log=print):
    """Polls for ANY of several icons to appear (e.g. victory_screen OR
    defeat_screen - a run always ends in exactly one of those, never
    both, so we don't know in advance which one is coming). Checks each
    key in order every poll_pause seconds until one matches or the
    timeout runs out.

    Returns the matching key (str) as soon as one is found, or None on
    timeout / stop_check firing. Use the returned key to branch on
    "was that a win or a loss" without needing two separate polling
    loops running at once."""
    start = time.time()
    while time.time() - start < timeout:
        if stop_check and stop_check():
            return None
        for key in keys:
            if on_screen(key, threshold, scale_range):
                return key
        time.sleep(poll_pause)
    log(f"[nav] Never saw any of {keys} within {timeout:.0f}s - "
        f"the match may still be running longer than expected, or something's stuck.")
    return None


def scroll_until_found(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                        scroll_amount=-300, scroll_pause=0.6, max_scrolls=15,
                        hover_key=None, stop_check=None, log=print):
    """Scrolls down step by step until the icon appears, then clicks it.
    Each scroll is broken into several smaller wheel ticks under the hood
    (see mouse.scroll) rather than one big jump.

    hover_key: the name of an icon that's reliably visible in the SAME
    list you're trying to scroll, BEFORE any scrolling happens (e.g. an
    earlier chapter that's always on screen without scrolling). If given,
    the mouse hovers over that icon's position first - the scroll wheel
    only affects whatever's under the cursor's current position, so
    without this the cursor could still be sitting wherever the last
    click happened (a completely different list/column), and scrolling
    would silently do nothing to the list you actually meant to scroll.

    stop_check: an optional no-argument callable returning True if the
    caller wants to abort immediately - checked before every scroll
    attempt, so a Stop button can interrupt mid-scroll instead of only
    being noticed after all max_scrolls attempts finish.

    Returns True if found and clicked, False if it gave up after
    max_scrolls (or stop_check fired)."""
    if hover_key:
        found, hx, hy, hscore = find_icon(hover_key, threshold, scale_range)
        if found:
            mouse.move_only(hx, hy)
            log(f"[nav] Hovering over '{hover_key}' at ({hx}, {hy}) before scrolling.")
        else:
            log(f"[nav] Warning: couldn't find '{hover_key}' to hover over before scrolling "
                f"(score {hscore:.2f}) - scrolling from wherever the cursor already is.")

    for attempt in range(max_scrolls + 1):
        if stop_check and stop_check():
            log(f"[nav] Stopped while scrolling for '{key}'.")
            return False

        found, x, y, score = find_icon(key, threshold, scale_range)

        if found:
            mouse.click_at(x, y, retry=attempt)
            log(f"[nav] '{key}' found (score {score:.2f}) after {attempt} scroll(s) -> clicked at ({x}, {y})")
            return True

        if attempt < max_scrolls:
            mouse.scroll(scroll_amount)
            time.sleep(scroll_pause)

    log(f"[nav] '{key}' not found after {max_scrolls} scrolls. Giving up - "
        f"make sure the mouse was over the right list before starting.")
    return False
