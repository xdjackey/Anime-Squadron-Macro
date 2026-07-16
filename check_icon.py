"""
check_icon.py
--------------
Diagnostic tool: tests ONE icon against whatever is on your screen right
now, without clicking anything. Use this to figure out whether a failing
icon is (a) genuinely not on screen yet at that point, (b) a bad/loose
capture, or (c) just barely below the threshold.

USAGE:
  1. Manually get your game to the exact screen where the icon SHOULD be
     visible (e.g. click Create Room yourself and wait for it to load).
  2. Run:
       python check_icon.py create_room
  3. Read the score it prints.

Requires: mss, numpy, opencv-python
"""

import sys
import game_navigator as nav


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_icon.py <icon_key>")
        print("Example: python check_icon.py create_room")
        print("\nAvailable keys are the .png filenames (without .png) in launcher_assets/")
        return

    key = sys.argv[1]
    print(f"Checking for '{key}' on your CURRENT screen (no click, just testing)...")

    try:
        found, x, y, score = nav.find_icon(key)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return

    print(f"Best match score: {score:.3f}   (threshold used for this icon: {nav._threshold_for(key, None)})")

    if found:
        print(f"MATCH - would click at ({x}, {y})")
    else:
        print("NOT a confident match.")
        if score < 0.5:
            print("Score is quite low - the icon most likely isn't visible on screen right")
            print("now (wrong screen/menu, still loading, or covered by something).")
            print("Get the game to the exact screen where this should appear, then re-run this.")
        else:
            print("Score is moderate - it might be the right spot but a loose/imperfect capture.")
            print("Try re-capturing this icon more tightly (just the icon, no extra background),")
            print("or check Windows display scaling is set to 100%.")


if __name__ == "__main__":
    main()
