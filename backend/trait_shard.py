"""
trait_shard.py
----------------
Figures out how many Trait Shards dropped this run by checking for two
known pictures - "x1" and "x2" - since shards only ever drop in amounts
of 1 or 2. Simpler and more reliable than OCR.

The reward can pop in with a brief animation and can land anywhere on
the results screen depending on UI scaling/layout, so read_shard_count()
searches the whole Roblox game window (not a fixed sub-area) and polls
repeatedly for a few seconds instead of taking one snapshot. Each scan
is done on a downscaled copy of the frame (see DOWNSCALE) to keep a
full-window search fast enough to actually catch a brief reward flash.

Setup (from the repo root), tight crops only - no icon/background:
    python backend/capture_icons.py trait_shard_icon
    python backend/capture_icons.py trait_shard_x1
    python backend/capture_icons.py trait_shard_x2
"""

import time

from screen import find_icon_bbox

# Minimum score gap needed to trust whichever of x1/x2 scored higher -
# below this it's too close to call, so we keep polling instead.
MIN_SCORE_GAP = 0.05

# trait_shard_icon/x1/x2 are always captured together in one session, so
# they share the same size ratio every time - a narrow scale range and
# few steps finds them fast without the wide search other icons need.
SCALE_RANGE = (0.85, 1.15)
SCALE_STEPS = 8

# Matching cost scales with the frame's pixel count, and these searches
# now cover the WHOLE game window every poll - shrinking the search
# frame to 60% before matching cuts that cost by roughly 3x, with
# negligible score loss even for the small x1/x2 crops (tested against
# realistic image content, not just noise). Precise pixel coordinates
# aren't needed here anyway, just presence/roughly-which-badge.
DOWNSCALE = 0.6

# How long to keep polling for the reward to appear and resolve, and how
# long to pause between polls - covers both the pop-in animation delay
# and any single-frame misses. Faster per-poll matching (DOWNSCALE
# above) means a short poll_pause still gets several checks in before
# timeout instead of missing a reward that only flashes briefly.
SCAN_TIMEOUT = 5.0
POLL_PAUSE = 0.2

# trait_shard_icon is just the "Trait Shards" text label - x1/x2 are the
# small count badge next to it. Both are searched over the whole window
# independently, so without this check a loose/coincidental match on
# each - anywhere, unrelated to each other - could combine into a false
# reading (e.g. some other "xN" badge elsewhere on the results screen
# mistaken for the shard count). Requiring the badge match to actually
# be near the label match is what ties them back into one real reward.
MAX_BADGE_DISTANCE = 300  # pixels, either axis, from the label's center


def _near(box_a, box_b, max_distance=MAX_BADGE_DISTANCE):
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    return (abs((ax + aw / 2) - (bx + bw / 2)) <= max_distance
            and abs((ay + ah / 2) - (by + bh / 2)) <= max_distance)


def read_shard_count(log=print, region=None, timeout=SCAN_TIMEOUT, poll_pause=POLL_PAUSE):
    """Waits for the Trait Shards reward to finish animating in, then
    reads whether it shows 'x1' or 'x2'. Searches the whole Roblox game
    window (region) rather than a fixed sub-area, and polls repeatedly
    until a reward is confirmed or `timeout` seconds pass. Returns 1, 2,
    or None if no reward is ever confirmed (no drop this run, or the
    read stayed ambiguous the whole time) - the caller logs the actual
    count, so this only logs the no-shard-detected case."""
    start = time.time()

    while time.time() - start < timeout:
        found_icon, icon_left, icon_top, icon_w, icon_h, _ = find_icon_bbox(
            "trait_shard_icon", region=region, scale_range=SCALE_RANGE, scale_steps=SCALE_STEPS,
            downscale=DOWNSCALE)
        if found_icon:
            icon_box = (icon_left, icon_top, icon_w, icon_h)
            found_x2, x2_left, x2_top, x2_w, x2_h, score_x2 = find_icon_bbox(
                "trait_shard_x2", region=region, scale_range=SCALE_RANGE, scale_steps=SCALE_STEPS,
                downscale=DOWNSCALE)
            found_x1, x1_left, x1_top, x1_w, x1_h, score_x1 = find_icon_bbox(
                "trait_shard_x1", region=region, scale_range=SCALE_RANGE, scale_steps=SCALE_STEPS,
                downscale=DOWNSCALE)
            found_x2 = found_x2 and _near(icon_box, (x2_left, x2_top, x2_w, x2_h))
            found_x1 = found_x1 and _near(icon_box, (x1_left, x1_top, x1_w, x1_h))

            if found_x1 and found_x2:
                if abs(score_x1 - score_x2) >= MIN_SCORE_GAP:
                    return 2 if score_x2 > score_x1 else 1
                # Too close to call yet - the pop-in animation may still
                # be mid-transition between the two, so keep polling.
            elif found_x2:
                return 2
            elif found_x1:
                return 1

        time.sleep(poll_pause)

    log("[shard] No shard detected this run.")
    return None
