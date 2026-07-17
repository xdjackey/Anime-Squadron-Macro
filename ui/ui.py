"""
ui.py
-----
Everything you actually SEE when you use the app - all the windows,
colors, buttons, dropdowns, and the log panel. This file does not run
any of the actual automation itself; that all happens in launcher.py.
"""

import ctypes
import time
import tkinter as tk
from tkinter import ttk

from window_lock import find_window, move_window, EDGE_OVERLAP, titlebar_height
from mission_queue import Mission, MissionQueue
import json
import os

import app_paths
import app_logging
import auto_update

SETTINGS_FILE = app_paths.path("launcher_settings.json")


def load_settings():
    """Returns saved settings (currently just the Discord webhook config)
    from disk, or sensible defaults if the file doesn't exist yet or is
    unreadable for any reason."""
    defaults = {
        "discord_webhook_url": "",
        # "discord_enabled" was the original single on/off toggle (screenshot
        # on every victory/defeat) - kept as the default source for
        # discord_notify_result below so anyone who already had it on
        # doesn't silently lose that notification after this update.
        "discord_enabled": False,
        "discord_notify_result": False,
        "discord_notify_task_complete": False,
        "discord_notify_shard_drop": False,
        "shard_targets": {},
        "verbose_logging": False,
    }
    if not os.path.exists(SETTINGS_FILE):
        return defaults
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        defaults.update(data)
        if "discord_notify_result" not in data and "discord_enabled" in data:
            defaults["discord_notify_result"] = data["discord_enabled"]
        return defaults
    except Exception:
        return defaults


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass  # a failed save shouldn't crash the app - worst case, re-enter next time

# ======================= APP TEXT =======================
APP_TITLE_LEFT = "ANIME SQUADRON"
# Reads from auto_update.CURRENT_VERSION instead of its own hardcoded
# string - the two used to drift out of sync (this was stuck on "V1.0"
# long after auto_update.py had already moved on to 1.6.0), since
# nothing forced them to be bumped together. Now there's exactly one
# place to update per release.
APP_TITLE_RIGHT = f"MACRO V{auto_update.CURRENT_VERSION}"
ROBLOX_TITLE = "Roblox"

# ======================= LAYOUT =======================
UI_WIDTH = 380
LOG_HEIGHT = 200
TITLE_BAR_HEIGHT = titlebar_height()  # matches Roblox's actual native title bar height,
                                       # so the overlay that covers it lines up exactly
PANEL_OVERLAP = EDGE_OVERLAP # overlap panel leftward to hide Roblox right border gap
LOG_OVERLAP = EDGE_OVERLAP   # overlap log upward to hide Roblox bottom border gap

# ======================= THEME =======================
BG = "#121212"
PANEL_BG = "#1a1a1a"
TITLE_BG = "#171717"
CARD_BG = "#161616"
FIELD_BG = "#232323"
BORDER = "#2e2e2e"
ACCENT = "#e5484d"
ACCENT_HOVER = "#f0656a"
TEXT_MAIN = "#e8e8e8"
TEXT_DIM = "#8a8a8a"
LOG_INFO = "#7ab8ff"
LOG_SUCCESS = "#5ce68a"
LOG_WARNING = "#f2c94c"
LOG_ERROR = "#f26d6d"
FONT_NORMAL = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_HEADER = ("Segoe UI", 13, "bold")
FONT_SECTION = ("Segoe UI", 9, "bold")
FONT_MONO = ("Consolas", 9)

LOG_TAGS = {
    "info": ("INFO", LOG_INFO),
    "success": ("SUCCESS", LOG_SUCCESS),
    "warning": ("WARNING", LOG_WARNING),
    "error": ("ERROR", LOG_ERROR),
}

import stage_data
import shard_progress

MODES = ["Story", "Squadron", "Challenge", "Raid", "Invasion"]
DIFFICULTIES = stage_data.DIFFICULTIES


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_work_area():
    """Return desktop work area excluding the Windows taskbar."""
    rect = RECT()
    ok = ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    if not ok:
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        return 0, 0, sw, sh
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def dock_roblox_to_work_area(ui_width=UI_WIDTH, log_height=LOG_HEIGHT, title_substring=ROBLOX_TITLE):
    """Dock Roblox inside the usable work area, not underneath the taskbar."""
    work_x, work_y, work_w, work_h = get_work_area()
    hwnd = find_window(title_substring)
    if hwnd is None:
        return None, None, None, work_x, work_y, work_w, work_h

    roblox_width = max(300, work_w - ui_width)
    roblox_height = max(300, work_h - log_height)
    move_window(hwnd, work_x, work_y, roblox_width, roblox_height)
    return hwnd, roblox_width, roblox_height, work_x, work_y, work_w, work_h


