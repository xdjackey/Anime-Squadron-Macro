"""
launcher.py
-----------
This is the main file you run - it's the brain of the whole app.

The visual look of the app (windows, buttons, colors) lives in ui/ui.py.
The actual automation/game-logic modules live in backend/. This file
handles everything behind the scenes: asking Windows for admin
permission, the F6/F7 keyboard shortcuts, starting/stopping, keeping
Roblox in focus, and walking through each mission step by step.
"""

import os
import sys

# backend/ and ui/ modules import each other by plain name (e.g.
# "import stage_data"), so both folders need to be on sys.path before
# anything below is imported - done here, first, rather than turning
# every file in the project into a proper nested package.
_ROOT = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
for _sub in ("backend", "ui"):
    sys.path.insert(0, os.path.join(_ROOT, _sub))

import ctypes
import time
import threading
import tkinter as tk

import keyboard
import game_navigator as nav
import screen
import mouse
import discord_webhook
import trait_shard
import shard_progress
import manual_credits
import stage_data
import display_info
import reset_clock
from window_lock import find_window, bring_to_front
from ui import LauncherUI, ROBLOX_TITLE
from mission_queue import Mission

RESULT_TIMEOUT = 180.0   # how long a single match is allowed to run before we give up waiting
STEP_PAUSE = 2.0

# Speeds up every click in the Play-through-Start navigation sequence.
# The default click timing (mouse.py) assumes a button might need a
# hover-animation to finish before it registers - true for some Roblox
# UI (confirmed: Create Room needs this, breaking the sequence when
# rushed too hard). This is a modest speedup over the default (0.45s /
# 0.15s), not an aggressive one - if a specific button still needs the
# full default timing, it should get its own explicit override rather
# than lowering these further for everything.
NAV_CLICK_PAUSE = 0.3
NAV_MOVE_DURATION = 0.12
WAIT_FOR_ROBLOX_INTERVAL = 1.5
CHAPTER_SCROLL_AMOUNT = -150
CHAPTER_MAX_SCROLLS = 25

# Anti-idle: periodically nudge the mouse and click, then put it back
# exactly where it was, purely so the game doesn't consider the session
# AFK during long unattended stretches. Only fires while nothing else is
# actively running (see _anti_idle_loop) so it can't misclick mid-sequence.
ANTI_IDLE_INTERVAL_SECONDS = 600  # 10 minutes
ANTI_IDLE_JITTER_OFFSET = (12, 12)

# Worlds beyond the first 5 aren't visible without scrolling the world
# list first - same idea as chapters 8-10. Ice Continent is the last one
# reliably visible before any scrolling, so it's used as the hover anchor.
WORLDS_NEEDING_SCROLL = {"infinity_train"}
WORLD_LIST_HOVER_ANCHOR = "world_ice_continent"


def _ensure_admin():
    """Re-launch elevated so Windows does not block clicks to elevated Roblox."""
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False

    if is_admin:
        return

    params = " ".join(f'"{arg}"' for arg in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{sys.argv[0]}" {params}', None, 1
    )
    sys.exit(0)


