"""
click_logger.py
------------------
Logs every mouse click (position + timestamp) to a running list in its
own window. Run this in a SEPARATE terminal while you test the launcher -
it keeps logging every click (yours or the script's) until you stop it
with Ctrl+C.

Use this to compare:
  - Where you click manually vs. where the log says the script clicked
  - Whether a click even registered as a click at all (sometimes an
    attempted click doesn't generate an OS-level click event at all,
    which is a different problem than "clicked but the game ignored it")

Requires: pynput   (pip install pynput)
"""

import time
from pynput import mouse


def on_click(x, y, button, pressed):
    if pressed:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] CLICK at ({x}, {y})  button={button}")


def main():
    print("Click logger running - every click (manual or scripted) will print here.")
    print("Leave this window open while you test. Press Ctrl+C to stop.\n")
    with mouse.Listener(on_click=on_click) as listener:
        listener.join()


if __name__ == "__main__":
    main()
