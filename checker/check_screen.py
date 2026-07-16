"""
check_screen.py
------------------
Diagnostic tool: checks a set of known "landmark" icons against your
CURRENT screen and tells you which one(s) match - i.e. what page the bot
thinks you're actually on right now, using the exact same detection
logic the launcher itself uses (screen.find_icon / game_navigator).

Run this any time to sanity-check "does the bot correctly recognize the
page I'm looking at?" without running the full automated sequence.

USAGE (from the repo root):
    python checker/check_screen.py
        Checks a default set of landmarks covering each known page.

    python checker/check_screen.py menu_play create_room mode_story
        Checks only the icons you list.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import game_navigator as nav

# Default landmark icons, each representing a distinct known page/screen.
# Add your own here if you capture new landmarks for other pages.
DEFAULT_LANDMARKS = {
    "menu_play": "Main menu / lobby",
    "create_room": "Create Room button visible",
    "mode_story": "Mode-selection page (Story tab)",
    "mode_squadron": "Mode-selection page (Squadron tab)",
    "world_gt_city": "Story world list",
    "diff_normal": "Difficulty selector (Normal)",
    "diff_hard": "Difficulty selector (Hard)",
    "chapter_1": "Chapter list",
    "victory_screen": "Post-match result screen (win)",
    "defeat_screen": "Post-match result screen (loss)",
    "leave_button": "Leave button on the result screen",
}


def main():
    keys = sys.argv[1:]
    landmarks = {k: DEFAULT_LANDMARKS.get(k, "(custom)") for k in keys} if keys else DEFAULT_LANDMARKS

    print("Checking your current screen against known landmarks...\n")
    results = []
    for key, description in landmarks.items():
        try:
            found, x, y, score = nav.find_icon(key)
        except FileNotFoundError as e:
            print(f"  '{key}': {e}")
            continue
        results.append((key, description, found, score))

    if not results:
        print("No valid landmarks to check - see errors above.")
        return

    results.sort(key=lambda r: r[3], reverse=True)

    print(f"{'Icon':<18} {'Represents':<32} {'Match?':<8} Score")
    print("-" * 70)
    for key, description, found, score in results:
        marker = "YES" if found else "no"
        print(f"{key:<18} {description:<32} {marker:<8} {score:.3f}")

    matched = [r for r in results if r[2]]
    if matched:
        best = matched[0]
        print(f"\nBest guess: you're on '{best[1]}' (matched '{best[0]}', score {best[3]:.2f})")
        if len(matched) > 1:
            others = ", ".join(f"'{r[0]}'" for r in matched[1:])
            print(f"(Also matched: {others} - normal if those icons are persistent "
                  f"elements that stay visible across multiple pages.)")
    else:
        print("\nNo known landmark matched at all. Either you're on a page with no "
              "captured landmark yet, or something needs a threshold/recapture check - "
              "try checker/check_icon.py on the specific icon you expected to match.")


if __name__ == "__main__":
    main()
