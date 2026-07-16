"""
manual_credits.py
--------------------
Lets you manually credit trait shards you earned WITHOUT the launcher
tracking them - e.g. you played a stage by hand instead of running the
farmer, or the launcher was closed while you kept playing.

Edit manual_shard_credits.json directly in any text editor: type in how
many shards you got for a given stage, save the file, and the next time
you START the launcher it adds that amount into the tracked progress
for that stage and resets the file's number back to 0 (so it doesn't
get applied again the following launch).

The file is auto-created - with every known shard-dropping stage listed
at 0 - the first time the launcher runs, so there's nothing to set up
by hand; just open manual_shard_credits.json, fill in a number next to
whichever stage you played, save, and start the launcher.
"""

import json
import os

import stage_data
import shard_progress

CREDITS_FILE = "manual_shard_credits.json"


def _build_template():
    """One entry per known shard-dropping stage, keyed by its
    human-readable label (not the internal progress key) so the file is
    editable by hand without needing to know any internal format."""
    return {label: 0 for _, label, _, _ in stage_data.shard_target_rows()}


def _label_to_progress_key():
    return {label: progress_key for _, label, _, progress_key in stage_data.shard_target_rows()}


def ensure_file_exists():
    """Creates manual_shard_credits.json with every known stage at 0 if
    it doesn't exist yet. Safe to call every startup - does nothing if
    the file's already there (so it won't stomp on numbers you've typed
    in but haven't had applied yet)."""
    if not os.path.exists(CREDITS_FILE):
        with open(CREDITS_FILE, "w") as f:
            json.dump(_build_template(), f, indent=2)


def apply_credits(log=print):
    """Reads manual_shard_credits.json, adds any nonzero amounts into
    the real tracked progress for their matching stage, logs what
    happened, and resets those entries back to 0 so they're not
    re-applied on the next startup. Call this once, early, every time
    the launcher starts."""
    ensure_file_exists()

    try:
        with open(CREDITS_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        log(f"[credits] Couldn't read {CREDITS_FILE}: {e}", "error")
        return

    label_to_key = _label_to_progress_key()
    changed = False

    for label, amount in list(data.items()):
        if not isinstance(amount, (int, float)) or amount == 0:
            continue

        progress_key = label_to_key.get(label)
        if progress_key is None:
            log(f"[credits] '{label}' in {CREDITS_FILE} doesn't match any known stage - "
                f"skipping (did a stage name change?).", "warning")
            continue

        amount = int(amount)
        current = shard_progress.get_progress_by_key(progress_key)
        new_total = max(0, current + amount)
        shard_progress.set_progress_by_key(progress_key, new_total)
        log(f"[credits] Manually credited '{label}': {'+' if amount >= 0 else ''}{amount} "
            f"-> now {new_total} banked.", "success")
        data[label] = 0
        changed = True

    if changed:
        try:
            with open(CREDITS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log(f"[credits] Applied credits but couldn't reset {CREDITS_FILE} back to 0: {e}", "warning")
