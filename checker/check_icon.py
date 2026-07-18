"""
check_icon.py
--------------
Tests ONE icon against your current screen, without clicking - use it to
see why an icon isn't matching.

Usage: get the game to the right screen first, then run
    python checker/check_icon.py <icon_key>
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import game_navigator as nav


def main():
    if len(sys.argv) < 2:
        print("Usage: python checker/check_icon.py <icon_key>")
        print("Example: python checker/check_icon.py create_room")
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
