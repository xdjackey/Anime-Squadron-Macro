# Changelog

## v1.6.5

### ✨ Added
- 🔄 Auto-updater - checks GitHub for a newer release on startup and, if you
  agree, downloads and swaps in the new .exe automatically.
- 🔔 Discord notifications split into 3 independent toggles instead of one:
  screenshot after each victory/defeat, a message when a task finishes, and
  a message every time a Trait Shard drop is actually counted.

### 🔧 Fixed
- 🎯 Trait Shard detection reliability - the "x1"/"x2" drop-amount search is
  now anchored to a small area right above the "Trait Shards" label instead
  of scanning the whole screen. Fixes two things at once: other reward
  drops on the same result screen showing their own "x1"/"x2" badge no
  longer get mistaken for a shard drop, and x1 vs. x2 misreads caused by
  the shard icon's shimmering/animated background no longer dominate the
  match score.
- ⚡ Trait Shard detection speed - narrowed the scale-search range and step
  count specifically for the shard-related icons (they're always captured
  together in one session, so they don't need the wide range built for
  covering every user's different monitor setup). Detection now takes
  roughly a quarter of the time it used to.
- ⏱️ Shard count is now read the instant the victory/defeat screen is
  detected, instead of after a Discord screenshot dispatch and an
  unconditional 150ms refocus delay ran first - the reward badge can be
  transient, so anything delaying the read risked missing it.
- 🔢 Discord messages (and a couple of log lines) getting stuck showing the
  shard count from the START of a farming session (e.g. "0/30") for the
  entire run, even as shards were actually being banked in the background -
  caused by reusing a label string computed once before the loop started
  instead of recomputing it fresh after each run.
- 🏷️ Title bar was still showing "V1.0" long after the app had moved on -
  it now reads the version from the same single place the auto-updater
  does, instead of a separate hardcoded string nobody remembered to bump.

## v1.6.0

### 🐛 Bugs reported
- Leave button sometimes clashed with the "2-step" Settings ➜ Return to Lobby
  fallback - the fallback would still run even when Leave had actually worked.
- Icon detection failing for players not on a 27" 1440p monitor - buttons
  the launcher should recognize were never matching on their setup.
- Visible gaps at the edges of the Roblox window, and the END CURRENT TASK /
  SETTINGS buttons visually overlapping each other in the control panel.

### ✨ Added
- 🔢 Live shard counter (`banked/target`) shown next to each trait shard farm
  task - replaces the old static "(no run limit)" text and updates
  automatically after every victory/defeat screen.
- ⚔️ Difficulty selection (Normal/Hard) for Raid mode - GT City, Eclipse, and
  Infinity Train all show it now.
- 🙈 Hide/show button for the whole UI (the "–" button), plus an **F8**
  hotkey to bring it back.
- 📁 Repo reorganized into `backend/`, `ui/`, and `checker/` folders instead
  of one flat folder of 25 files.
- 📦 First real build: `AnimeSquadronMacro.exe`, published with this release.
- 📝 `AnimeSquadronMacro.spec` committed, so the exe can be rebuilt with the
  exact same PyInstaller configuration.

### 🗑️ Removed
- TASK PROGRESS bar, TOTAL PROGRESS bar, and ELAPSED TIME from the Status
  card (and all the now-unused tracking code behind them).
- Icons on the END CURRENT TASK and SETTINGS buttons - plain text now.
- The extra "select stage" click for single-stage challenges (Katakara
  Bridge, The Hero Hunter) - goes straight to Create Room since there's
  nothing else to pick.
- Install/build instructions from the README - it's exe-only now, so there's
  nothing to set up before running it.

### 🔧 Fixed
- 🏃 Leave button vs. the Settings ➜ Return to Lobby fallback clashing - a
  successful Leave click was sometimes mistaken for a failure, so the
  fallback ran again right on top of it.
- 🧩 END CURRENT TASK and SETTINGS buttons had zero spacing and the same flat
  background, so they visually merged into one blob - gave them a real gap.
- 📐 Gap between the Roblox window and the control panel - the overlap used
  to hide Windows' invisible window-border margin was too small on the
  right edge (now matches what the log panel already used on the bottom).
- 🎬 The title-bar overlay used a hardcoded guess (34px) for its height
  instead of the `titlebar_height()` helper that already existed but was
  never actually wired up - could leave a seam on other systems.
- 🙈 `.gitignore` was using inline `pattern  # comment` lines, which Git's
  `.gitignore` syntax doesn't support - every single "never commit this"
  rule (Discord webhook URL, personal farming progress, captured icons)
  was silently not matching anything. Found while preparing this release.

### ⚠️ Reported fixes not yet confirmed
- ⏱️ The Leave-button clash above was first patched by rechecking the lobby
  for 2 seconds before falling back - but that turned out to still be too
  short for genuinely slow (but successful) transitions, so it was bumped
  to 10 seconds. Not yet confirmed this fully resolves it.
- 🖥️ The icon-detection fix (widened `DEFAULT_SCALE_RANGE` to `(0.65, 1.30)`
  and `SCALE_STEPS` to `16`) was reported by a user on a different monitor
  setup - not yet confirmed it fixed detection for them.

### ✏️ Renamed
- "Banked" ➜ "Current" in the Trait Shard Targets manual-adjustment field.
- Trait Shard Targets description shortened to one plain-language line.
