"""
launcher.py
-----------
The main file you run - the brain of the app. UI lives in ui/ui.py,
automation/game-logic in backend/. This file handles admin permission,
F6/F7 hotkeys, start/stop, keeping Roblox in focus, and walking through
each mission.
"""

import os
import sys

# backend/ and ui/ import each other by plain name, so both need to be
# on sys.path before anything below is imported.
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
import result_color
import shard_progress
import manual_credits
import stage_data
import display_info
import reset_clock
import auto_update
from window_lock import find_window, bring_to_front, is_foreground
from ui import LauncherUI, ROBLOX_TITLE
from mission_queue import Mission

RESULT_TIMEOUT = 180.0   # how long a single match can run before giving up
STEP_PAUSE = 2.0

# Any of these showing means the match has ended and the results screen
# is up. Retry/Leave are checked first (cheaper, and immune to a level-up
# toast covering the banner); victory_screen/defeat_screen back them up
# for the reverse case - a toast covering Retry/Leave itself.
RESULT_SCREEN_KEYS = ["retry_button", "leave_button", "victory_screen", "defeat_screen"]

# Confirming Retry/Leave used to search the ENTIRE virtual screen at
# full resolution (~700ms per icon checked) - restricting it to just
# Roblox's window and shrinking the search frame (like trait_shard.py's
# scan) cuts that to well under 200ms, so the results screen (and the
# shard reward on it) gets caught sooner instead of several seconds late.
RESULT_DETECTION_DOWNSCALE = 0.6

# Modest speedup over mouse.py's default click timing (0.45s/0.15s) for
# the Play-through-Start sequence. Some buttons (Create Room) need a
# hover animation to finish first, so don't lower these further - give
# a specific button its own override instead.
NAV_CLICK_PAUSE = 0.3
NAV_MOVE_DURATION = 0.12
WAIT_FOR_ROBLOX_INTERVAL = 1.5
CHAPTER_SCROLL_AMOUNT = -150
CHAPTER_MAX_SCROLLS = 25

# Keeps the game from treating a long unattended session as AFK - see
# _anti_idle_loop for how the two modes below are chosen.
ANTI_IDLE_INTERVAL_SECONDS = 600  # 10 minutes, while idle (no task running)
ANTI_IDLE_JITTER_OFFSET = (12, 12)
ANTI_IDLE_IN_GAME_INTERVAL_SECONDS = 30  # 30 seconds, while a task IS running

