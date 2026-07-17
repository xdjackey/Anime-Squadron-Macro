"""
capture_icons.py
----------------------------
Walks you through taking a picture of every button/screen the
launcher needs to recognize, one at a time. This only needs to be
done once (or again if you switch to a different monitor).

For each item:
  1. It tells you what to get on your screen.
  2. You switch to the game, get it showing, come back and press Enter.
  3. Drag a box around it with your mouse.

Type 's' + Enter at any prompt to skip something you don't need yet
(for example, skip Squadron/Raid/Challenge/Invasion pictures if you
only play Story mode). You can run this again anytime to fill in
skipped items, or to redo one that isn't working well - just capture
the same item again and it'll overwrite the old picture.

Needs: mss, pillow, pywin32 (these get installed with pip)
"""

import os
import sys
import tkinter as tk
from PIL import Image, ImageTk
import mss

from window_lock import dock_roblox
import stage_data
import screen
import display_info
import app_paths

ASSETS_DIR = app_paths.path("launcher_assets")

# Must match UI_WIDTH and LOG_HEIGHT in launcher_ui.py exactly - this is
# what keeps capture-time and run-time window geometry identical.
UI_WIDTH = 380
LOG_HEIGHT = 200
ROBLOX_TITLE = "Roblox"

# (key, human description) - order matches the order you'll actually
# encounter these on screen during a real run.
ITEMS = [
    ("menu_play", "the Play button on the main menu"),
    ("lobby_screen", "OPTIONAL: some OTHER element that's only visible on the main menu/lobby - "
                      "pick something different from menu_play itself (a different button, logo, "
                      "or piece of text). This is a second, independent way to confirm you're back "
                      "at the lobby - if menu_play alone ever fails to match (covered by something, "
                      "borderline score), this backs it up instead of the whole farming queue "
                      "stopping over one missed detection."),
    ("create_room", "the Create Room button"),
    ("mode_story", "the Story mode tab/icon"),
    ("mode_squadron", "the Squadron mode tab/icon"),
    ("mode_raid", "the Raid mode tab/icon"),
    ("mode_challenge", "the Challenge mode tab/icon"),
    ("mode_invasion", "the Invasion mode tab/icon"),
    ("world_gt_city", "the GT City world entry - crop TIGHT around just the 'GT City' text, "
                       "not the background thumbnail (worlds can share enough visual similarity "
                       "in their background art to get confused with each other otherwise)"),
    ("world_marine_lobby", "the Marine Lobby world entry - same tight text-only crop"),
    ("world_ninja_village", "the Ninja Village world entry - same tight text-only crop"),
    ("world_eclipse_before", "the Eclipse (Before) world entry - same tight text-only crop"),
    ("world_ice_continent", "the Ice Continent world entry - same tight text-only crop"),
    ("world_infinity_train", "the Infinity Train world entry (scroll the world list down first "
                             "to see it) - same tight text-only crop"),
]

# Challenge / Raid / Invasion menu-selection icons - generated straight from
# stage_data.py so this list can never drift out of sync with what the
# dropdowns actually offer. Each is a text-only crop of that stage's name
# button, same reasoning as the world/chapter crops above.
for _challenge_key, _challenge in stage_data.CHALLENGES.items():
    ITEMS.append((
        f"challenge_{_challenge_key}",
        f"the '{_challenge['display']}' entry in the Challenge menu - crop TIGHT around just "
        f"its name text, not the background/box"
    ))
    for _stage in _challenge["stages"]:
        ITEMS.append((
            stage_data.challenge_stage_icon_key(_challenge_key, _stage),
            f"the '{_stage}' stage entry under Challenge > {_challenge['display']} - crop TIGHT "
            f"around just its name text, not the background/box"
        ))

for _raid_key, _raid in stage_data.RAIDS.items():
    ITEMS.append((
        f"raid_{_raid_key}",
        f"the '{_raid['display']}' entry in the Raid world-select menu - crop TIGHT around just "
        f"its name text, not the background/box"
    ))
    for _stage in _raid["stages"]:
        ITEMS.append((
            stage_data.raid_stage_icon_key(_raid_key, _stage),
            f"the '{_stage}' stage entry under Raid > {_raid['display']} - crop TIGHT around just "
            f"its name text, not the background/box"
        ))

