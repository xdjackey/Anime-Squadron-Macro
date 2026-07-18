"""
check_shard_read.py
----------------------
Checks whether the "x1"/"x2" shard-drop badge is showing on your current
screen and prints what it found.

Usage: get a result screen with a shard reward up, then run
    python checker/check_shard_read.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import trait_shard


def main():
    count = trait_shard.read_shard_count()
    if count is None:
        print("Neither 'x1' nor 'x2' matched (no shard reward this run, or the "
              "pictures need recapturing/recropping).")
    else:
        print(f"Read shard count: {count}")


if __name__ == "__main__":
    main()