# Worlds past the first 5 need the world list scrolled first - Ice
# Continent is the last one visible before scrolling, used as the hover anchor.
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

        # Must run before anything else touches shard progress - otherwise
        # manual_credits below could get wiped by a reset that hasn't
        # been processed yet.
        self._check_shard_reset()

        self._register_hotkeys()

        display_info.check_scaling(log=self.ui.log)
        manual_credits.apply_credits(log=self.ui.log)

        if find_window(ROBLOX_TITLE) is None:
            self._start_wait_for_roblox_thread()

        threading.Thread(target=self._shard_reset_loop, daemon=True).start()
        auto_update.check_for_update_async(self._on_update_found, log=self.ui.log)

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
        """Keeps the game from treating a long unattended session as AFK -
        opt-in via the "Anti-idle" checkbox in Settings (off by default;
        the in-game Space-jump can interfere with trait shard stages).
        Two modes when enabled, picked fresh each cycle based on
        self.running:

          - Task running: presses Space (a jump) every
            ANTI_IDLE_IN_GAME_INTERVAL_SECONDS. A jump is harmless mid-
            automation - unlike a mouse click, it can't land on and
            misclick some game UI the automation is mid-sequence with.
          - Idle (no task running): nudges the mouse and clicks every
            ANTI_IDLE_INTERVAL_SECONDS instead, same as before - safe
            here since there's no automation in progress to disrupt.

        Starts on first Start press, runs for the session."""
        while not self._closing:
            if not self.ui.is_anti_idle_enabled():
                time.sleep(2.0)
                continue

            running_now = self.running
            interval = ANTI_IDLE_IN_GAME_INTERVAL_SECONDS if running_now else ANTI_IDLE_INTERVAL_SECONDS

            # Sleep in short increments so app close/a running-state
            # change doesn't wait out the full interval to be noticed -
            # if self.running flips mid-wait, bail out and re-pick the
            # interval/action for the new state instead of finishing the
            # old one.
            slept = 0.0
            mode_changed = False
            while slept < interval:
                if self._closing:
                    return
                time.sleep(0.5)
                slept += 0.5
                if self.running != running_now:
                    mode_changed = True
                    break
            if mode_changed:
                continue

            try:
                hwnd = find_window(ROBLOX_TITLE)
                if hwnd is None:
                    continue
                bring_to_front(hwnd)
                time.sleep(0.3)
                if self.running != running_now:
                    continue  # running-state flipped during that brief focus wait - bail out

                if running_now:
                    # find_window does a loose substring match over every
                    # open window - if some OTHER window's title happens
                    # to contain "Roblox" (a browser tab, another app),
                    # bring_to_front could have focused THAT instead, and
                    # Space would silently go there rather than the game.
                    # Confirming focus actually landed on Roblox before
                    # sending is what makes this catch that instead of
                    # jumping nowhere.
                    if not is_foreground(ROBLOX_TITLE):
                        self.ui.log("Anti-idle: Roblox didn't come to the foreground - "
                                    "skipping this Space press.", "warning")
                        continue
                    self.ui.log("Anti-idle: pressing Space to prevent an AFK kick.", "info")
                    keyboard.send("space")
                else:
                    self.ui.log("Anti-idle: nudging the mouse to prevent an AFK kick.", "info")
                    mouse.jitter_and_click(offset=ANTI_IDLE_JITTER_OFFSET)
            except Exception as e:
                self.ui.log(f"Anti-idle nudge failed (non-fatal): {e}", "warning")

    def _check_shard_reset(self):
        """Compares the most recent official 5pm-Pacific reset boundary
        against the saved marker - if the marker's older, clears all
        banked progress and updates it. If they already match (already
        processed, including across multiple relaunches the same day),
        does nothing. See reset_clock.check_and_consume_reset()."""
        try:
            if reset_clock.check_and_consume_reset():
                shard_progress.clear_all()
                self.ui.log("Daily Trait Shard reset detected (5pm Pacific) - all banked "
                            "progress has been cleared.", "warning")
        except Exception as e:
            self.ui.log(f"Shard reset check failed (non-fatal): {e}", "warning")

    def _shard_reset_loop(self):
        """Re-checks every 30s so a reset boundary crossed WHILE the app
        stays open still gets caught - the first, startup-time check
        already happened synchronously in __init__ (see
        _check_shard_reset)."""
        while not self._closing:
            slept = 0.0
            while slept < 30.0:
                if self._closing:
                    return
                time.sleep(0.5)
                slept += 0.5
            self._check_shard_reset()

    def on_close(self):
        self.stop_requested = True
        self._closing = True
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.ui.destroy()

    # ---------- Auto-update ----------

    def _on_update_found(self, version, download_url):
        """Called from the background check thread - hops to the main
        thread before touching any UI."""
        self.root.after(0, lambda: self._prompt_update(version, download_url))

    def _prompt_update(self, version, download_url):
        import tkinter.messagebox as messagebox
        yes = messagebox.askyesno(
            "Update available",
            f"A new version is available: {version} (you have v{auto_update.CURRENT_VERSION}).\n\n"
            "Update now? The app will close and restart automatically once it's downloaded.",
        )
        if not yes:
            self.ui.log(f"Skipped update to {version} - will ask again next launch.", "info")
            return
        threading.Thread(target=self._download_and_apply_update, args=(download_url,), daemon=True).start()

    def _download_and_apply_update(self, download_url):
        """Runs on a background thread so downloading can't freeze the
        UI; hops back to the main thread once done to launch the swap
        script and shut down."""
        try:
            new_exe_path = auto_update.download_update(download_url, log=self.ui.log)
        except Exception as e:
            self.ui.log(f"[update] Update download failed: {e}", "error")
            return
        self.root.after(0, lambda: self._finish_update(new_exe_path))

    def _finish_update(self, new_exe_path):
        auto_update.launch_swap_script(new_exe_path, log=self.ui.log)
        self.on_close()

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
        """Same as self.ui.log, but only shows if Verbose Logging is on -
        for routine step-by-step chatter. Results/errors/milestones
        always use self.ui.log directly."""
        if self.ui.is_verbose_enabled():
            self.ui.log(text, level)

    def _check_stop(self):
        if self.stop_requested:
            self.ui.log("Stopped by user.", "warning")
            return True
        return False

    def on_end_task(self):
        """'End Current Task' - unlike Stop, doesn't pause the queue.
        Wraps up the current task now (as if its target was reached) and
        moves on to the next one."""
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
        """Checks we're back at the lobby - 'menu_play', or also
        'lobby_screen' if that optional landmark's been captured, so one
        borderline detection doesn't read as 'not at the lobby'."""
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
        """Fires a Roblox-only screenshot to Discord if that's turned on
        and a URL is set; otherwise does nothing."""
        if not self.ui.is_discord_result_notify_enabled():
            return
        url = self.ui.get_discord_webhook_url()
        if not url:
            return
        bbox = self.ui.get_roblox_bbox()
        if bbox is None:
            self.ui.log("Discord: Roblox window position unknown - skipping screenshot.", "warning")
            return
        discord_webhook.send_screenshot_async(url, bbox, message=message, log=self.ui.log)

    def _maybe_send_discord_task_complete(self, message):
        """Fires a plain-text Discord message when a task finishes, if
        the user's turned that on and set a URL. Bolded (Discord markdown
        **text**) so it stands out from the per-run result messages."""
        if not self.ui.is_discord_task_complete_notify_enabled():
            return
        url = self.ui.get_discord_webhook_url()
        if not url:
            return
        discord_webhook.send_message_async(url, f"**{message}**", log=self.ui.log)

    def _maybe_send_discord_shard_drop(self, message):
        """Fires a plain-text Discord message every time a Trait Shard
        drop is actually counted (not on 0-shard runs), if the user's
        turned that on and set a URL."""
        if not self.ui.is_discord_shard_drop_notify_enabled():
            return
        url = self.ui.get_discord_webhook_url()
        if not url:
            return
        discord_webhook.send_message_async(url, message, log=self.ui.log)

    # ---------- Navigation sequence ----------

    def run_queue(self):
        """Pulls missions off the queue one at a time, running each to
        completion before moving to the next. Stops early (leaving the
        rest untouched) if the user hits Stop."""
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
                # Popping removes it from the queue immediately, so
                # queue.total_runs() alone would drop this mission's
                # whole repeat_count from TOTAL RUNS right now, before
                # any of its runs have actually happened - this tells
                # the UI to keep counting it until each run completes
                # (see _run_fixed_repeats/_farm_shards, which report
                # progress as they go via update_mission_progress).
                self.root.after(0, lambda rc=mission.repeat_count: self.ui.start_mission_progress(rc))
                self.root.after(0, self.ui._refresh_queue_listbox)
                self.root.after(0, lambda ti=self._task_index, tt=self._total_tasks:
                                 self.ui.set_status_line(f"Running Task {ti} / {tt}"))
                self.root.after(0, lambda lbl=mission.label(): self.ui.set_current_task_label(lbl))
                if not self._run_mission(mission):
                    # Deliberate Stop or hard failure either way - push
                    # back so nothing's lost; Start (F6) resumes it. Reset
                    # BEFORE refreshing so the full repeat_count is
                    # counted from the queue again, not double-counted
                    # on top of it.
                    queue.push_front(mission)
                    self.root.after(0, self.ui.end_mission_progress)
                    self.root.after(0, self.ui._refresh_queue_listbox)
                    if self.stop_requested:
                        self.root.after(0, lambda lbl=mission.label():
                                         self.ui.set_current_task_label(f"Paused: {lbl}"))
                    else:
                        self.root.after(0, lambda lbl=mission.label():
                                         self.ui.set_current_task_label(f"Stopped on error: {lbl}"))
                    return
                self.root.after(0, self.ui.end_mission_progress)
            self.root.after(0, lambda: self.ui.set_status_line("Queue finished."))
            self.root.after(0, lambda: self.ui.set_current_task_label("Nothing running - queue finished."))
        finally:
            self.running = False
            self.stop_requested = False
            self.root.after(0, lambda: self.ui.set_running_state(False))

    def _run_mission(self, mission: Mission):
        """Runs one mission - a fixed number of repeats, or (if
        shard_target is set) farmed until enough shards drop. The result
        screen auto-replays the map, so Leave is only clicked once, right
        before the next mission. Returns False on abort/stop/failure."""
        label = mission.label()

        if mission.shard_farming and mission.shard_target is not None:
            already_banked = shard_progress.get_progress(mission)
            if already_banked >= mission.shard_target:
                # Already met (e.g. manually banked via Settings) - skip
                # entirely, before starting a live match with nowhere to click Leave.
                self.ui.log(f"Skipping '{label}' - already have {already_banked} shard(s) banked, "
                            f"meeting or exceeding the {mission.shard_target} target.", "success")
                shard_progress.clear_progress(mission)
                return True

        self.ui.log(f"Starting mission: {label}")

        if not self._enter_mission(mission):
            return False

        if mission.shard_farming:
            return self._farm_shards(mission)
        return self._run_fixed_repeats(mission, label)

    def _detect_outcome(self):
        """Runs color detection on the results screen's banner region
        (green = victory, red = defeat) to determine the outcome - this
        only happens AFTER the results screen is already confirmed up via
        Retry/Leave (see _wait_for_result_screen), and is independent of
        the trait shard scan (which runs regardless of what this
        returns). Logs and returns "VICTORY", "DEFEAT", or "UNKNOWN" if
        the color scan can't confidently tell which one it is."""
        outcome = result_color.detect_result_color(self.ui.get_roblox_bbox(), log=self.ui.log)
        label = outcome.upper()
        level = "success" if label == "VICTORY" else "warning"
        self.ui.log(f"Result: {label}", level)
        return label

    def _wait_for_result_screen(self, timeout=RESULT_TIMEOUT, poll_pause=0.2):
        """Polls for the results screen via Retry/Leave OR the Victory/
        Defeat banner icon - any one showing is enough to confirm it's
        up. Deliberately icon-matching only, never color detection - see
        result_color.py's docstring for why that's kept out of this
        role. A game notification toast (e.g. "Upgraded X to upgrade
        Y!") can render directly over the Retry/Leave buttons and blank
        them out for a stretch, which was observed to time out this
        whole wait (and abort the mission) when Retry/Leave were the
        only signal - the banner sits in a different part of the screen
        and isn't affected, so it backs the buttons up here (and vice
        versa)."""
        start = time.time()
        bbox = self.ui.get_roblox_bbox()
        while time.time() - start < timeout:
            if self._check_stop():
                return None
            for key in RESULT_SCREEN_KEYS:
                if nav.on_screen(key, region=bbox, downscale=RESULT_DETECTION_DOWNSCALE):
                    return key
            time.sleep(poll_pause)
        self.ui.log(f"Never saw the results screen (Retry/Leave/banner) within {timeout:.0f}s - "
                    f"the match may still be running longer than expected, or something's stuck.", "warning")
        return None

    def _run_fixed_repeats(self, mission: Mission, label: str):
        unlimited = mission.repeat_count is None
        run_number = 0

        while unlimited or run_number < mission.repeat_count:
            run_number += 1
            if self._check_stop():
                return False

            run_label = f"{run_number}/{mission.repeat_count}" if not unlimited else f"{run_number} (no limit)"
            self._log_debug(f"In match ({run_label}) - waiting for the results screen...")
            result_key = self._wait_for_result_screen()
            if self._check_stop():
                return False
            if result_key is None:
                self.ui.log("Aborting this mission.", "error")
                return False

            # Sent immediately on results-screen confirmation, before
            # outcome detection - the screenshot itself doesn't need the
            # outcome to already be known (the banner's right there in
            # the captured frame either way), and this is the earliest
            # point the result screen is guaranteed to be up.
            self._maybe_send_discord_screenshot(f"Result screen - {label} (run {run_label})")

            try:
                self._detect_outcome()
            except Exception as e:
                self.ui.log(f"Result color detection failed (non-fatal): {e}", "warning")

            if not unlimited:
                self.root.after(0, lambda rn=run_number, rc=mission.repeat_count:
                                 self.ui.set_run_progress(rn, rc))
                self.root.after(0, lambda rn=run_number: self.ui.update_mission_progress(rn))
            else:
                self.root.after(0, lambda rn=run_number: self.ui.set_run_progress(rn, "∞"))

            is_last_run = ((not unlimited) and run_number == mission.repeat_count) or self._check_end_task()
            if not self._replay_or_leave(is_last_run):
                return False
            if is_last_run:
                break

        self.ui.log(f"Mission complete: {label}", "success")
        self._maybe_send_discord_task_complete(f"Task complete: {label}")
        return True

    def _farm_shards(self, mission: Mission):
        """Auto-replays the map, reading and accumulating the shard
        count off each result screen. Stops once the total reaches
        shard_target (or never, if None - farms until Stop).
        repeat_count, if set, is a safety cap on max attempts."""
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
            self._log_debug(f"In match ({run_number}{cap_label}) - waiting for the results screen...")
            result_key = self._wait_for_result_screen()
            if self._check_stop():
                return False
            if result_key is None:
                self.ui.log("Aborting this mission.", "error")
                return False

            self.ui.log("Result screen detected.", "success")

            # Sent immediately on results-screen confirmation, before
            # outcome detection or the shard scan - the screenshot itself
            # doesn't need the outcome to already be known (the banner's
            # right there in the captured frame either way), and this is
            # the earliest point the result screen is guaranteed to be up.
            self._maybe_send_discord_screenshot(f"Result screen - {mission.label()} (run {run_number})")

            # Color detection determines VICTORY/DEFEAT, but must never
            # block or skip the shard scan below - wrapped so a failure
            # here (or an "unknown" result) can't prevent shards from
            # still being read.
            try:
                self._detect_outcome()
            except Exception as e:
                self.ui.log(f"Result color detection failed (non-fatal): {e}", "warning")

            # Read the shard count - independent of the outcome above.
            # Searches the whole Roblox window and polls for a few
            # seconds internally to give the reward's pop-in animation
            # time to settle (see trait_shard.read_shard_count).
            try:
                shard_count = trait_shard.read_shard_count(log=self.ui.log, region=self.ui.get_roblox_bbox())
            except FileNotFoundError as e:
                self.ui.log(f"Can't read trait shards: {e}", "error")
                return False
            if shard_count is None:
                shard_count = 0
            total_shards += shard_count
            shard_progress.set_progress(mission, total_shards)
            target_label = f"/{mission.shard_target}" if has_target else ""
            self.ui.log(f"Trait shards this run: {shard_count}  (total: {total_shards}{target_label})")

            # mission.label() reads shard_progress fresh every call -
            # must be called AFTER set_progress() above so it reflects
            # this run's result, not a stale count from before the loop started.
            current_label = mission.label()
            if shard_count > 0:
                self._maybe_send_discord_shard_drop(
                    f"+{shard_count} Trait Shard{'s' if shard_count != 1 else ''} - {current_label}")
            self.root.after(0, lambda lbl=current_label: self.ui.set_current_task_label(lbl))

            if has_target:
                self.root.after(0, lambda c=total_shards, t=mission.shard_target: self.ui.set_run_progress(c, t))
            else:
                self.root.after(0, lambda c=total_shards: self.ui.set_run_progress(c, "∞"))
            if has_run_cap:
                self.root.after(0, lambda rn=run_number: self.ui.update_mission_progress(rn))

            target_reached = has_target and total_shards >= mission.shard_target
            about_to_hit_cap = has_run_cap and run_number >= mission.repeat_count
            end_task = self._check_end_task()
            is_last_run = target_reached or (about_to_hit_cap and not has_target) or end_task
            if not self._replay_or_leave(is_last_run):
                return False
            if end_task and not target_reached and not about_to_hit_cap:
                self.ui.log(f"Ended '{mission.label()}' early - progress is saved, so this "
                            f"resumes from here next time.", "warning")
                break

        # Captured BEFORE clear_progress() below, which resets banked
        # count to 0 - calling mission.label() after that would show
        # "0/target" in the very message announcing the target was hit.
        final_label = mission.label()
        if has_target and total_shards < mission.shard_target:
            self.ui.log(f"Hit the {mission.repeat_count}-run safety cap before reaching "
                        f"{mission.shard_target} shards (got {total_shards}) - moving on anyway.", "warning")
        if has_target and total_shards >= mission.shard_target:
            shard_progress.clear_progress(mission)
        self.ui.log(f"Mission complete: {final_label}", "success")
        self._maybe_send_discord_task_complete(f"Task complete: {final_label}")
        return True

    def _replay_or_leave(self, is_last_run: bool):
        """Tail end of a single run: either let the game auto-replay
        (waiting for the result screen to clear first, so it can't be
        double-counted), or click Leave and confirm we're at the lobby."""
        self._refocus_roblox()
        if not is_last_run:
            self._log_debug("Target not reached yet - game will auto-replay, waiting for it to restart...")
            nav.wait_until_gone(
                RESULT_SCREEN_KEYS, timeout=15.0, log=self.ui.log, stop_check=self._check_stop,
                region=self.ui.get_roblox_bbox(), downscale=RESULT_DETECTION_DOWNSCALE,
            )
            if self._check_stop():
                return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False
        else:
            self._log_debug("Target reached - clicking Leave to return to the lobby...")
            leave_confirm_attempts = 5
            for attempt in range(leave_confirm_attempts):
                if self._check_stop():
                    return False
                if not self._click_leave():
                    return False
                # Fast confirm every attempt - Leave races auto-replay,
                # so retry COUNT (not a longer wait) is what protects
                # against one missed detection.
                if self._confirm_lobby(timeout=3.0):
                    break
                if attempt < leave_confirm_attempts - 1:
                    self.ui.log("Not confirmed at the lobby yet after Leave - trying again "
                                f"({attempt + 2}/{leave_confirm_attempts})...", "warning")
                else:
                    self.ui.log(f"Still couldn't confirm the lobby after {leave_confirm_attempts} attempts - "
                                "pausing here. This task is preserved in the queue - press Start (F6) to "
                                "retry it once you've checked what's on screen.", "error")
                    return False
            if self._sleep_interruptible(STEP_PAUSE):
                return False
        return True

    def _click_leave(self, retries=4, retry_pause=0.5):
        """Clicks Leave via icon detection. If covered, falls back to
        clicking around its last-known position (use_cache_on_miss in
        game_navigator.py); if that fails too, falls back to Settings >
        Return to Lobby instead."""
        if nav.click_icon("leave_button", log=self._log_debug, stop_check=self._check_stop,
                          retries=retries, retry_pause=retry_pause,
                          click_pause=0.05, move_duration=0.06,
                          use_cache_on_miss=True, confirm_key="menu_play", confirm_timeout=3.0):
            return True

        # click_icon can report failure even if Leave actually landed - it
        # just means 'menu_play' didn't match within ITS OWN polling
        # window (a slow transition). Give it a real second check here
        # instead of assuming Leave failed and clashing with Return to
        # Lobby on top of an already-successful Leave.
        if self._confirm_lobby(timeout=10.0):
            self._log_debug("Already at the lobby - Leave must have landed despite the failed confirm.")
            return True

        self.ui.log("Leave button attempts failed - trying Settings > Return to Lobby instead...",
                     "warning")
        return self._click_return_to_lobby_via_settings()

    def _click_return_to_lobby_via_settings(self):
        """Fallback: open Settings and click Return to Lobby from
        inside it - lives elsewhere on screen than Leave, so whatever
        covered Leave may not reach here."""
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
        """Icon that should appear once the mode button is actually
        clicked - used as click_icon's confirm_key so a slow-loading
        page isn't mistaken for a successful click."""
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
        """Navigates from the main menu into a match for this mission
        (mode/world/chapter/difficulty), ending with Start. Repeats each
        time, since every run starts back at the lobby after Leave."""
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
                # A single-stage challenge auto-selects on the challenge
                # click itself - only 2+ stage challenges need another click.
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
