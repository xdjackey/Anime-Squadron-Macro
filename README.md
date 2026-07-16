# Anime Squadron Macro

A launcher that plays Anime Squadron for you. It docks a small control panel
next to your Roblox window, and once you tell it what to run, it clicks
through the menus, plays the match, and repeats - so you don't have to sit
there doing it yourself.

## What you need
- Windows
- Roblox already installed

## Getting started

Open Roblox first, then double-click the .exe to run it. Nothing to
install - the panel will dock itself to the side of your screen
automatically.

## How to use it

1. Pick a **Mode** (Story, Squadron, Challenge, Raid, or Invasion) and fill
   in the fields under it.
2. Set **Runs** to how many times you want it repeated, or leave it blank
   to run until you press Stop.
3. Click **+ ADD TASK** to add it to the Task List. You can queue up
   several tasks in a row - it'll do them one after another.
4. Click **▶ START** when you're ready.

A few buttons worth knowing:
- **END CURRENT TASK** - stops the task that's running right now and
  moves on to the next one in the queue.
- **SETTINGS** - set a Trait Shard farming target for each stage, or a
  Discord webhook if you want a screenshot sent after every match.
- **AUTO-QUEUE ALL TRAIT SHARD STAGES** - queues up every stage that drops
  Trait Shards in one click.
- The **–** button hides the panel, and the **✕** button closes it.

Keyboard shortcuts (work even if Roblox is focused):
- **F6** - Start / continue
- **F7** - Pause
- **F8** - Hide/show the panel

Watch the log box at the bottom - it tells you what it's finding (or not
finding) on screen, which is the easiest way to tell if something's wrong.

## Project layout
- `launcher.py` - the entry point, run this to start the app.
- `backend/` - all the automation logic: finding/clicking things on screen,
  running missions, tracking Trait Shard progress, and so on.
- `ui/` - the control panel itself (windows, buttons, colors).
- `checker/` - small standalone tools for troubleshooting icon detection,
  run individually when something isn't being recognized (e.g.
  `python checker/check_icon.py create_room`).

