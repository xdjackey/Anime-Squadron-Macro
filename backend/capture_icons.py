"""
capture_icons.py
----------------------------
Walks you through capturing a picture of every button/screen the
launcher needs to recognize, one at a time: it names what to get, you
switch to the game and press Enter, then drag a box around it.

Type 's' + Enter to skip anything you don't need yet. Safe to re-run
anytime to fill in skipped items or redo a bad capture.
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

# Must match UI_WIDTH and LOG_HEIGHT in launcher_ui.py exactly, so
# capture-time and run-time window geometry are identical.
UI_WIDTH = 380
LOG_HEIGHT = 200
ROBLOX_TITLE = "Roblox"

# (key, human description), in the order you'll encounter them in a run.
ITEMS = [
    ("menu_play", "the Play button on the main menu"),
    ("lobby_screen", "OPTIONAL: a DIFFERENT lobby-only element (not menu_play) - a backup way "
                      "to confirm you're at the lobby if menu_play alone ever misses."),
    ("create_room", "the Create Room button"),
    ("mode_story", "the Story mode tab/icon"),
    ("mode_squadron", "the Squadron mode tab/icon"),
    ("mode_raid", "the Raid mode tab/icon"),
    ("mode_challenge", "the Challenge mode tab/icon"),
    ("mode_invasion", "the Invasion mode tab/icon"),
    ("world_gt_city", "the GT City world entry - crop TIGHT around just the 'GT City' text, "
                       "not the background thumbnail (worlds can look similar otherwise)"),
    ("world_marine_lobby", "the Marine Lobby world entry - same tight text-only crop"),
    ("world_ninja_village", "the Ninja Village world entry - same tight text-only crop"),
    ("world_eclipse_before", "the Eclipse (Before) world entry - same tight text-only crop"),
    ("world_ice_continent", "the Ice Continent world entry - same tight text-only crop"),
    ("world_infinity_train", "the Infinity Train world entry (scroll the world list down first "
                             "to see it) - same tight text-only crop"),
]

# Challenge/Raid/Invasion icons, generated from stage_data.py so this
# list can't drift out of sync with the dropdowns. Text-only crops.
for _challenge_key, _challenge in stage_data.CHALLENGES.items():
    ITEMS.append((
        f"challenge_{_challenge_key}",
        f"the '{_challenge['display']}' entry in the Challenge menu - crop TIGHT to just its name text"
    ))
    for _stage in _challenge["stages"]:
        ITEMS.append((
            stage_data.challenge_stage_icon_key(_challenge_key, _stage),
            f"the '{_stage}' stage under Challenge > {_challenge['display']} - crop TIGHT to just its name text"
        ))

for _raid_key, _raid in stage_data.RAIDS.items():
    ITEMS.append((
        f"raid_{_raid_key}",
        f"the '{_raid['display']}' entry in the Raid world-select menu - crop TIGHT to just its name text"
    ))
    for _stage in _raid["stages"]:
        ITEMS.append((
            stage_data.raid_stage_icon_key(_raid_key, _stage),
            f"the '{_stage}' stage under Raid > {_raid['display']} - crop TIGHT to just its name text"
        ))

for _inv_key, _inv in stage_data.INVASIONS.items():
    ITEMS.append((
        f"invasion_{_inv_key}",
        f"the '{_inv['display']}' entry in the Invasion world-select menu - crop TIGHT to just its name text"
    ))
    for _stage in _inv["stages"]:
        ITEMS.append((
            stage_data.invasion_stage_icon_key(_inv_key, _stage),
            f"the '{_stage}' stage under Invasion > {_inv['display']} - crop TIGHT to just its name text"
        ))

ITEMS += [
    ("diff_normal", "the Normal difficulty icon/toggle"),
    ("diff_hard", "the Hard difficulty icon/toggle"),
    ("chapter_1", "Chapter 1 - crop ONLY the digit '1', nothing else (no 'Chapter' text, "
                  "no box) - those are identical across every chapter, so only the digit tells them apart."),
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
    ("victory_screen", "the VICTORY banner - crop TIGHT around JUST the word 'Victory!', cutting "
                        "off as much of the checkered background as you can (it's nearly identical "
                        "to Defeat's, just a different color, so a loose crop risks confusing the two)."),
    ("defeat_screen", "the DEFEAT banner - same as above but for 'Defeat!'."),
    ("retry_button", "the Retry button on the result screen - crop TIGHT around just the word "
                      "'Retry', not its background. Retry/Leave are used (instead of the Victory/"
                      "Defeat banners) to detect that a match has ended, since they're more reliable."),
    ("leave_button", "the Leave button on the result screen (red pill) - crop TIGHT around just "
                      "the word 'Leave', not the pill shape/background"),
    ("settings_gear", "the gear/settings icon on the result screen - fallback path for returning "
                       "to the lobby if Leave can't be clicked"),
    ("return_to_lobby_button", "the 'Return to Lobby' button INSIDE the settings menu - open that "
                                "menu first, then capture just this button"),
    ("trait_shard_icon", "OPTIONAL (only if farming Trait Shards): the 'Trait Shards' text label "
                          "on a result screen showing a shard reward - crop tight around just that "
                          "text. Capture this before x1/x2 below, which search near it."),
    ("trait_shard_x1", "OPTIONAL: a result screen showing a Trait Shard drop of exactly 'x1' - "
                        "crop TIGHT around ONLY the 'x1' digit badge, no icon/background/text "
                        "(those shimmer/animate and hurt the match)."),
    ("trait_shard_x2", "OPTIONAL: same as above but for a drop of 'x2'."),
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

    # Pass specific keys as arguments to jump straight to just those:
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
