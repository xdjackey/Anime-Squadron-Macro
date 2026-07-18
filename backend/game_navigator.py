"""
game_navigator.py
------------------
Combines find-it (screen.py) and click-it (mouse.py) into the actions
the launcher actually uses:

  - click_icon(key)          find something on screen and click it
  - scroll_until_found(key)  scroll until something shows up, then click it

Plus retrying and logging what happened.
"""

import time

from screen import find_icon, DEFAULT_THRESHOLD, DEFAULT_SCALE_RANGE, _threshold_for
import mouse

# Last-seen position of each icon - the window is docked at a fixed size
# for the session, so a once-seen icon's coordinates stay valid even if
# something later covers it visually. See use_cache_on_miss in click_icon.
_position_cache = {}


def click_icon(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
               retries=8, retry_pause=1.5, clicks=1, confirm_key=None,
               confirm_timeout=12.0, stop_check=None, log=print,
               click_pause=None, move_duration=None, use_cache_on_miss=False):
    """Finds an icon and clicks it, retrying if not found yet. Set
    clicks > 1 to press multiple times. Returns True if clicked, False
    if never found (or stop_check fired).

    stop_check: no-arg callable checked every retry, so Stop can
    interrupt mid-operation.

    click_pause / move_duration: passed to mouse.click_at as
    pre_click_pause / move_duration. Lower these (or 0) for buttons
    racing a timer (e.g. Leave vs. auto-replay).

    use_cache_on_miss: if this icon was found before but isn't on the
    first attempt this time, click its cached last-known position
    immediately instead of waiting - for buttons whose position is fixed
    but can get visually covered by something transient.

    confirm_key: a DIFFERENT icon that should only appear once the click
    actually worked. If given, polls for it after clicking (up to
    confirm_timeout) and retries the click if it never shows - more
    reliable than checking if the clicked button itself disappeared,
    since some (tabs, toggles) are supposed to stay visible."""
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
            # Click the cached center plus nearby offsets, in case only
            # part of the button is covered. Stops early once confirmed.
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


def on_screen(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE, region=None, downscale=1.0):
    """Quick yes/no: is this icon/landmark visible right now? Thin
    wrapper around find_icon that returns just True/False.

    region/downscale: same meaning as in screen.find_icon_bbox - use
    these to restrict a presence-only check (not a click target) to a
    known window and a shrunk search frame for speed."""
    found, _, _, _ = find_icon(key, threshold, scale_range, region=region, downscale=downscale)
    return found


def wait_for_screen(key, timeout=8.0, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                     stop_check=None, log=print, region=None, downscale=1.0):
    """Polls for a screen-identifying icon, up to timeout seconds - use
    to confirm you've actually arrived somewhere before proceeding.
    Returns True once found, False on timeout/stop."""
    start = time.time()
    while time.time() - start < timeout:
        if stop_check and stop_check():
            return False
        if on_screen(key, threshold, scale_range, region=region, downscale=downscale):
            return True
        time.sleep(0.4)
    log(f"[nav] Never confirmed '{key}' within {timeout:.0f}s - "
        f"doesn't look like that screen loaded.")
    return False


def wait_until_gone(keys, timeout=15.0, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                     poll_pause=0.4, stop_check=None, log=print, region=None, downscale=1.0):
    """Polls until none of the given icons are on screen anymore - use
    after a result screen the game auto-dismisses, before polling for
    the next result, so the same screen can't get double-counted.
    Returns True once cleared, False on timeout/stop."""
    start = time.time()
    while time.time() - start < timeout:
        if stop_check and stop_check():
            return False
        if not any(on_screen(k, threshold, scale_range, region=region, downscale=downscale) for k in keys):
            return True
        time.sleep(poll_pause)
    log(f"[nav] {keys} still on screen after {timeout:.0f}s - the auto-replay transition "
        f"may be slower than expected, or it's stuck.")
    return False


def wait_for_any_screen(keys, timeout=120.0, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                         poll_pause=0.2, stop_check=None, log=print, region=None, downscale=1.0):
    """Polls for any of several icons to appear (e.g. victory_screen OR
    defeat_screen - never both, and we don't know which is coming).
    Returns the matching key once found, or None on timeout/stop."""
    start = time.time()
    while time.time() - start < timeout:
        if stop_check and stop_check():
            return None
        for key in keys:
            if on_screen(key, threshold, scale_range, region=region, downscale=downscale):
                return key
        time.sleep(poll_pause)
    log(f"[nav] Never saw any of {keys} within {timeout:.0f}s - "
        f"the match may still be running longer than expected, or something's stuck.")
    return None


def scroll_until_found(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE,
                        scroll_amount=-300, scroll_pause=0.6, max_scrolls=15,
                        hover_key=None, stop_check=None, log=print):
    """Scrolls step by step until the icon appears, then clicks it.

    hover_key: an icon reliably visible in the same list before any
    scrolling - if given, the mouse hovers there first, since the wheel
    only affects whatever's under the cursor's current position.

    Returns True if found and clicked, False if it gave up (or stopped)."""
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
