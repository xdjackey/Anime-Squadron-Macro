"""
compare_icons.py
------------------
Tests several icons against the current screen at once and prints their
scores side by side. Use it to check if similar-looking icons (mode
tabs, Normal vs Hard, etc.) are being confused with each other.

Usage: python checker/compare_icons.py <key1> <key2> ...
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import game_navigator as nav


def main():
    keys = sys.argv[1:]
    if not keys:
        print("Usage: python checker/compare_icons.py <key1> <key2> ...")
        print("Example: python checker/compare_icons.py mode_story mode_squadron mode_raid mode_challenge mode_invasion")
        return

    results = []
    for key in keys:
        try:
            found, x, y, score = nav.find_icon(key)
            results.append((key, score, found, x, y))
        except FileNotFoundError as e:
            print(f"'{key}': {e}")

    results.sort(key=lambda r: r[1], reverse=True)

    print(f"\n{'Icon':<20} {'Score':<8} {'Location':<16} {'Above threshold?'}")
    print("-" * 60)
    for key, score, found, x, y in results:
        marker = "YES" if found else "no"
        loc = f"({x}, {y})" if found else "-"
        print(f"{key:<20} {score:.3f}    {loc:<16} {marker}")

    # Two icons matching the same spot is the real sign of confusion -
    # not just having similar scores.
    close_pairs = []
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            k1, s1, f1, x1, y1 = results[i]
            k2, s2, f2, x2, y2 = results[j]
            if f1 and f2 and abs(x1 - x2) < 40 and abs(y1 - y2) < 40:
                close_pairs.append((k1, k2))

    if close_pairs:
        print("\nThese pairs matched to the SAME location - genuine confusion:")
        for k1, k2 in close_pairs:
            print(f"  '{k1}' and '{k2}'")
        print("Re-crop these tighter around just what's different (text/icon),")
        print("not the shared button shape/background.")
    elif len(results) >= 2:
        gap = results[0][1] - results[1][1]
        print(f"\nGap between top two scores: {gap:.3f}, but they matched DIFFERENT locations -")
        print("likely each correctly found its own button. Close scores alone aren't a")
        print("problem if the locations are right.")


if __name__ == "__main__":
    main()
