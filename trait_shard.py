"""
trait_shard.py
----------------
Figures out how many Trait Shards dropped this run by checking for two
known pictures - "x1" and "x2" - since shards only ever drop in
amounts of 1 or 2 per run. This is much simpler and more reliable than
reading the number with text recognition, which could occasionally
misread a digit and add the wrong amount.

To set this up, capture two pictures:
    python capture_icons.py trait_shard_x1
    python capture_icons.py trait_shard_x2
crop tight around just the "x1" and "x2" text on a real reward screen
showing each amount.
"""

from screen import find_icon


def read_shard_count(log=print):
    """Checks whether the 'x1' or 'x2' shard-drop picture is showing on
    screen right now. Returns 1, 2, or None if neither is found (no
    shard reward this run, or the result screen isn't showing yet)."""
    found_x1, _, _, score_x1 = find_icon("trait_shard_x1")
    found_x2, _, _, score_x2 = find_icon("trait_shard_x2")

    if found_x1 and found_x2:
        # Both matched at once - shouldn't normally happen since only one
        # amount can be true per run. Trust whichever scored higher, but
        # this is a sign the two pictures should be cropped tighter/more
        # distinctly from each other.
        log(f"[shard] Both 'x1' (score {score_x1:.2f}) and 'x2' (score {score_x2:.2f}) "
            f"matched at once - using whichever scored higher. Consider recropping "
            f"them tighter so this doesn't happen.", "warning")
        return 2 if score_x2 >= score_x1 else 1

    if found_x2:
        return 2
    if found_x1:
        return 1

    log(f"[shard] Neither 'x1' nor 'x2' found (best scores: x1={score_x1:.2f}, "
        f"x2={score_x2:.2f}) - no shard reward this run, or the result screen "
        f"isn't showing yet.")
    return None