class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.stop_requested = False
        self.end_task_requested = False
        self._anti_idle_started = False
        self._waiting_thread_started = False
        self._closing = False

        self.ui = LauncherUI(root, on_start_stop=self.on_go_or_stop, on_end_task=self.on_end_task,
                              on_close=self.on_close)
        self._register_hotkeys()

        display_info.check_scaling(log=self.ui.log)
        manual_credits.apply_credits(log=self.ui.log)

        if find_window(ROBLOX_TITLE) is None:
            self._start_wait_for_roblox_thread()

        threading.Thread(target=self._shard_reset_loop, daemon=True).start()

    # ---------- Hotkeys / lifecycle ----------

    def _register_hotkeys(self):
        keyboard.add_hotkey("f6", lambda: self.root.after(0, self.start_hotkey))
        keyboard.add_hotkey("f7", lambda: self.root.after(0, self.stop_hotkey))
        keyboard.add_hotkey("f8", lambda: self.root.after(0, self.ui.toggle_ui_visibility))

    def _start_wait_for_roblox_thread(self):
        if self._waiting_thread_started:
            return
        self._waiting_thread_started = True
        threading.Thread(target=self._wait_for_roblox, daemon=True).start()

    def _wait_for_roblox(self):
        while True:
            if find_window(ROBLOX_TITLE) is not None:
                self.ui.log("Roblox detected - docking now.", "success")
                self.root.after(0, self.ui.dock_windows)
                return
            time.sleep(WAIT_FOR_ROBLOX_INTERVAL)

    def _anti_idle_loop(self):
        """Starts running the first time Start is pressed (not at app
        launch) and then keeps going for the rest of the session. Every
        ANTI_IDLE_INTERVAL_SECONDS, if nothing else is currently running
        (self.running is False - so this never fires mid-mission), nudges
        the mouse a few pixels, clicks, and puts the cursor back exactly
        where it was. Purely to stop the game from treating a long
        unattended stretch (between queued runs, or after the queue
        finishes) as AFK."""
        while not self._closing:
            # Sleep in short increments so app close / a Start click don't
            # have to wait out a full 10-minute sleep to be noticed.
            slept = 0.0
            while slept < ANTI_IDLE_INTERVAL_SECONDS:
                if self._closing:
                    return
                time.sleep(0.5)
                slept += 0.5

            if self._closing or self.running:
                continue

            try:
                hwnd = find_window(ROBLOX_TITLE)
                if hwnd is None:
                    continue
                bring_to_front(hwnd)
                time.sleep(0.15)
                if self.running:
                    continue  # a mission started during that brief focus wait - bail out
                self.ui.log("Anti-idle: nudging the mouse to prevent an AFK kick.", "info")
                mouse.jitter_and_click(offset=ANTI_IDLE_JITTER_OFFSET)
            except Exception as e:
                self.ui.log(f"Anti-idle nudge failed (non-fatal): {e}", "warning")

    def _shard_reset_loop(self):
        """Runs for the lifetime of the app, checking every 30 seconds
        whether the daily 5pm-Pacific Trait Shard reset boundary has
        just passed. Fires at most once per actual reset - see
        reset_clock.check_and_consume_reset(). Safe to run even while a
        farm is active; the check itself is cheap and clearing progress
        mid-farm just means the next run's count starts the new day's
        tally, which is correct behavior right at a real reset."""
        while not self._closing:
            slept = 0.0
            while slept < 30.0:
                if self._closing:
                    return
                time.sleep(0.5)
                slept += 0.5

            try:
                if reset_clock.check_and_consume_reset():
                    shard_progress.clear_all()
                    self.ui.log("Daily Trait Shard reset detected (5pm Pacific) - all banked "
                                "progress has been cleared.", "warning")
            except Exception as e:
                self.ui.log(f"Shard reset check failed (non-fatal): {e}", "warning")

    def on_close(self):
        self.stop_requested = True
        self._closing = True
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.ui.destroy()

    # ---------- Start / stop ----------

    def start_hotkey(self):
        if not self.running:
            self.on_go_or_stop()

    def stop_hotkey(self):
        if self.running:
            self.stop_requested = True
            self.ui.log("Pause requested (F7).", "warning")

    def on_go_or_stop(self):
        if self.running:
            self.stop_requested = True
            self.ui.log("Pause requested - stopping as soon as possible.", "warning")
            return

        queue = self.ui.get_queue()
        if queue.is_empty():
            self.ui.log("Queue is empty - add at least one mission before starting.", "warning")
            return

        self.running = True
        self.stop_requested = False
        self.ui.set_running_state(True)
        self.ui.log("Starting / resuming - the queue continues from wherever it left off.", "success")

        if not self._anti_idle_started:
            self._anti_idle_started = True
            threading.Thread(target=self._anti_idle_loop, daemon=True).start()

        threading.Thread(target=self.run_queue, daemon=True).start()

    def _log_debug(self, text, level=None):
        """Same as self.ui.log, but only actually shows up if Verbose
        Logging is turned on (Settings popup) - used for routine
        step-by-step navigation chatter ('Looking for Play button...',
        'Selecting world: gt_city', etc.) that's useful when debugging
        but clutters the log during normal use. Results, errors, and
        milestones always use self.ui.log directly regardless of this
        setting."""
        if self.ui.is_verbose_enabled():
            self.ui.log(text, level)

    def _check_stop(self):
        if self.stop_requested:
            self.ui.log("Stopped by user.", "warning")
            return True
        return False

    def on_end_task(self):
        """Handler for the 'End Current Task' button/hotkey - unlike
        Stop, this doesn't pause the whole queue or preserve the current
        task for resuming. It just wraps up the CURRENT task right now
        (as if its target/repeat_count had been reached) and moves on to
        whatever's next in the queue, without stopping automation."""
        if not self.running:
            self.ui.log("Nothing is running right now.", "warning")
            return
        self.end_task_requested = True
        self.ui.log("Ending the current task early - moving to the next queued task...", "warning")

    def _check_end_task(self):
        if self.end_task_requested:
            self.end_task_requested = False
            return True
        return False

    def _confirm_lobby(self, timeout):
        """Checks whether we're back at the main menu/lobby. Normally
        this just means 'menu_play' matched - but if the optional
        'lobby_screen' landmark has also been captured, either one
        matching counts, so a single borderline/missed detection on one
        icon can't be mistaken for 'not actually at the lobby' as long
        as the other confirms it. Silently skips lobby_screen if it was
        never captured (it's optional) rather than erroring."""
        keys = ["menu_play"]
        try:
            screen._load_template("lobby_screen")
            keys.append("lobby_screen")
        except FileNotFoundError:
            pass
        return nav.wait_for_any_screen(keys, timeout=timeout, log=self.ui.log,
                                       stop_check=self._check_stop) is not None

    def _sleep_interruptible(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self._check_stop():
                return True
            time.sleep(0.02)
        return False

    # ---------- Roblox helpers ----------

    def _refocus_roblox(self):
        hwnd = find_window(ROBLOX_TITLE)
        if hwnd is not None:
            bring_to_front(hwnd)
            time.sleep(0.15)
            return True
        self.ui.log(f"Couldn't find a '{ROBLOX_TITLE}' window to focus - clicks may not register.", "warning")
        return False

    def _maybe_send_discord_screenshot(self, message):
        """Fires a Roblox-only screenshot to the configured Discord
        webhook, if the user's turned that on and set a URL. Silently
        does nothing otherwise - this should never block or fail a
        mission just because Discord isn't configured."""
        if not self.ui.is_discord_enabled():
            return
        url = self.ui.get_discord_webhook_url()
        if not url:
            return
        bbox = self.ui.get_roblox_bbox()
        if bbox is None:
            self.ui.log("Discord: Roblox window position unknown - skipping screenshot.", "warning")
            return
        discord_webhook.send_screenshot_async(url, bbox, message=message, log=self.ui.log)

    # ---------- Navigation sequence ----------

    def run_queue(self):
        """Pulls missions off the queue one at a time. Each mission gets
        entered, repeated up to its own repeat_count (counting each
        victory/defeat result), then we leave to the lobby and move on
        to the next queued mission. Stops early (leaving remaining
        missions untouched in the queue) if the user hits Stop."""
        queue = self.ui.get_queue()
        missions_snapshot = queue.all()
        self._total_tasks = len(missions_snapshot)
        self._task_index = 0

        try:
            while not queue.is_empty():
                if self._check_stop():
                    return
                self._task_index += 1
                mission = queue.pop_next()
                self.root.after(0, self.ui._refresh_queue_listbox)
                self.root.after(0, lambda ti=self._task_index, tt=self._total_tasks:
                                 self.ui.set_status_line(f"Running Task {ti} / {tt}"))
                self.root.after(0, lambda lbl=mission.label(): self.ui.set_current_task_label(lbl))
                if not self._run_mission(mission):
                    # Whether this was a deliberate Stop or a hard failure
                    # (like never confirming the lobby after Leave), push
                    # the mission back so nothing is silently lost from
                    # the queue - Start (F6) resumes with it either way.
                    queue.push_front(mission)
                    self.root.after(0, self.ui._refresh_queue_listbox)
                    if self.stop_requested:
                        self.root.after(0, lambda lbl=mission.label():
                                         self.ui.set_current_task_label(f"Paused: {lbl}"))
                    else:
                        self.root.after(0, lambda lbl=mission.label():
                                         self.ui.set_current_task_label(f"Stopped on error: {lbl}"))
                    return
            self.root.after(0, lambda: self.ui.set_status_line("Queue finished."))
            self.root.after(0, lambda: self.ui.set_current_task_label("Nothing running - queue finished."))
        finally:
            self.running = False
            self.stop_requested = False
            self.root.after(0, lambda: self.ui.set_running_state(False))

    def _run_mission(self, mission: Mission):
        """Runs one queued mission - either a fixed number of repeats, or
        (if mission.shard_target is set) farmed until enough trait
        shards have dropped. Either way this is done WITHOUT leaving the
        room in between individual runs - the result screen auto-
        replays the same map, so Leave is only ever clicked once, right
        before moving on to the next queued mission. Returns False on
        abort/stop/failure."""
        label = mission.label()

        if mission.shard_farming and mission.shard_target is not None:
            already_banked = shard_progress.get_progress(mission)
            if already_banked >= mission.shard_target:
                # Already met (e.g. the user manually banked enough via
                # Settings) - skip this ENTIRELY, no navigation at all.
                # Checking this before _enter_mission matters: otherwise
                # this would only be noticed after already starting a
                # live match, with nowhere sensible to click Leave yet.
                self.ui.log(f"Skipping '{label}' - already have {already_banked} shard(s) banked, "
                            f"meeting or exceeding the {mission.shard_target} target.", "success")
                shard_progress.clear_progress(mission)
                return True

        self.ui.log(f"Starting mission: {label}")

        if not self._enter_mission(mission):
            return False

        if mission.shard_farming:
            return self._farm_shards(mission, label)
        return self._run_fixed_repeats(mission, label)

    def _run_fixed_repeats(self, mission: Mission, label: str):
        unlimited = mission.repeat_count is None
        run_number = 0

        while unlimited or run_number < mission.repeat_count:
            run_number += 1
            if self._check_stop():
                return False

            run_label = f"{run_number}/{mission.repeat_count}" if not unlimited else f"{run_number} (no limit)"
            self._log_debug(f"In match ({run_label}) - waiting for victory or defeat...")
            result_key = nav.wait_for_any_screen(
                ["victory_screen", "defeat_screen"],
                timeout=RESULT_TIMEOUT, log=self.ui.log, stop_check=self._check_stop,
            )
            if self._check_stop():
                return False
            if result_key is None:
                self.ui.log("Never saw a victory/defeat screen - aborting this mission.", "error")
                return False

            outcome = "VICTORY" if result_key == "victory_screen" else "DEFEAT"
            self.ui.log(f"Result: {outcome}", "success" if outcome == "VICTORY" else "warning")
            self._maybe_send_discord_screenshot(f"{outcome} - {label} (run {run_label})")

            if not unlimited:
                self.root.after(0, lambda rn=run_number, rc=mission.repeat_count:
                                 self.ui.set_run_progress(rn, rc))
            else:
                self.root.after(0, lambda rn=run_number: self.ui.set_run_progress(rn, "∞"))

            is_last_run = ((not unlimited) and run_number == mission.repeat_count) or self._check_end_task()
            if not self._replay_or_leave(is_last_run):
                return False
            if is_last_run:
                break

        self.ui.log(f"Mission complete: {label}", "success")
        return True

    def _farm_shards(self, mission: Mission, label: str):
        """Auto-replays the same map, reading the trait shard count off
        each result screen and accumulating it. Stops once the running
        total reaches (or slightly passes) mission.shard_target - or, if
        shard_target is None, keeps farming with no numeric target at
        all. Either way, repeat_count (if set) acts as a safety cap on
        max attempts; if repeat_count is also None, this only ever stops
        via the Stop button."""
        total_shards = shard_progress.get_progress(mission)
        run_number = 0
        has_target = mission.shard_target is not None
        has_run_cap = mission.repeat_count is not None

        if total_shards > 0:
            self.ui.log(f"Resuming this stage - already have {total_shards} shard(s) banked from before.", "info")

        while True:
            if has_target and total_shards >= mission.shard_target:
                break
            if has_run_cap and run_number >= mission.repeat_count:
                break
            run_number += 1
            if self._check_stop():
                return False

            cap_label = f"/{mission.repeat_count} max" if has_run_cap else ""
            self._log_debug(f"In match ({run_number}{cap_label}) - waiting for victory or defeat...")
            result_key = nav.wait_for_any_screen(
                ["victory_screen", "defeat_screen"],
                timeout=RESULT_TIMEOUT, log=self.ui.log, stop_check=self._check_stop,
            )
            if self._check_stop():
                return False
            if result_key is None:
                self.ui.log("Never saw a victory/defeat screen - aborting this mission.", "error")
                return False

            outcome = "VICTORY" if result_key == "victory_screen" else "DEFEAT"
            self.ui.log(f"Result: {outcome}", "success" if outcome == "VICTORY" else "warning")
            self._maybe_send_discord_screenshot(f"{outcome} - {label} (run {run_number})")

            self._refocus_roblox()
            try:
                shard_count = trait_shard.read_shard_count(log=self.ui.log)
            except FileNotFoundError as e:
                self.ui.log(f"Can't read trait shards: {e}", "error")
                return False
            if shard_count is None:
                self.ui.log("Couldn't read a shard count this run - assuming 0.", "warning")
                shard_count = 0
            total_shards += shard_count
            shard_progress.set_progress(mission, total_shards)
            target_label = f"/{mission.shard_target}" if has_target else ""
            self.ui.log(f"Trait shards this run: {shard_count}  (total: {total_shards}{target_label})")
            self.root.after(0, lambda lbl=mission.label(): self.ui.set_current_task_label(lbl))

            if has_target:
                self.root.after(0, lambda c=total_shards, t=mission.shard_target: self.ui.set_run_progress(c, t))
            else:
                self.root.after(0, lambda c=total_shards: self.ui.set_run_progress(c, "∞"))

            target_reached = has_target and total_shards >= mission.shard_target
            about_to_hit_cap = has_run_cap and run_number >= mission.repeat_count
            end_task = self._check_end_task()
            is_last_run = target_reached or (about_to_hit_cap and not has_target) or end_task
            if not self._replay_or_leave(is_last_run):
                return False
            if end_task and not target_reached and not about_to_hit_cap:
                self.ui.log(f"Ended '{label}' early at {total_shards} shard(s) banked - "
                            f"progress is saved, so this resumes from here next time.", "warning")
                break

        if has_target and total_shards < mission.shard_target:
            self.ui.log(f"Hit the {mission.repeat_count}-run safety cap before reaching "
                        f"{mission.shard_target} shards (got {total_shards}) - moving on anyway.", "warning")
        if has_target and total_shards >= mission.shard_target:
            shard_progress.clear_progress(mission)
        self.ui.log(f"Mission complete: {label} ({total_shards} shards)", "success")
        return True

    def _replay_or_leave(self, is_last_run: bool):
        """Shared tail end of a single run: either let the game
        auto-replay (waiting for the current result screen to clear
        first so it can't be double-counted), or click Leave and confirm
        we're back at the lobby. Returns False on stop/failure."""
        self._refocus_roblox()
        if not is_last_run:
            self._log_debug("Target not reached yet - game will auto-replay, waiting for it to restart...")
            nav.wait_until_gone(
                ["victory_screen", "defeat_screen"],
                timeout=15.0, log=self.ui.log, stop_check=self._check_stop,
            )
            if self._check_stop():
                return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False
        else:
            self._log_debug("Target reached - clicking Leave to return to the lobby...")
            for attempt in range(3):
                if self._check_stop():
                    return False
                if not self._click_leave():
                    return False
                # Fast confirm on every attempt - Leave is racing the
                # game's own auto-replay timer, so this should never slow
                # down. The retry COUNT (not a longer per-attempt wait) is
                # what protects against one missed detection ending the
                # whole farm.
                if self._confirm_lobby(timeout=3.0):
                    break
                if attempt < 2:
                    self.ui.log("Not confirmed at the lobby yet after Leave - trying again "
                                f"({attempt + 2}/3)...", "warning")
                else:
                    self.ui.log("Still couldn't confirm the lobby after 3 attempts - pausing here. "
                                "This task is preserved in the queue - press Start (F6) to retry it "
                                "once you've checked what's on screen.", "error")
                    return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False
        return True

    def _click_leave(self, retries=4, retry_pause=0.5):
        """Clicks Leave using plain icon detection - 'leave_button' is
        captured the same normal way as every other button (via
        capture_icons.py), so this works out of the box for anyone
        using a shared asset_data.py, with no separate calibration step
        needed. If something is covering the button and it can't be
        seen right now, falls back to clicking several spots around its
        last-known position (see use_cache_on_miss in game_navigator.py) -
        and if THAT fails too, falls back to Settings > Return to Lobby,
        which sits in a different part of the screen entirely."""
        if nav.click_icon("leave_button", log=self._log_debug, stop_check=self._check_stop,
                          retries=retries, retry_pause=retry_pause,
                          click_pause=0.05, move_duration=0.06,
                          use_cache_on_miss=True, confirm_key="menu_play", confirm_timeout=3.0):
            return True

        # click_icon can report failure here even though Leave was actually
        # found and clicked - it just means 'menu_play' never matched within
        # ITS OWN polling window (e.g. one slow transition). By this point
        # click_icon has already spent up to retries * confirm_timeout (~12s)
        # polling, so a slow-but-real transition may still be mid-flight -
        # give it a real window here rather than a token check before
        # assuming Leave never landed. Otherwise this runs Settings > Return
        # to Lobby on top of an already-successful Leave, which clashes
        # (clicking the gear icon over a screen that's already mid-transition,
        # or already at the lobby).
        if self._confirm_lobby(timeout=10.0):
            self._log_debug("Already at the lobby - Leave must have landed despite the failed confirm.")
            return True

        self.ui.log("Leave button attempts failed - trying Settings > Return to Lobby instead...",
                     "warning")
        return self._click_return_to_lobby_via_settings()

    def _click_return_to_lobby_via_settings(self):
        """Fallback path: open the gear/settings menu and click Return
        to Lobby from inside it. Two clicks instead of one, but the
        gear icon and this button live somewhere else on screen than
        the result-screen reward row, so whatever covered Leave (a
        scrolling banner, a toast) may not reach here at all."""
        self._log_debug("Opening Settings (gear icon)...")
        self._refocus_roblox()
        if not nav.click_icon("settings_gear", log=self._log_debug, stop_check=self._check_stop,
                              confirm_key="return_to_lobby_button", confirm_timeout=10.0):
            self.ui.log("Couldn't open Settings via the gear icon either.", "error")
            return False
        if self._sleep_interruptible(STEP_PAUSE):
            return False

        self._log_debug("Clicking Return to Lobby...")
        self._refocus_roblox()
        if not nav.click_icon("return_to_lobby_button", log=self._log_debug, stop_check=self._check_stop):
            self.ui.log("Couldn't click Return to Lobby.", "error")
            return False
        return True

    def _mode_confirm_icon(self, mission: Mission):
        """Which icon should appear once the top-level mode button
        (mode_story / mode_squadron / etc.) has actually been clicked -
        used as click_icon's confirm_key so a slow-loading page doesn't
        get mistaken for a successful click."""
        if mission.mode in ("Story", "Squadron"):
            return "world_gt_city"
        if mission.mode == "Challenge":
            first_challenge_key = next(iter(stage_data.CHALLENGES))
            return f"challenge_{first_challenge_key}"
        if mission.mode == "Raid":
            first_raid_key = next(iter(stage_data.RAIDS))
            return f"raid_{first_raid_key}"
        if mission.mode == "Invasion":
            first_invasion_key = next(iter(stage_data.INVASIONS))
            return f"invasion_{first_invasion_key}"
        return None

    def _enter_mission(self, mission: Mission):
        """Navigates from the main menu all the way into a match for the
        given mission (mode/world/chapter/difficulty as applicable),
        ending with the Start button click. This is the same navigation
        every run of a mission repeats, since each repeat starts back at
        the lobby after the previous run's Leave click."""
        try:
            self._refocus_roblox()

            self._log_debug("Confirming we're at the main menu (lobby)...")
            if not self._confirm_lobby(timeout=15.0):
                self.ui.log("Doesn't look like the lobby/main menu is showing - aborting.", "error")
                return False
            if self._check_stop():
                return False

            self._log_debug("Looking for Play button...")
            self._refocus_roblox()
            if not nav.click_icon("menu_play", log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False

            self._log_debug("Looking for Create Room...")
            self._refocus_roblox()
            if not nav.click_icon("create_room", log=self._log_debug, stop_check=self._check_stop):
                return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False

            self._log_debug("Confirming the mode-selection page actually loaded...")
            if not nav.wait_for_screen("mode_story", timeout=12.0, log=self.ui.log, stop_check=self._check_stop):
                self.ui.log("Mode-selection page doesn't look loaded - aborting rather than clicking blind.", "error")
                return False
            if self._check_stop():
                return False

            mode_key = f"mode_{mission.mode.lower()}"
            self._log_debug(f"Selecting mode: {mission.mode}")
            self._refocus_roblox()
            mode_confirm = self._mode_confirm_icon(mission)
            if not nav.click_icon(mode_key, log=self._log_debug, confirm_key=mode_confirm, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False

            if mission.mode in ("Story", "Squadron"):
                world_key, difficulty, chapter = mission.world_key, mission.difficulty, mission.chapter

                self._log_debug(f"Selecting world: {world_key}")
                self._refocus_roblox()
                world_icon = f"world_{world_key}"
                if world_key in WORLDS_NEEDING_SCROLL:
                    self._log_debug(f"World '{world_key}' needs scrolling - scrolling down in small steps...")
                    ok = nav.scroll_until_found(
                        world_icon,
                        log=self.ui.log,
                        hover_key=WORLD_LIST_HOVER_ANCHOR,
                        scroll_amount=CHAPTER_SCROLL_AMOUNT,
                        max_scrolls=CHAPTER_MAX_SCROLLS,
                        stop_check=self._check_stop,
                    )
                    if not ok and not self._check_stop():
                        self._log_debug(f"Double-checking: is '{world_icon}' actually visible right now?", "warning")
                        if nav.on_screen(world_icon):
                            self._log_debug("It IS visible now - retrying the click directly.", "warning")
                            ok = nav.click_icon(world_icon, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION)
                else:
                    ok = nav.click_icon(world_icon, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION)
                if not ok:
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

                chapter_key = f"chapter_{chapter}"
                self._log_debug(f"Selecting chapter {chapter}")
                self._refocus_roblox()
                if chapter <= 7:
                    ok = nav.click_icon(chapter_key, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION)
                else:
                    self._log_debug(f"Chapter {chapter} needs scrolling - scrolling down in small steps...")
                    ok = nav.scroll_until_found(
                        chapter_key,
                        log=self.ui.log,
                        hover_key="chapter_7",
                        scroll_amount=CHAPTER_SCROLL_AMOUNT,
                        max_scrolls=CHAPTER_MAX_SCROLLS,
                        stop_check=self._check_stop,
                    )
                    if not ok and not self._check_stop():
                        self._log_debug(f"Double-checking: is '{chapter_key}' actually visible right now?", "warning")
                        if nav.on_screen(chapter_key):
                            self._log_debug("It IS visible now - retrying the click directly.", "warning")
                            ok = nav.click_icon(chapter_key, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION)
                if not ok:
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

                self._log_debug(f"Selecting difficulty: {difficulty}")
                self._refocus_roblox()
                if not nav.click_icon(f"diff_{difficulty}", log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

            elif mission.mode == "Challenge":
                challenge_icon = f"challenge_{mission.challenge_key}"
                self._log_debug(f"Selecting challenge: {mission.challenge_key}")
                self._refocus_roblox()
                # A challenge with only one stage auto-selects it - clicking
                # the challenge icon already lands there (that's what its
                # confirm_key below checks for), so there's nothing left to
                # click. Only challenges with 2+ stages need a separate
                # stage click after this.
                single_stage = (mission.challenge_stage is not None
                                 and len(stage_data.CHALLENGES[mission.challenge_key]["stages"]) == 1)
                if mission.challenge_stage:
                    stage_confirm = stage_data.challenge_stage_icon_key(
                        mission.challenge_key, mission.challenge_stage)
                    ok = nav.click_icon(challenge_icon, log=self._log_debug, confirm_key=stage_confirm,
                                        stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION)
                else:
                    ok = nav.click_icon(challenge_icon, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION)
                if not ok:
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

                if mission.challenge_stage and single_stage:
                    self._log_debug(f"'{mission.challenge_key}' only has one stage - already selected, "
                                     "skipping straight to Create Room.")
                elif mission.challenge_stage:
                    stage_icon = stage_data.challenge_stage_icon_key(
                        mission.challenge_key, mission.challenge_stage)
                    self._log_debug(f"Selecting challenge stage: {mission.challenge_stage}")
                    self._refocus_roblox()
                    if not nav.click_icon(stage_icon, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                        return False
                    if self._sleep_interruptible(STEP_PAUSE):
                        return False

            elif mission.mode == "Raid":
                raid_icon = f"raid_{mission.raid_key}"
                self._log_debug(f"Selecting raid: {mission.raid_key}")
                self._refocus_roblox()
                first_stage = stage_data.RAIDS[mission.raid_key]["stages"][0]
                raid_confirm = stage_data.raid_stage_icon_key(mission.raid_key, first_stage)
                if not nav.click_icon(raid_icon, log=self._log_debug, confirm_key=raid_confirm,
                                      stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

                stage_icon = stage_data.raid_stage_icon_key(mission.raid_key, mission.raid_stage)
                self._log_debug(f"Selecting raid stage: {mission.raid_stage}")
                self._refocus_roblox()
                if not nav.click_icon(stage_icon, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

                if mission.difficulty:
                    self._log_debug(f"Selecting difficulty: {mission.difficulty}")
                    self._refocus_roblox()
                    if not nav.click_icon(f"diff_{mission.difficulty}", log=self._log_debug,
                                          stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                        return False
                    if self._sleep_interruptible(STEP_PAUSE):
                        return False

            elif mission.mode == "Invasion":
                invasion_icon = f"invasion_{mission.invasion_key}"
                self._log_debug(f"Selecting invasion: {mission.invasion_key}")
                self._refocus_roblox()
                first_stage = stage_data.INVASIONS[mission.invasion_key]["stages"][0]
                invasion_confirm = stage_data.invasion_stage_icon_key(mission.invasion_key, first_stage)
                if not nav.click_icon(invasion_icon, log=self._log_debug, confirm_key=invasion_confirm,
                                      stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

                stage_icon = stage_data.invasion_stage_icon_key(mission.invasion_key, mission.invasion_stage)
                self._log_debug(f"Selecting invasion stage: {mission.invasion_stage}")
                self._refocus_roblox()
                if not nav.click_icon(stage_icon, log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

                self._log_debug(f"Selecting difficulty: {mission.difficulty}")
                self._refocus_roblox()
                if not nav.click_icon(f"diff_{mission.difficulty}", log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                    return False
                if self._sleep_interruptible(STEP_PAUSE):
                    return False

            self._log_debug("Finalizing room creation...")
            self._refocus_roblox()
            if not nav.click_icon("create_room_2", log=self._log_debug, stop_check=self._check_stop):
                return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False

            self._log_debug("Looking for Start button...")
            self._refocus_roblox()
            if not nav.click_icon("start_button", log=self._log_debug, stop_check=self._check_stop, click_pause=NAV_CLICK_PAUSE, move_duration=NAV_MOVE_DURATION):
                return False

            return True
        except FileNotFoundError as e:
            self.ui.log(f"Missing icon: {e}", "error")
            return False


def main():
    _ensure_admin()
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
