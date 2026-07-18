"""
click_logger.py
------------------
Prints every mouse click (position + timestamp) as it happens. Run in a
separate terminal while testing the launcher, to see where clicks (yours
or the script's) actually land. Ctrl+C to stop.
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