for _inv_key, _inv in stage_data.INVASIONS.items():
    ITEMS.append((
        f"invasion_{_inv_key}",
        f"the '{_inv['display']}' entry in the Invasion world-select menu - crop TIGHT around "
        f"just its name text, not the background/box"
    ))
    for _stage in _inv["stages"]:
        ITEMS.append((
            stage_data.invasion_stage_icon_key(_inv_key, _stage),
            f"the '{_stage}' stage entry under Invasion > {_inv['display']} - crop TIGHT around "
            f"just its name text, not the background/box"
        ))

ITEMS += [
    ("diff_normal", "the Normal difficulty icon/toggle"),
    ("diff_hard", "the Hard difficulty icon/toggle"),
    ("chapter_1", "Chapter 1 - crop ONLY the digit '1' itself, nothing else - no "
                  "'Chapter' text, no box, no background. The word 'Chapter' and the "
                  "button box are IDENTICAL across every chapter, so including them "
                  "dilutes the one thing that actually tells chapters apart: the digit."),
    ("chapter_2", "Chapter 2 - crop ONLY the digit '2', same as above"),
    ("chapter_3", "Chapter 3 - crop ONLY the digit '3', same as above"),
    ("chapter_4", "Chapter 4 - crop ONLY the digit '4', same as above"),
    ("chapter_5", "Chapter 5 - crop ONLY the digit '5', same as above"),
    ("chapter_6", "Chapter 6 - crop ONLY the digit '6', same as above"),
    ("chapter_7", "Chapter 7 - crop ONLY the digit '7', same as above"),
    ("chapter_8", "Chapter 8 (scroll the chapter list down first) - crop ONLY the digit '8'"),
    ("chapter_9", "Chapter 9 (should still be visible or scroll a bit more) - crop ONLY the digit '9'"),
    ("chapter_10", "Chapter 10 (scroll to the bottom of the list) - crop ONLY the digits '10'"),
    ("create_room_2", "the SECOND Create Room button - on the mode/world/chapter/difficulty "
                       "screen, after everything's picked (may look slightly different from the first one)"),
    ("start_button", "the Start button in the room, after Create Room has been pressed"),
    ("victory_screen", "the VICTORY / result screen banner - crop TIGHT around JUST the word "
                        "'Victory!' itself, cutting off as much of the green checkered background "
                        "and jagged banner edges as you can. That background is nearly IDENTICAL "
                        "to the Defeat banner's (just a different color), so if too much of it is "
                        "included, a win can get misread as a loss or vice versa - the word itself "
                        "needs to dominate the crop, not the shared banner chrome around it."),
    ("defeat_screen", "the DEFEAT / result screen banner - same as above but for 'Defeat!': crop "
                       "TIGHT around just that word, cutting off the red checkered background and "
                       "banner edges as much as possible - that background nearly matches the "
                       "Victory banner's, so a loose crop risks confusing the two."),
    ("leave_button", "the Leave button on the result screen (red pill) that returns you to the "
                      "main menu/lobby - crop TIGHT around just the word 'Leave', not the pill "
                      "shape/background"),
    ("settings_gear", "the gear/settings icon (should be visible on the result screen, and "
                       "probably elsewhere too) that opens a settings menu - this is a FALLBACK "
                       "path for returning to the lobby if Leave itself ever can't be clicked"),
    ("return_to_lobby_button", "the 'Return to Lobby' button that appears INSIDE the settings "
                                "menu after clicking the gear icon - open that menu first, then "
                                "capture just this button"),
    ("trait_shard_icon", "OPTIONAL (only needed if you plan to farm Trait Shards): the "
                          "'Trait Shards' text label on a result screen showing a shard reward - "
                          "crop tight around just that text. The x1/x2 pictures below search a "
                          "small area right above wherever this is found, instead of the whole "
                          "screen, so this needs to be captured first."),
    ("trait_shard_x1", "OPTIONAL: get a result screen showing a Trait Shard drop of exactly "
                        "'x1' - crop TIGHT around ONLY the 'x1' digit badge itself, no shard icon, "
                        "no background, no 'Trait Shards' text. The icon/background shimmer and "
                        "animate between frames, which hurts the match if included - the digit "
                        "badge alone is the one part that stays visually consistent. This and "
                        "trait_shard_x2 below replace needing any OCR/calibration step at all - "
                        "shards only ever drop in amounts of 1 or 2, so just recognizing which of "
                        "these two pictures is showing tells the launcher exactly how many dropped."),
    ("trait_shard_x2", "OPTIONAL: same as above but for a drop of 'x2' - crop TIGHT around ONLY "
                        "the 'x2' digit badge, nothing else."),
]