class LauncherUI:
    """Pure UI object. launcher.py passes callbacks for behavior."""

    def __init__(self, root, on_start_stop, on_end_task, on_close):
        self.root = root
        self.on_start_stop = on_start_stop
        self.on_end_task = on_end_task
        self.on_close_callback = on_close

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BG)

        self._ui_hidden = False
        self._setup_style()
        self.roblox_bbox = None
        self._init_persistent_settings_vars()
        self._build_controls(root)

        self.log_win = tk.Toplevel(root)
        self.log_win.overrideredirect(True)
        self.log_win.attributes("-topmost", True)
        self.log_win.configure(bg=BG)
        self._build_log_bar(self.log_win)

        # Separate overlay that covers ONLY Roblox's native title bar area.
        # It does not stretch over the right control panel.
        self.title_win = tk.Toplevel(root)
        self.title_win.overrideredirect(True)
        self.title_win.attributes("-topmost", True)
        self.title_win.configure(bg=TITLE_BG)
        self._build_title_bar(self.title_win)

        self.dock_windows()

    # ---------- UI construction ----------

    def _build_title_bar(self, win):
        outer = tk.Frame(win, bg=TITLE_BG, highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill="both", expand=True)

        icon = tk.Label(outer, text="▣", bg=ACCENT, fg="#ffffff", font=("Segoe UI", 10, "bold"), width=2)
        icon.pack(side="left", padx=(10, 8), pady=6)

        tk.Label(outer, text=APP_TITLE_LEFT, bg=TITLE_BG, fg=TEXT_MAIN,
                 font=("Segoe UI", 10, "bold")).pack(side="left", pady=6)
        tk.Label(outer, text=" | ", bg=TITLE_BG, fg=TEXT_DIM,
                 font=("Segoe UI", 10, "bold")).pack(side="left", pady=6)
        tk.Label(outer, text=APP_TITLE_RIGHT, bg=TITLE_BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(side="left", pady=6)

    def _enable_mousewheel_scroll(self, canvas, toplevel):
        """Binds mousewheel scrolling for this canvas. Uses bind_all
        (needed so scrolling works while hovering over ANY child widget -
        labels, entries - not just bare canvas background), but with a
        toplevel check inside the handler and add='+' so multiple
        scrollable windows can coexist safely: each handler only acts if
        the wheel event actually happened within ITS OWN window, and
        stacking handlers with add='+' means one window's binding can
        never silently overwrite or break another's."""
        def handler(event):
            try:
                if event.widget.winfo_toplevel() == toplevel:
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass  # toplevel or canvas already destroyed - ignore
        canvas.bind_all("<MouseWheel>", handler, add="+")

    def _init_persistent_settings_vars(self):
        """Creates every settings variable ONCE at startup, loaded from
        disk - not lazily inside _build_settings_card/_build_shard_targets_card,
        which only run when the Settings popup is actually opened. Code
        elsewhere (is_discord_result_notify_enabled and friends, is_verbose_enabled,
        the Discord checks during farming, _save_settings on close) reads
        these regardless of whether Settings has ever been opened this
        session - if they were only created lazily, any of that code
        running first would crash with an AttributeError, which is
        exactly what was happening before this fix."""
        saved = load_settings()
        self.discord_webhook_var = tk.StringVar(value=saved["discord_webhook_url"])
        self.discord_notify_result_var = tk.BooleanVar(value=saved["discord_notify_result"])
        self.discord_notify_task_complete_var = tk.BooleanVar(value=saved["discord_notify_task_complete"])
        self.discord_notify_shard_drop_var = tk.BooleanVar(value=saved["discord_notify_shard_drop"])
        self.verbose_logging_var = tk.BooleanVar(value=saved.get("verbose_logging", False))
        self._verbose_logging_cache = self.verbose_logging_var.get()

        saved_targets = saved.get("shard_targets", {})
        self.shard_target_field_vars = {}
        for key, label, default, progress_key in stage_data.shard_target_rows():
            initial = saved_targets.get(key, str(default))
            self.shard_target_field_vars[key] = tk.StringVar(value=initial)

    def _build_controls(self, win):
        header = tk.Frame(win, bg=PANEL_BG, height=52)
        header.pack(fill="x", side="top")
        icon = tk.Label(header, text="▣", bg=ACCENT, fg="#ffffff",
                         font=("Segoe UI", 12, "bold"), width=2)
        icon.pack(side="left", padx=(14, 8), pady=12)
        tk.Label(header, text=f"{APP_TITLE_LEFT} | {APP_TITLE_RIGHT}", bg=PANEL_BG, fg=TEXT_MAIN,
                 font=FONT_HEADER, anchor="w").pack(side="left", pady=12)
        tk.Button(
            header, text="✕", command=self.on_close,
            bg=PANEL_BG, fg=TEXT_DIM, activebackground=PANEL_BG, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 11, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(side="right", padx=(0, 14))
        tk.Button(
            header, text="–", command=self.hide_ui,
            bg=PANEL_BG, fg=TEXT_DIM, activebackground=PANEL_BG, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 11, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(side="right")

        canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=BG)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._enable_mousewheel_scroll(canvas, win)

        body = tk.Frame(scroll_frame, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)

        self.queue = MissionQueue()
        self._build_selections_card(body)
        self._build_task_list_card(body)
        self._build_status_card(body)

    # ---- Selections card ----

    def _build_selections_card(self, body):
        card = tk.Frame(body, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x")
        card_inner = tk.Frame(card, bg=CARD_BG)
        card_inner.pack(fill="x", padx=14, pady=14)

        tk.Label(card_inner, text="SELECTIONS", bg=CARD_BG, fg=ACCENT,
                 font=FONT_SECTION, anchor="w").pack(fill="x", pady=(0, 10))

        self._field_label(card_inner, "MODE")
        self.mode_var = tk.StringVar(value=MODES[0])
        self.mode_box = ttk.Combobox(card_inner, textvariable=self.mode_var, values=MODES,
                                      state="readonly", style="Dark.TCombobox")
        self.mode_box.pack(fill="x", pady=(2, 10))
        self.mode_box.bind("<<ComboboxSelected>>", self.on_mode_change)

        # field2: World (Story/Squadron) / Challenge / Raid World / Invasion
        self.field2_frame = tk.Frame(card_inner, bg=CARD_BG)
        self.field2_frame.pack(fill="x")
        self.field2_label = self._field_label(self.field2_frame, "WORLD")
        self.field2_var = tk.StringVar()
        self.field2_box = ttk.Combobox(self.field2_frame, textvariable=self.field2_var,
                                        state="readonly", style="Dark.TCombobox")
        self.field2_box.pack(fill="x", pady=(2, 10))
        self.field2_box.bind("<<ComboboxSelected>>", self.on_field2_change)

        # field3: Chapter (Story/Squadron) / Stage (Raid/Invasion) - hidden for Challenge
        self.field3_frame = tk.Frame(card_inner, bg=CARD_BG)
        self.field3_frame.pack(fill="x")
        self.field3_label = self._field_label(self.field3_frame, "CHAPTER")
        self.field3_var = tk.StringVar()
        self.field3_box = ttk.Combobox(self.field3_frame, textvariable=self.field3_var,
                                        state="readonly", style="Dark.TCombobox")
        self.field3_box.pack(fill="x", pady=(2, 10))

        # difficulty - hidden for Challenge/Raid
        self.diff_frame = tk.Frame(card_inner, bg=CARD_BG)
        self.diff_frame.pack(fill="x")
        self.diff_label = self._field_label(self.diff_frame, "DIFFICULTY  ·  selected LAST")
        self.diff_var = tk.StringVar(value=DIFFICULTIES[0])
        self.diff_box = ttk.Combobox(self.diff_frame, textvariable=self.diff_var, values=DIFFICULTIES,
                                      state="readonly", style="Dark.TCombobox")
        self.diff_box.pack(fill="x", pady=(2, 10))

        self.runs_frame = tk.Frame(card_inner, bg=CARD_BG)
        self.runs_frame.pack(fill="x")
        self._field_label(self.runs_frame, "RUNS  ·  blank = no limit, run until Stop")
        self.repeat_var = tk.StringVar(value="1")
        self.repeat_spinbox = tk.Spinbox(
            self.runs_frame, from_=1, to=9999, textvariable=self.repeat_var,
            bg=FIELD_BG, fg=TEXT_MAIN, insertbackground=TEXT_MAIN, font=FONT_NORMAL,
            bd=0, buttonbackground=FIELD_BG, highlightbackground=BORDER,
            highlightthickness=1, highlightcolor=ACCENT, justify="left"
        )
        self.repeat_spinbox.pack(fill="x", pady=(2, 12), ipady=4)

        button_row = tk.Frame(card_inner, bg=CARD_BG)
        button_row.pack(fill="x", pady=(0, 10))

        self.go_button = tk.Button(
            button_row, text="▶   START", command=self.on_start_stop,
            bg=ACCENT, fg="#ffffff", activebackground=ACCENT_HOVER, activeforeground="#ffffff",
            font=FONT_BOLD, bd=0, relief="flat", cursor="hand2", height=2
        )
        self.go_button.pack(side="left", fill="x", expand=True, padx=(0, 6))

        tk.Button(
            button_row, text="+  ADD TASK", command=self.on_add_to_queue,
            bg=FIELD_BG, fg=TEXT_MAIN, activebackground=BORDER, activeforeground=TEXT_MAIN,
            font=FONT_BOLD, bd=0, relief="flat", cursor="hand2", height=2
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

        tk.Button(
            card_inner, text="END CURRENT TASK", command=self.on_end_task,
            bg=FIELD_BG, fg=LOG_WARNING, activebackground=BORDER, activeforeground=LOG_WARNING,
            font=("Segoe UI", 9, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(fill="x", pady=(8, 6))

        tk.Button(
            card_inner, text="SETTINGS", command=self.on_open_settings,
            bg=FIELD_BG, fg=TEXT_MAIN, activebackground=BORDER, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 9, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(fill="x")

        tk.Label(
            card_inner, text="F6: Start / Continue where it left off   ·   F7: Pause   ·   F8: Hide/Show UI",
            bg=CARD_BG, fg=TEXT_DIM, font=("Segoe UI", 8), anchor="w"
        ).pack(fill="x", pady=(8, 0))

        self.on_mode_change()  # populate field2/field3/difficulty for the initial mode

    # ---- Task list card ----

    def _build_task_list_card(self, body):
        card = tk.Frame(body, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(14, 0))
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="x", padx=14, pady=14)

        header = tk.Frame(inner, bg=CARD_BG)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="TASK LIST", bg=CARD_BG, fg=ACCENT,
                 font=FONT_SECTION, anchor="w").pack(side="left")
        tk.Button(
            header, text="🗑  CLEAR ALL", command=self.on_clear_all_tasks,
            bg=CARD_BG, fg=TEXT_DIM, activebackground=CARD_BG, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 8, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(side="right")

        tk.Button(
            inner, text="AUTO-QUEUE ALL TRAIT SHARD STAGES", command=self.on_auto_queue_trait_farm,
            bg=FIELD_BG, fg=TEXT_MAIN, activebackground=BORDER, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 9, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(fill="x", pady=(0, 10))

        self.task_list_container = tk.Frame(inner, bg=CARD_BG)
        self.task_list_container.pack(fill="x")

        self.task_list_empty_label = tk.Label(
            self.task_list_container, text="No tasks queued yet.", bg=CARD_BG, fg=TEXT_DIM,
            font=("Segoe UI", 9), anchor="w"
        )

        totals_row = tk.Frame(inner, bg=CARD_BG)
        totals_row.pack(fill="x", pady=(10, 0))
        self.total_tasks_var = tk.StringVar(value="TOTAL TASKS:  0")
        self.total_runs_var = tk.StringVar(value="TOTAL RUNS:  0")
        tk.Label(totals_row, textvariable=self.total_tasks_var, bg=CARD_BG, fg=TEXT_DIM,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
        tk.Label(totals_row, textvariable=self.total_runs_var, bg=CARD_BG, fg=TEXT_DIM,
                 font=("Segoe UI", 9, "bold"), anchor="e").pack(side="right")

        current_task_row = tk.Frame(inner, bg=FIELD_BG, highlightbackground=BORDER, highlightthickness=1)
        current_task_row.pack(fill="x", pady=(10, 0))
        tk.Label(current_task_row, text="CURRENTLY RUNNING", bg=FIELD_BG, fg=ACCENT,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        self.current_task_var = tk.StringVar(value="Nothing running yet.")
        tk.Label(current_task_row, textvariable=self.current_task_var, bg=FIELD_BG, fg=TEXT_MAIN,
                 font=("Segoe UI", 9, "bold"), anchor="w", wraplength=UI_WIDTH - 60,
                 justify="left").pack(fill="x", padx=10, pady=(0, 8))

        self._refresh_queue_listbox()

    def _render_task_row(self, index, mission):
        row = tk.Frame(self.task_list_container, bg=FIELD_BG, highlightbackground=BORDER,
                        highlightthickness=1)
        row.pack(fill="x", pady=(0, 6))

        tk.Label(
            row, text=f"{index + 1}.  {mission.label()}", bg=FIELD_BG, fg=TEXT_MAIN,
            font=("Segoe UI", 9), anchor="w", justify="left", wraplength=UI_WIDTH - 150
        ).pack(side="left", fill="x", expand=True, padx=(8, 4), pady=6)

        btns = tk.Frame(row, bg=FIELD_BG)
        btns.pack(side="right", padx=(0, 6))

        def make_btn(symbol, command):
            return tk.Button(
                btns, text=symbol, command=command,
                bg=FIELD_BG, fg=TEXT_DIM, activebackground=BORDER, activeforeground=TEXT_MAIN,
                font=("Segoe UI", 9, "bold"), bd=0, relief="flat", cursor="hand2", width=2
            )

        make_btn("↑", lambda i=index: self.on_move_task_up(i)).pack(side="left")
        make_btn("↓", lambda i=index: self.on_move_task_down(i)).pack(side="left")
        make_btn("✕", lambda i=index: self.on_remove_task(i)).pack(side="left")

    # ---- Status card ----

    def _build_status_card(self, body):
        card = tk.Frame(body, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(14, 0))
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="x", padx=14, pady=14)

        tk.Label(inner, text="STATUS", bg=CARD_BG, fg=ACCENT,
                 font=FONT_SECTION, anchor="w").pack(fill="x", pady=(0, 10))

        self._field_label(inner, "LOCAL TIME  ·  Trait Shards reset daily at 5pm Pacific")
        self.clock_var = tk.StringVar(value="--:--:--")
        tk.Label(inner, textvariable=self.clock_var, bg=CARD_BG, fg=TEXT_MAIN,
                 font=FONT_BOLD, anchor="w").pack(fill="x", pady=(0, 12))
        self._tick_clock()

        self.status_line_var = tk.StringVar(value="Idle - no mission running.")
        tk.Label(inner, textvariable=self.status_line_var, bg=CARD_BG, fg=LOG_SUCCESS,
                 font=FONT_BOLD, anchor="w").pack(fill="x", pady=(0, 12))

        self._field_label(inner, "RUN PROGRESS")
        self.run_progress_var = tk.StringVar(value="- / -")
        tk.Label(inner, textvariable=self.run_progress_var, bg=CARD_BG, fg=TEXT_MAIN,
                 font=FONT_BOLD, anchor="w").pack(fill="x", pady=(0, 12))

        self._field_label(inner, "TRAIT SHARDS  ·  overall progress across every known stage")
        self.shard_summary_var = tk.StringVar(value="- / -")
        tk.Label(inner, textvariable=self.shard_summary_var, bg=CARD_BG, fg=TEXT_MAIN,
                 font=FONT_BOLD, anchor="w").pack(fill="x")

        self._refresh_shard_summary()

    def _tick_clock(self):
        import reset_clock
        now = reset_clock.get_local_time()
        remaining = reset_clock.seconds_until_next_reset()
        if remaining is not None:
            hrs, rem = divmod(int(remaining), 3600)
            mins = rem // 60
            countdown = f" · reset in {hrs}h {mins}m"
        else:
            countdown = " · install 'tzdata' for reset countdown"
        self.clock_var.set(now.strftime("%I:%M:%S %p") + countdown)
        self.root.after(1000, self._tick_clock)

    def _refresh_shard_summary(self):
        """Recomputes total banked / total target across every known
        Trait Shard stage and updates the Status card - runs on its own
        timer independent of whether a farm is currently active, so it
        stays accurate even just sitting idle after a previous session."""
        total_banked = 0
        total_target = 0
        for key, label, default, progress_key in stage_data.shard_target_rows():
            total_banked += shard_progress.get_progress_by_key(progress_key)
            target = self.get_shard_target(key, default)
            if target:
                total_target += target
        if total_target:
            self.shard_summary_var.set(f"{total_banked} / {total_target}")
        else:
            self.shard_summary_var.set(f"{total_banked} banked (no targets set)")
        self.root.after(5000, self._refresh_shard_summary)

    def _build_settings_card(self, body):
        card = tk.Frame(body, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(14, 0))
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="x", padx=14, pady=14)

        tk.Label(inner, text="SETTINGS", bg=CARD_BG, fg=ACCENT,
                 font=FONT_SECTION, anchor="w").pack(fill="x", pady=(0, 10))

        self._field_label(inner, "DISCORD WEBHOOK URL")
        self.discord_webhook_entry = tk.Entry(
            inner, textvariable=self.discord_webhook_var, bg=FIELD_BG, fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN, font=("Segoe UI", 9), bd=0,
            highlightbackground=BORDER, highlightthickness=1, highlightcolor=ACCENT, show="*"
        )
        self.discord_webhook_entry.pack(fill="x", pady=(2, 10), ipady=4)
        self.discord_webhook_entry.bind("<FocusOut>", lambda e: self._save_settings())

        tk.Checkbutton(
            inner, text="Send a screenshot of Roblox after each victory/defeat",
            variable=self.discord_notify_result_var, command=self._save_settings,
            bg=CARD_BG, fg=TEXT_MAIN, selectcolor=FIELD_BG,
            activebackground=CARD_BG, activeforeground=TEXT_MAIN, font=("Segoe UI", 9),
            anchor="w", cursor="hand2"
        ).pack(fill="x", pady=(0, 4))

        tk.Checkbutton(
            inner, text="Send a message when a task finishes",
            variable=self.discord_notify_task_complete_var, command=self._save_settings,
            bg=CARD_BG, fg=TEXT_MAIN, selectcolor=FIELD_BG,
            activebackground=CARD_BG, activeforeground=TEXT_MAIN, font=("Segoe UI", 9),
            anchor="w", cursor="hand2"
        ).pack(fill="x", pady=(0, 4))

        tk.Checkbutton(
            inner, text="Send a message every time a Trait Shard drop is counted",
            variable=self.discord_notify_shard_drop_var, command=self._save_settings,
            bg=CARD_BG, fg=TEXT_MAIN, selectcolor=FIELD_BG,
            activebackground=CARD_BG, activeforeground=TEXT_MAIN, font=("Segoe UI", 9),
            anchor="w", cursor="hand2"
        ).pack(fill="x", pady=(0, 10))

        tk.Checkbutton(
            inner, text="Verbose logging (show every navigation step, not just results)",
            variable=self.verbose_logging_var, command=self._save_settings,
            bg=CARD_BG, fg=TEXT_MAIN, selectcolor=FIELD_BG,
            activebackground=CARD_BG, activeforeground=TEXT_MAIN, font=("Segoe UI", 9),
            anchor="w", cursor="hand2"
        ).pack(fill="x", pady=(0, 10))

        tk.Button(
            inner, text="TEST WEBHOOK", command=self.on_test_webhook,
            bg=FIELD_BG, fg=TEXT_MAIN, activebackground=BORDER, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 9, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(fill="x", pady=(0, 10))

        tk.Button(
            inner, text="📊  TRAIT SHARD TRACKER", command=self.on_open_shard_tracker,
            bg=ACCENT, fg="#ffffff", activebackground=ACCENT_HOVER, activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(fill="x")

    def _save_settings(self):
        existing = load_settings()
        existing["shard_targets"] = {key: var.get().strip() for key, var in self.shard_target_field_vars.items()}
        existing["discord_webhook_url"] = self.discord_webhook_var.get().strip()
        existing["discord_notify_result"] = self.discord_notify_result_var.get()
        existing["discord_notify_task_complete"] = self.discord_notify_task_complete_var.get()
        existing["discord_notify_shard_drop"] = self.discord_notify_shard_drop_var.get()
        existing.pop("discord_enabled", None)  # superseded by discord_notify_result
        existing["verbose_logging"] = self.verbose_logging_var.get()
        self._verbose_logging_cache = self.verbose_logging_var.get()
        save_settings(existing)

    def _build_shard_targets_card(self, body):
        card = tk.Frame(body, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(14, 0))
        inner = tk.Frame(card, bg=CARD_BG)
        inner.pack(fill="x", padx=14, pady=14)

        tk.Label(inner, text="TRAIT SHARD TARGETS", bg=CARD_BG, fg=ACCENT,
                 font=FONT_SECTION, anchor="w").pack(fill="x", pady=(0, 4))
        tk.Label(inner, text="How many shards to farm per stage (blank = farm until stopped).",
                 bg=CARD_BG, fg=TEXT_DIM, font=("Segoe UI", 8), anchor="w", wraplength=UI_WIDTH - 60,
                 justify="left").pack(fill="x", pady=(0, 10))

        for key, label, default, progress_key in stage_data.shard_target_rows():
            self._field_label(inner, label.upper())
            var = self.shard_target_field_vars[key]
            entry = tk.Entry(
                inner, textvariable=var, bg=FIELD_BG, fg=TEXT_MAIN,
                insertbackground=TEXT_MAIN, font=("Segoe UI", 9), bd=0,
                highlightbackground=BORDER, highlightthickness=1, highlightcolor=ACCENT
            )
            entry.pack(fill="x", pady=(2, 6), ipady=4)
            entry.bind("<FocusOut>", lambda e: self._save_settings())

            self._build_manual_progress_row(inner, progress_key)

        tk.Button(
            inner, text="⚠  RESET ALL TRAIT SHARDS", command=self.on_reset_all_shards,
            bg=CARD_BG, fg=LOG_ERROR, activebackground=BORDER, activeforeground=LOG_ERROR,
            font=("Segoe UI", 9, "bold"), bd=0, relief="flat", cursor="hand2",
            highlightbackground=LOG_ERROR, highlightthickness=1
        ).pack(fill="x", pady=(4, 0))

    def on_reset_all_shards(self):
        """Wipes ALL banked Trait Shard progress, for every stage - the
        same thing the daily 5pm-Pacific auto-reset does, but on demand.
        A native Yes/No confirm dialog is the required second check
        before anything actually gets cleared, since this can't be
        undone."""
        import tkinter.messagebox as messagebox
        confirmed = messagebox.askyesno(
            "Reset All Trait Shards",
            "This will permanently clear ALL banked Trait Shard progress for every stage.\n\n"
            "This can't be undone. Continue?",
            icon="warning",
        )
        if not confirmed:
            return
        shard_progress.clear_all()
        self.log("All Trait Shard progress has been reset.", "warning")
        if getattr(self, "_settings_win", None) is not None:
            try:
                if self._settings_win.winfo_exists():
                    self._settings_win.destroy()
                    self._settings_win = None
                    self.on_open_settings()
            except tk.TclError:
                pass

    def _build_manual_progress_row(self, parent, progress_key):
        row = tk.Frame(parent, bg=CARD_BG)
        row.pack(fill="x", pady=(0, 12))

        current = shard_progress.get_progress_by_key(progress_key)
        banked_var = tk.StringVar(value=f"Current: {current}")
        tk.Label(row, textvariable=banked_var, bg=CARD_BG, fg=TEXT_DIM,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left")

        add_var = tk.StringVar(value="")
        add_entry = tk.Entry(
            row, textvariable=add_var, width=6, bg=FIELD_BG, fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN, font=("Segoe UI", 9), bd=0,
            highlightbackground=BORDER, highlightthickness=1, highlightcolor=ACCENT
        )
        add_entry.pack(side="right", padx=(4, 0), ipady=2)

        def adjust(sign):
            raw = add_var.get().strip()
            if not raw.isdigit():
                self.log(f"Enter a whole number to add/subtract (got '{raw}').", "error")
                return
            new_total = max(0, shard_progress.get_progress_by_key(progress_key) + sign * int(raw))
            shard_progress.set_progress_by_key(progress_key, new_total)
            banked_var.set(f"Current: {new_total}")
            add_var.set("")
            self.log(f"Progress for this stage now at {new_total}.", "info")

        tk.Button(
            row, text="+", command=lambda: adjust(1), bg=FIELD_BG, fg=TEXT_MAIN,
            activebackground=BORDER, activeforeground=TEXT_MAIN, font=("Segoe UI", 9, "bold"),
            bd=0, relief="flat", cursor="hand2", width=2
        ).pack(side="right", padx=(2, 0))
        tk.Button(
            row, text="−", command=lambda: adjust(-1), bg=FIELD_BG, fg=TEXT_MAIN,
            activebackground=BORDER, activeforeground=TEXT_MAIN, font=("Segoe UI", 9, "bold"),
            bd=0, relief="flat", cursor="hand2", width=2
        ).pack(side="right", padx=(4, 0))

    def get_shard_target(self, key, default):
        """Reads the current (possibly user-edited) target for a given
        shard stage identity - falls back to the stage's default if the
        field is blank/invalid, or if the Settings popup (where these
        fields live) hasn't even been opened yet this session."""
        field_vars = getattr(self, "shard_target_field_vars", None)
        var = field_vars.get(key) if field_vars else None
        if var is None:
            return default
        raw = var.get().strip()
        if raw == "":
            return None
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        self.log(f"Shard target for '{key}' isn't a valid number ('{raw}') - using default {default}.", "warning")
        return default

    def _build_log_bar(self, win):
        log_header = tk.Frame(win, bg=PANEL_BG)
        log_header.pack(fill="x")
        tk.Label(log_header, text="LOGS", bg=PANEL_BG, fg=ACCENT,
                 font=FONT_SECTION).pack(side="left", padx=14, pady=8)
        tk.Button(
            log_header, text="CLEAR", command=self.clear_log,
            bg=PANEL_BG, fg=TEXT_DIM, activebackground=PANEL_BG, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 8, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(side="right", padx=14)

        self.log_box = tk.Text(
            win, state="disabled", wrap="word", bg=BG, fg=TEXT_MAIN,
            font=FONT_MONO, bd=0, padx=14, pady=6, insertbackground=TEXT_MAIN
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_configure("ts", foreground=TEXT_DIM)
        self.log_box.tag_configure("msg", foreground=TEXT_MAIN)
        for level, (_, color) in LOG_TAGS.items():
            self.log_box.tag_configure(f"tag_{level}", foreground=color, font=("Consolas", 9, "bold"))

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.TCombobox",
            fieldbackground=FIELD_BG, background=FIELD_BG, foreground=TEXT_MAIN,
            arrowcolor=TEXT_MAIN, bordercolor=BORDER, lightcolor=FIELD_BG, darkcolor=FIELD_BG,
            padding=6,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", FIELD_BG)],
            foreground=[("readonly", TEXT_MAIN)],
            selectbackground=[("readonly", FIELD_BG)],
            selectforeground=[("readonly", TEXT_MAIN)],
        )
        self.root.option_add("*TCombobox*Listbox.background", FIELD_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_MAIN)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.font", FONT_NORMAL)

    def _field_label(self, parent, text):
        label = tk.Label(parent, text=text, bg=CARD_BG, fg=TEXT_DIM, font=("Segoe UI", 8, "bold"),
                          anchor="w")
        label.pack(fill="x")
        return label

    # ---------- Values exposed to launcher.py ----------

    def get_selected_mode(self):
        return self.mode_var.get()

    def get_selected_difficulty(self):
        return self.diff_var.get().lower()

    def get_queue(self):
        return self.queue

    def get_discord_webhook_url(self):
        return self.discord_webhook_var.get().strip()

    def is_discord_result_notify_enabled(self):
        return self.discord_notify_result_var.get()

    def is_discord_task_complete_notify_enabled(self):
        return self.discord_notify_task_complete_var.get()

    def is_discord_shard_drop_notify_enabled(self):
        return self.discord_notify_shard_drop_var.get()

    def is_verbose_enabled(self):
        var = getattr(self, "verbose_logging_var", None)
        if var is not None:
            return var.get()
        return self._verbose_logging_cache

    def get_roblox_bbox(self):
        """Returns (left, top, width, height) of the docked Roblox
        window, or None if Roblox hasn't been found/docked yet."""
        return self.roblox_bbox

    def on_open_settings(self):
        """Opens a standalone Settings window containing the Discord
        webhook config and the per-stage Trait Shard target/manual-
        progress controls - moved out of the main panel into their own
        popup so the main panel stays compact."""
        if getattr(self, "_settings_win", None) is not None:
            try:
                if self._settings_win.winfo_exists():
                    self._settings_win.lift()
                    return
            except tk.TclError:
                pass

        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.configure(bg=BG)
        win.geometry("380x700")
        win.attributes("-topmost", True)
        self._settings_win = win

        header = tk.Frame(win, bg=PANEL_BG)
        header.pack(fill="x")
        tk.Label(header, text="SETTINGS", bg=PANEL_BG, fg=ACCENT,
                 font=FONT_BOLD).pack(side="left", padx=14, pady=10)

        canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=BG)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._enable_mousewheel_scroll(canvas, win)

        def close_settings():
            win.destroy()

        tk.Button(
            header, text="✕", command=close_settings, bg=PANEL_BG, fg=TEXT_DIM,
            activebackground=PANEL_BG, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 11, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(side="right", padx=14)
        win.protocol("WM_DELETE_WINDOW", close_settings)

        body = tk.Frame(scroll_frame, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)

        self._build_settings_card(body)
        self._build_shard_targets_card(body)

        def save_and_exit():
            self._save_settings()
            self.log("Settings saved successfully.", "success")
            close_settings()

        tk.Button(
            body, text="💾  SAVE & EXIT", command=save_and_exit,
            bg=ACCENT, fg="#ffffff", activebackground=ACCENT_HOVER, activeforeground="#ffffff",
            font=FONT_BOLD, bd=0, relief="flat", cursor="hand2", height=2
        ).pack(fill="x", pady=(14, 0))

    def on_open_shard_tracker(self):
        """Opens a standalone window listing every known Trait Shard
        stage with its current banked total, target, and percentage -
        auto-refreshing while open so it reflects live progress if a
        farm is currently running in the background."""
        if getattr(self, "_shard_tracker_win", None) is not None:
            try:
                if self._shard_tracker_win.winfo_exists():
                    self._shard_tracker_win.lift()
                    return
            except tk.TclError:
                pass

        win = tk.Toplevel(self.root)
        win.title("Trait Shard Tracker")
        win.configure(bg=BG)
        win.geometry("360x460")
        win.attributes("-topmost", True)
        self._shard_tracker_win = win

        header = tk.Frame(win, bg=PANEL_BG)
        header.pack(fill="x")
        tk.Label(header, text="TRAIT SHARD TRACKER", bg=PANEL_BG, fg=ACCENT,
                 font=FONT_BOLD).pack(side="left", padx=14, pady=10)
        tk.Button(
            header, text="✕", command=win.destroy, bg=PANEL_BG, fg=TEXT_DIM,
            activebackground=PANEL_BG, activeforeground=TEXT_MAIN,
            font=("Segoe UI", 11, "bold"), bd=0, relief="flat", cursor="hand2"
        ).pack(side="right", padx=14)

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)
        rows_container = tk.Frame(body, bg=BG)
        rows_container.pack(fill="both", expand=True)

        def refresh():
            for child in rows_container.winfo_children():
                child.destroy()
            for key, label, default, progress_key in stage_data.shard_target_rows():
                current = shard_progress.get_progress_by_key(progress_key)
                target = self.get_shard_target(key, default)

                row = tk.Frame(rows_container, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
                row.pack(fill="x", pady=(0, 8))
                tk.Label(row, text=label, bg=CARD_BG, fg=TEXT_MAIN, font=FONT_BOLD,
                         anchor="w", wraplength=300, justify="left").pack(fill="x", padx=10, pady=(8, 2))

                if target:
                    pct = min(100, current / target * 100)
                    done = current >= target
                    text = f"{current} / {target}  ({pct:.0f}%)" + ("  ✓ done" if done else "")
                    color = LOG_SUCCESS if done else TEXT_DIM
                else:
                    text = f"{current}  (no target set)"
                    color = TEXT_DIM
                tk.Label(row, text=text, bg=CARD_BG, fg=color, font=FONT_NORMAL,
                         anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        def auto_refresh():
            if not win.winfo_exists():
                return
            refresh()
            win.after(2000, auto_refresh)

        auto_refresh()

    def on_test_webhook(self):
        import discord_webhook
        url = self.get_discord_webhook_url()
        if not url:
            self.log("Enter a Discord webhook URL before testing.", "warning")
            return
        bbox = self.get_roblox_bbox()
        if bbox is None:
            self.log("Roblox isn't docked yet - open Roblox first so there's something to screenshot.", "warning")
            return
        self.log("Sending test screenshot to Discord...", "info")
        discord_webhook.send_screenshot_async(url, bbox, message="Test screenshot from the launcher.", log=self.log)

    def on_add_to_queue(self):
        mode = self.get_selected_mode()

        raw_repeat = self.repeat_var.get().strip()
        if raw_repeat == "":
            repeat_count = None  # no limit - run until Stop
        elif not raw_repeat.isdigit() or int(raw_repeat) < 1:
            self.log(f"Runs must be blank (no limit) or a whole number of 1 or more (got '{raw_repeat}').", "error")
            return
        else:
            repeat_count = int(raw_repeat)

        mission = self._build_mission(mode, repeat_count, shard_farming=False, shard_target=None)
        if mission is None:
            return  # error already logged by _build_mission

        self.queue.add(mission)
        self._refresh_queue_listbox()
        self.log(f"Added task: {mission.label()}", "info")

    def _build_mission(self, mode, repeat_count, shard_farming, shard_target):
        """Builds a Mission from the current field2/field3/difficulty
        selections, interpreted according to the selected mode. Returns
        None (after logging an error) if a required field is missing."""
        if mode in ("Story", "Squadron"):
            world_key = self._current_world_key()
            chapter_text = self.field3_var.get()
            if not world_key or not chapter_text:
                self.log("Pick a world and chapter first.", "error")
                return None
            return Mission(
                mode=mode, repeat_count=repeat_count,
                world_key=world_key, chapter=int(chapter_text),
                difficulty=self.get_selected_difficulty(),
                shard_farming=shard_farming, shard_target=shard_target,
            )

        if mode == "Challenge":
            challenge_key = self._current_challenge_key()
            if not challenge_key:
                self.log("Pick a challenge first.", "error")
                return None
            challenge_stage = self.field3_var.get() or None
            if stage_data.CHALLENGES[challenge_key]["stages"] and not challenge_stage:
                self.log("Pick a stage for this challenge first.", "error")
                return None
            return Mission(mode=mode, repeat_count=repeat_count,
                            challenge_key=challenge_key, challenge_stage=challenge_stage,
                            shard_farming=shard_farming, shard_target=shard_target)

        if mode == "Raid":
            raid_key = self._current_raid_key()
            stage_name = self.field3_var.get()
            if not raid_key or not stage_name:
                self.log("Pick a raid and stage first.", "error")
                return None
            has_difficulty = stage_data.RAIDS.get(raid_key, {}).get("has_difficulty")
            return Mission(mode=mode, repeat_count=repeat_count,
                            raid_key=raid_key, raid_stage=stage_name,
                            difficulty=self.get_selected_difficulty() if has_difficulty else None,
                            shard_farming=shard_farming, shard_target=shard_target)

        if mode == "Invasion":
            invasion_key = self._current_invasion_key()
            stage_name = self.field3_var.get()
            if not invasion_key or not stage_name:
                self.log("Pick an invasion and stage first.", "error")
                return None
            return Mission(
                mode=mode, repeat_count=repeat_count,
                invasion_key=invasion_key, invasion_stage=stage_name,
                difficulty=self.get_selected_difficulty(),
                shard_farming=shard_farming, shard_target=shard_target,
            )

        self.log(f"Unknown mode '{mode}'.", "error")
        return None

    def _selection_drops_shards(self, mode):
        if mode == "Challenge":
            return stage_data.stage_drops_shards("challenge", challenge_key=self._current_challenge_key(),
                                                  stage_name=self.field3_var.get() or None)
        if mode == "Raid":
            return stage_data.stage_drops_shards("raid", raid_key=self._current_raid_key(),
                                                  stage_name=self.field3_var.get())
        if mode == "Invasion":
            return stage_data.stage_drops_shards("invasion", invasion_key=self._current_invasion_key(),
                                                  stage_name=self.field3_var.get())
        return False

    def _current_world_key(self):
        worlds = stage_data.STORY_WORLDS if self.mode_var.get() == "Story" else stage_data.SQUADRON_WORLDS
        return dict(worlds).get(self.field2_var.get())

    def _current_challenge_key(self):
        display = self.field2_var.get()
        for key, challenge in stage_data.CHALLENGES.items():
            if challenge["display"] == display:
                return key
        return None

    def _current_raid_key(self):
        display = self.field2_var.get()
        for key, raid in stage_data.RAIDS.items():
            if raid["display"] == display:
                return key
        return None

    def _current_invasion_key(self):
        display = self.field2_var.get()
        for key, inv in stage_data.INVASIONS.items():
            if inv["display"] == display:
                return key
        return None

    def on_clear_all_tasks(self):
        self.queue.clear()
        self._refresh_queue_listbox()

    def on_auto_queue_trait_farm(self):
        """Queues every known Trait Shard-dropping stage in one go, each
        set to farm to its own target (read from the editable Trait
        Shard Targets card, falling back to stage_data's real per-stage
        caps). No run-count safety cap is applied - shard drops aren't
        guaranteed every run, so capping attempts risks stopping short
        of the target instead of just taking as many runs as it takes."""
        added = 0

        for challenge_key, challenge in stage_data.CHALLENGES.items():
            if not challenge["shard_stage"]:
                continue
            target = self.get_shard_target(f"challenge:{challenge_key}", challenge["shard_cap"])
            self.queue.add(Mission(
                mode="Challenge", repeat_count=None,
                challenge_key=challenge_key, challenge_stage=challenge["shard_stage"],
                shard_farming=True, shard_target=target,
            ))
            added += 1

        for raid_key, raid in stage_data.RAIDS.items():
            if not raid["shard_stage"]:
                continue
            target = self.get_shard_target(f"raid:{raid_key}", raid["shard_cap"])
            # Raids with a difficulty screen (GT City, Eclipse) should be
            # farmed on Hard - others don't need a difficulty set at all.
            raid_difficulty = "hard" if raid.get("has_difficulty") else None
            self.queue.add(Mission(
                mode="Raid", repeat_count=None,
                raid_key=raid_key, raid_stage=raid["shard_stage"], difficulty=raid_difficulty,
                shard_farming=True, shard_target=target,
            ))
            added += 1

        for invasion_key, invasion in stage_data.INVASIONS.items():
            if not invasion["shard_stage"]:
                continue
            for difficulty, default_cap in invasion.get("shard_caps", {}).items():
                target = self.get_shard_target(f"invasion:{invasion_key}:{difficulty.lower()}", default_cap)
                self.queue.add(Mission(
                    mode="Invasion", repeat_count=None,
                    invasion_key=invasion_key, invasion_stage=invasion["shard_stage"],
                    difficulty=difficulty.lower(),
                    shard_farming=True, shard_target=target,
                ))
                added += 1

        self._refresh_queue_listbox()
        self.log(f"Auto-queued {added} Trait Shard farming task(s) - no run cap, each runs until its target is hit.",
                  "success")

    def on_move_task_up(self, index):
        self.queue.move_up(index)
        self._refresh_queue_listbox()

    def on_move_task_down(self, index):
        self.queue.move_down(index)
        self._refresh_queue_listbox()

    def on_remove_task(self, index):
        self.queue.remove_at(index)
        self._refresh_queue_listbox()

    def _refresh_queue_listbox(self):
        for child in self.task_list_container.winfo_children():
            child.destroy()

        missions = self.queue.all()
        if not missions:
            self.task_list_empty_label = tk.Label(
                self.task_list_container, text="No tasks queued yet.", bg=CARD_BG, fg=TEXT_DIM,
                font=("Segoe UI", 9), anchor="w"
            )
            self.task_list_empty_label.pack(fill="x")
        else:
            for index, mission in enumerate(missions):
                self._render_task_row(index, mission)

        self.total_tasks_var.set(f"TOTAL TASKS:  {len(missions)}")
        total = self.queue.total_runs()
        suffix = "+" if self.queue.has_unlimited_mission() else ""
        self.total_runs_var.set(f"TOTAL RUNS:  {total}{suffix}")

    # ---- Status / progress (called by launcher.py while running) ----

    def set_status_line(self, text):
        self.status_line_var.set(text)

    def set_current_task_label(self, text):
        self.current_task_var.set(text)

    def set_run_progress(self, current, total):
        self.run_progress_var.set(f"{current} / {total}")

    def reset_status(self):
        self.set_status_line("Idle - no mission running.")
        self.set_current_task_label("Nothing running yet.")
        self.set_run_progress(0, 0)

    def set_running_state(self, running):
        if running:
            self.go_button.configure(text="⏸   STOP", bg="#555555")
        else:
            self.go_button.configure(text="▶   START", bg=ACCENT)

    # ---------- Window layout ----------

    def dock_windows(self):
        hwnd = find_window(ROBLOX_TITLE)
        if hwnd is None:
            self._layout_panels_only()
            self.log("Waiting for Roblox to open (checking every 1.5s)...", "warning")
            return False
        self._dock_now(hwnd)
        return True

    def _layout_panels_only(self):
        work_x, work_y, work_w, work_h = get_work_area()
        top_h = max(100, work_h - LOG_HEIGHT)
        panel_x = work_x + work_w - UI_WIDTH
        self.root.geometry(f"{UI_WIDTH}x{top_h}+{panel_x}+{work_y}")
        self.log_win.geometry(f"{work_w}x{LOG_HEIGHT}+{work_x}+{work_y + top_h}")
        self.title_win.geometry(f"{work_w - UI_WIDTH}x{TITLE_BAR_HEIGHT}+{work_x}+{work_y}")
        self.roblox_bbox = None

    def _dock_now(self, hwnd):
        hwnd, roblox_width, roblox_height, work_x, work_y, work_w, work_h = dock_roblox_to_work_area()
        self.roblox_bbox = (work_x, work_y, roblox_width, roblox_height)

        panel_x = work_x + roblox_width - PANEL_OVERLAP
        panel_w = work_x + work_w - panel_x
        log_y = work_y + roblox_height - LOG_OVERLAP
        log_h = work_y + work_h - log_y

        self.title_win.geometry(f"{roblox_width}x{TITLE_BAR_HEIGHT}+{work_x}+{work_y}")
        self.root.geometry(f"{panel_w}x{roblox_height}+{panel_x}+{work_y}")
        self.log_win.geometry(f"{work_w}x{log_h}+{work_x}+{log_y}")

        self.log(f"Docked: Roblox {roblox_width}x{roblox_height}, controls right, logs bottom.", "success")

    # ---------- UI events ----------

    def on_mode_change(self, event=None):
        mode = self.mode_var.get()

        def show(frame):
            frame.pack(fill="x", before=self.runs_frame)

        def hide(frame):
            frame.pack_forget()

        if mode in ("Story", "Squadron"):
            self.field2_label.configure(text="WORLD")
            worlds = stage_data.STORY_WORLDS if mode == "Story" else stage_data.SQUADRON_WORLDS
            self.field2_box.configure(values=[w[0] for w in worlds])
            self.field2_var.set(worlds[0][0])
            self.field3_label.configure(text="CHAPTER")
            show(self.field2_frame)
            show(self.field3_frame)
            show(self.diff_frame)
            self._refresh_chapter_options()

        elif mode == "Challenge":
            self.field2_label.configure(text="CHALLENGE")
            challenge_displays = [c["display"] for c in stage_data.CHALLENGES.values()]
            self.field2_box.configure(values=challenge_displays)
            self.field2_var.set(challenge_displays[0])
            self.field3_label.configure(text="STAGE")
            show(self.field2_frame)
            hide(self.diff_frame)
            self._refresh_challenge_stage_options()

        elif mode == "Raid":
            self.field2_label.configure(text="RAID")
            raid_displays = [r["display"] for r in stage_data.RAIDS.values()]
            self.field2_box.configure(values=raid_displays)
            self.field2_var.set(raid_displays[0])
            self.field3_label.configure(text="STAGE")
            show(self.field2_frame)
            show(self.field3_frame)
            self._refresh_raid_stage_options()

        elif mode == "Invasion":
            self.field2_label.configure(text="INVASION")
            inv_displays = [i["display"] for i in stage_data.INVASIONS.values()]
            self.field2_box.configure(values=inv_displays)
            self.field2_var.set(inv_displays[0])
            self.field3_label.configure(text="STAGE")
            show(self.field2_frame)
            show(self.field3_frame)
            show(self.diff_frame)
            self._refresh_invasion_stage_options()

    def on_field2_change(self, event=None):
        mode = self.mode_var.get()
        if mode in ("Story", "Squadron"):
            self._refresh_chapter_options()
        elif mode == "Challenge":
            self._refresh_challenge_stage_options()
        elif mode == "Raid":
            self._refresh_raid_stage_options()
        elif mode == "Invasion":
            self._refresh_invasion_stage_options()

    def _refresh_challenge_stage_options(self):
        challenge_key = self._current_challenge_key()
        stages = stage_data.CHALLENGES.get(challenge_key, {}).get("stages", [])
        if stages:
            self.field3_box.configure(values=stages)
            self.field3_var.set(stages[0])
            self.field3_frame.pack(fill="x", before=self.runs_frame)
        else:
            self.field3_frame.pack_forget()
            self.field3_var.set("")

    def _refresh_chapter_options(self):
        world_key = self._current_world_key()
        if self.mode_var.get() == "Story":
            max_chapter = stage_data.STORY_CHAPTER_COUNT
        else:
            max_chapter = stage_data.SQUADRON_CHAPTER_COUNTS.get(world_key, 1)
        values = [str(c) for c in range(1, max_chapter + 1)]
        self.field3_box.configure(values=values)
        self.field3_var.set(values[0])

    def _refresh_raid_stage_options(self):
        raid_key = self._current_raid_key()
        raid = stage_data.RAIDS.get(raid_key, {})
        stages = raid.get("stages", [])
        self.field3_box.configure(values=stages)
        if stages:
            self.field3_var.set(stages[0])

        if raid.get("has_difficulty"):
            self.diff_frame.pack(fill="x", before=self.runs_frame)
        else:
            self.diff_frame.pack_forget()

    def _refresh_invasion_stage_options(self):
        invasion_key = self._current_invasion_key()
        stages = stage_data.INVASIONS.get(invasion_key, {}).get("stages", [])
        self.field3_box.configure(values=stages)
        if stages:
            self.field3_var.set(stages[0])

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def on_close(self):
        self.on_close_callback()

    def hide_ui(self):
        """Withdraws all three windows that make up the UI (control panel,
        log bar, title bar overlay) without stopping whatever's running -
        useful for getting the panel out of the way. Since these windows
        are overrideredirect (no taskbar entry to click back), the only
        way back is toggle_ui_visibility (bound to a hotkey in
        launcher.py)."""
        if self._ui_hidden:
            return
        self._ui_hidden = True
        self.root.withdraw()
        self.log_win.withdraw()
        self.title_win.withdraw()

    def show_ui(self):
        if not self._ui_hidden:
            return
        self._ui_hidden = False
        self.root.deiconify()
        self.log_win.deiconify()
        self.title_win.deiconify()

    def toggle_ui_visibility(self):
        if self._ui_hidden:
            self.show_ui()
        else:
            self.hide_ui()

    def destroy(self):
        self._save_settings()
        for win in (self.title_win, self.log_win, self.root):
            try:
                win.destroy()
            except Exception:
                pass

    # ---------- Logging ----------

    def _classify(self, text):
        low = text.lower()
        if "warning" in low or "not found" in low or "may not have registered" in low:
            return "warning"
        if "error" in low or "missing" in low or "giving up" in low or "couldn't" in low:
            return "error"
        if "done!" in low or "clicked at" in low or "docked" in low or "detected -" in low or "found (score" in low:
            return "success"
        return "info"

    def log(self, text, level=None):
        tag = level or self._classify(text)
        label, _ = LOG_TAGS[tag]
        import time
        ts = time.strftime("%H:%M:%S")

        app_logging.write_log_line(text, tag)

        def _write():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"[{ts}] ", "ts")
            self.log_box.insert("end", f"[{label}] ", f"tag_{tag}")
            self.log_box.insert("end", text + "\n", "msg")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.root.after(0, _write)
