"""
trait_shard.py
----------------
Figures out how many Trait Shards dropped this run by checking for two
known pictures - "x1" and "x2" - since shards only ever drop in
amounts of 1 or 2 per run. This is much simpler and more reliable than
reading the number with text recognition, which could occasionally
misread a digit and add the wrong amount.

The x1/x2 search is restricted to a small region right above the
"Trait Shards" label (trait_shard_icon) instead of searching the whole
screen. Two reasons:
  - Other reward drops on the same result screen can ALSO show their
    own "x1"/"x2" badge (a currency or material reward, say) - a
    screen-wide search for just the digit badge risks matching one of
    THOSE instead of the trait shard one.
  - It also makes misreads between x1 and x2 themselves less likely:
    without the region restriction, both templates end up needing to
    include a lot of the surrounding icon/background to stay uniquely
    tied to the trait shard reward, but that background shimmers/
    animates between frames, which drowns out the one thing that
    should actually decide the read (the digit itself).

To set this up, capture three pictures (from the repo root):
    python backend/capture_icons.py trait_shard_icon
    python backend/capture_icons.py trait_shard_x1
    python backend/capture_icons.py trait_shard_x2
trait_shard_icon should be a tight crop of just the "Trait Shards" text.
trait_shard_x1/x2 should be tight crops of just the "x1"/"x2" badge
itself - not the shard icon or any background around it.
"""

from screen import find_icon_bbox

# How far above the "Trait Shards" label to search for the x1/x2 badge,
# and how much wider than the label to search - expressed as a multiple
# of the label's OWN matched size so it scales with whatever resolution
# the label was actually found at, instead of a fixed pixel guess.
SEARCH_HEIGHT_MULTIPLE = 3.0
SEARCH_WIDTH_MARGIN_MULTIPLE = 0.5

# Minimum score gap required between x1 and x2 before trusting whichever
# scored higher - if they're this close, it's genuinely ambiguous rather
# than one being a clean match and the other noise, so this reports
# "couldn't tell" instead of guessing.
MIN_SCORE_GAP = 0.05

# trait_shard_icon/x1/x2 are always captured back-to-back in the same
# capture_icons.py session (right after docking, before ANY individual
# item is captured - see save_capture_reference), so they share the
# exact same capture-time-to-run-time size ratio for this user, every
# time. screen._effective_scale_range() already re-centers the search
# on that ratio dynamically, so there's no need for the wide default
# range (which exists to cover wildly different USERS' setups) here -
# a narrower band around 1.0x plus fewer scale steps still finds these
# reliably, at a fraction of the compute cost. Worth it since this runs
# after every single victory/defeat screen. Kept wider than a razor-thin
# margin, though - a real-world near-miss (icon captured slightly off
# from this session's actual docked size) showed this needs some slack
# rather than assuming the ratio is dead-on every time.
SCALE_RANGE = (0.85, 1.15)
SCALE_STEPS = 8


def read_shard_count(log=print):
    """Checks whether the 'x1' or 'x2' shard-drop picture is showing
    just above the "Trait Shards" label right now. Returns 1, 2, or None
    if neither is found (no shard reward this run, the result screen
    isn't showing yet, or the read was too ambiguous to trust)."""
    found_icon, icon_left, icon_top, icon_w, icon_h, icon_score = find_icon_bbox(
        "trait_shard_icon", scale_range=SCALE_RANGE, scale_steps=SCALE_STEPS)
    if not found_icon:
        log(f"[shard] 'Trait Shards' label not found (best score {icon_score:.2f}) - "
            f"no shard reward this run, or the result screen isn't showing yet.")
        return None

    search_region = (
        int(icon_left - icon_w * SEARCH_WIDTH_MARGIN_MULTIPLE),
        int(icon_top - icon_h * SEARCH_HEIGHT_MULTIPLE),
        int(icon_w * (1 + 2 * SEARCH_WIDTH_MARGIN_MULTIPLE)),
        int(icon_h * SEARCH_HEIGHT_MULTIPLE),
    )
    found_x1, _, _, _, _, score_x1 = find_icon_bbox(
        "trait_shard_x1", region=search_region, scale_range=SCALE_RANGE, scale_steps=SCALE_STEPS)
    found_x2, _, _, _, _, score_x2 = find_icon_bbox(
        "trait_shard_x2", region=search_region, scale_range=SCALE_RANGE, scale_steps=SCALE_STEPS)

    if found_x1 and found_x2:
        gap = abs(score_x1 - score_x2)
        if gap < MIN_SCORE_GAP:
            log(f"[shard] Both 'x1' (score {score_x1:.2f}) and 'x2' (score {score_x2:.2f}) matched "
                f"near the shard label with too small a gap ({gap:.2f}) to trust either - treating "
                f"this run as unread. Consider recropping them tighter (just the digit badge, not "
                f"the icon/background).", "warning")
            return None
        log(f"[shard] Both 'x1' (score {score_x1:.2f}) and 'x2' (score {score_x2:.2f}) matched - "
            f"using whichever scored higher (gap {gap:.2f}).", "warning")
        return 2 if score_x2 > score_x1 else 1

    if found_x2:
        return 2
    if found_x1:
        return 1

    log(f"[shard] Found the 'Trait Shards' label but neither 'x1' nor 'x2' matched near it "
        f"(best scores: x1={score_x1:.2f}, x2={score_x2:.2f}) - couldn't read the amount this run.",
        "warning")
    return None