def capture_one(key, description):
    """Show a full-screen snapshot, let the user drag-select a box, save it."""
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(cursor="cross")

    tk_img = ImageTk.PhotoImage(img)
    canvas = tk.Canvas(root, width=img.width, height=img.height, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, image=tk_img, anchor="nw")
    canvas.create_text(
        img.width // 2, 40,
        text=f"Drag a box around: {description}   (Esc to cancel)",
        fill="red", font=("Arial", 20, "bold")
    )

    start = {}
    rect_id = {"id": None}
    saved = {"ok": False}

    def on_press(event):
        start["x"], start["y"] = event.x, event.y
        if rect_id["id"]:
            canvas.delete(rect_id["id"])
        rect_id["id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=2)

    def on_drag(event):
        canvas.coords(rect_id["id"], start["x"], start["y"], event.x, event.y)

    def on_release(event):
        x1, y1 = start["x"], start["y"]
        x2, y2 = event.x, event.y
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if right - left < 5 or bottom - top < 5:
            print("Selection too small, try again.")
            return
        os.makedirs(ASSETS_DIR, exist_ok=True)
        path = os.path.join(ASSETS_DIR, f"{key}.png")
        img.crop((left, top, right, bottom)).save(path)
        saved["ok"] = True
        print(f"Saved {path}  ({right - left}x{bottom - top} px)")
        root.destroy()

    def on_escape(event):
        print("Cancelled.")
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.mainloop()
    return saved["ok"]


def main():
    print("=== Launcher asset capture ===")
    display_info.check_scaling(log=print)

    hwnd, roblox_width, roblox_height, screen_w, screen_h = dock_roblox(
        UI_WIDTH, ROBLOX_TITLE, log_height=LOG_HEIGHT)
    if hwnd is None:
        print(f"Warning: couldn't find a window titled like '{ROBLOX_TITLE}'.")
        print("Open Roblox first, then re-run this - otherwise your captures won't")
        print("line up with where launcher_ui.py will actually look for them.\n")
    else:
        print(f"Docked Roblox to {roblox_width}x{roblox_height} at (0, 0) - the exact layout")
        print("launcher_ui.py will use at runtime, so your captures will line up.\n")
        screen.save_capture_reference(roblox_width, roblox_height)
        print(f"Saved capture reference size ({roblox_width}x{roblox_height}) - this lets icon "
              f"matching adapt automatically if you ever run the launcher on a different "
              f"monitor/resolution.\n")

    # QoL: pass specific keys as arguments to jump straight to just those,
    # instead of stepping through the whole list with 's' to skip each one.
    #   python backend/capture_icons.py chapter_8 chapter_9 start_button
    requested = sys.argv[1:]
    if requested:
        items_to_run = [(k, d) for k, d in ITEMS if k in requested]
        missing = set(requested) - {k for k, _ in items_to_run}
        if missing:
            print(f"Warning: these aren't recognized keys and will be skipped: {', '.join(missing)}")
        print(f"Capturing only: {', '.join(k for k, _ in items_to_run)}\n")
    else:
        items_to_run = ITEMS
        print(f"Capturing {len(items_to_run)} icons in order. Type 's' + Enter to skip any one.\n")

    done = 0
    skipped = 0
    for key, description in items_to_run:
        existing = os.path.exists(os.path.join(ASSETS_DIR, f"{key}.png"))
        tag = " (already captured - press Enter to redo, or 's' to keep as-is)" if existing else ""
        choice = input(f"Next: {description}{tag}\nPress Enter to capture, or 's' to skip: ").strip().lower()

        if choice == "s":
            skipped += 1
            print("Skipped.\n")
            continue

        print("Switch to your game, get it visible, then come back here.")
        input("Press Enter when ready to capture the screen... ")

        if capture_one(key, description):
            done += 1
        print()

    print(f"Done. Captured {done} icon(s), skipped {skipped}.")
    print(f"Files are in the '{ASSETS_DIR}/' folder. Re-run this anytime to fill in the rest.")


if __name__ == "__main__":
    main()
