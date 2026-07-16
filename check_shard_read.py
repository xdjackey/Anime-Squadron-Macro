"""
check_shard_read.py
----------------------
A troubleshooting tool: checks whether the "x1" or "x2" shard-drop
picture is showing on your CURRENT screen, and prints what it found.

HOW TO USE IT:
    Get a result screen with a shard reward showing, then run:
        python check_shard_read.py
"""

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
