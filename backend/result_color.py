"""
result_color.py
------------------
Determines whether a completed match was a Victory or a Defeat by
sampling the results screen's banner background color (green = Victory,
red = Defeat) instead of matching the "Victory!"/"Defeat!" text - the
two banners share almost the same checkered shape and only differ by
color/word, which made text-based matching prone to misreads.

This only runs AFTER the results screen is already confirmed open via
the Retry/Leave buttons (see launcher.py's _wait_for_result_screen /
_detect_outcome) - it has no role in detecting that the results screen
is up, only in reading which outcome it shows once it is.

Only scans BANNER_REGION_FRACTION - a small dedicated area of the
Roblox window where the banner is expected - NOT the whole window.
That's deliberately the opposite of trait_shard.py's reward scan,
which DOES search the whole window since the reward's position varies
more; keeping this one narrow avoids picking up unrelated red/green
elsewhere on screen (health bars, chat text, etc.).

Requires: mss, numpy, opencv-python

BANNER_REGION_FRACTION is calibrated from a real "Victory!" screenshot:
the HP bar sits in the top ~12% of the window, then there's empty space,
then the banner itself runs roughly from 18% to 30% down. The region
below is narrowed to that band on purpose - an earlier, taller version
(y starting at 0.05) swept through the always-on player HP bar during
normal combat and misread its green fill as a victory banner.

Before scanning, this also checks that Roblox is actually the focused
window (window_lock.is_foreground). The scan grabs raw screen pixels at
a fixed, cached coordinate rect - it has no idea what window is actually
rendered there. If the player tabs away to a browser or another app that
overlaps where Roblox was docked, the scan would otherwise read THAT
window's content (which can easily contain its own red/green pixels)
and misreport a victory/defeat that has nothing to do with the game.
"""

import numpy as np
import cv2
import mss

import window_lock

ROBLOX_TITLE = "Roblox"

# Fraction of the Roblox window where the banner is expected - tight
# band around just the checkered banner shape, clear of the HP bar
# above and the stats panel below. See note above for how this was
# calibrated.
BANNER_REGION_FRACTION = {"x": 0.20, "y": 0.18, "w": 0.60, "h": 0.12}

# OpenCV hue is 0-179. Red wraps around 0/180, so it needs two ranges.
GREEN_HUE_RANGE = (35, 85)
RED_HUE_RANGES = ((0, 10), (170, 179))

# Saturation/value floors exclude washed-out or dark pixels (UI chrome,
# shadows, the game world behind the banner) that aren't actually the
# checkered banner color.
MIN_SATURATION = 80
MIN_VALUE = 60

# One color must outnumber the other by this ratio to be trusted, and
# must cover at least this fraction of the scanned region at all - guards
# against a coin-flip call or a stray red/green UI element being
# mistaken for the banner. With the region now tightly cropped to the
# banner itself, a real banner should fill a large share of it (well
# above this floor), while background/stray pixels stay near zero.
MIN_DOMINANT_RATIO = 1.5
MIN_PIXEL_FRACTION = 0.05


def _banner_region(roblox_bbox):
    """Converts BANNER_REGION_FRACTION into an absolute (left, top,
    width, height) rect within the given Roblox window bbox."""
    left, top, width, height = roblox_bbox
    f = BANNER_REGION_FRACTION
    return (
        int(left + f["x"] * width),
        int(top + f["y"] * height),
        int(f["w"] * width),
        int(f["h"] * height),
    )


def _grab_bgr(region):
    left, top, width, height = region
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        return cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2BGR)


def detect_result_color(roblox_bbox, log=print):
    """Samples the banner region (a fraction of roblox_bbox - see
    BANNER_REGION_FRACTION, NOT the whole window) for a dominant green
    or red checkered banner. Returns "victory", "defeat", or "unknown"
    if neither color clearly dominates.

    Returns "unknown" without scanning if Roblox isn't the focused
    window right now - see the module docstring for why."""
    if not window_lock.is_foreground(ROBLOX_TITLE):
        log("[result] Roblox isn't the focused window right now - skipping color scan.")
        return "unknown"
    region = _banner_region(roblox_bbox)
    frame = _grab_bgr(region)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    sat_val_mask = (sat >= MIN_SATURATION) & (val >= MIN_VALUE)

    green_mask = (hue >= GREEN_HUE_RANGE[0]) & (hue <= GREEN_HUE_RANGE[1]) & sat_val_mask
    red_mask = (
        ((hue >= RED_HUE_RANGES[0][0]) & (hue <= RED_HUE_RANGES[0][1])) |
        ((hue >= RED_HUE_RANGES[1][0]) & (hue <= RED_HUE_RANGES[1][1]))
    ) & sat_val_mask

    total = hue.size
    green_count = int(np.count_nonzero(green_mask))
    red_count = int(np.count_nonzero(red_mask))
    green_frac = green_count / total
    red_frac = red_count / total

    log(f"[result] Color scan: green={green_frac:.1%}, red={red_frac:.1%}")

    if green_count >= red_count * MIN_DOMINANT_RATIO and green_frac >= MIN_PIXEL_FRACTION:
        return "victory"
    if red_count >= green_count * MIN_DOMINANT_RATIO and red_frac >= MIN_PIXEL_FRACTION:
        return "defeat"
    return "unknown"
