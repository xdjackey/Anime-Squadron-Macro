"""
shard_progress.py
--------------------
Saves your trait-shard farming progress to a file, tracked separately
for each specific stage. This is what lets you stop a shard-farming
task partway through and pick it back up later - even after closing
the app completely - without losing the shards you already banked.

Once a stage's target is actually reached, its saved progress gets
cleared, so farming that same stage again later starts fresh at 0
instead of thinking it's already done.
"""

import json
import os

import stage_data
import app_paths

PROGRESS_FILE = app_paths.path("shard_progress.json")


def _load_all():
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_all(data):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # a failed save shouldn't crash a farming run


def stage_key(mission):
    """Builds a stable identity string for a shard-farming mission's
    exact stage, so saved progress can be looked up regardless of what
    order things are queued in or how many times the app's been
    reopened since."""
    mode = mission.mode
    if mode == "Challenge":
        return stage_data.shard_stage_key("challenge", challenge_key=mission.challenge_key,
                                           challenge_stage=mission.challenge_stage)
    if mode == "Raid":
        return stage_data.shard_stage_key("raid", raid_key=mission.raid_key, raid_stage=mission.raid_stage)
    if mode == "Invasion":
        return stage_data.shard_stage_key("invasion", invasion_key=mission.invasion_key,
                                           invasion_stage=mission.invasion_stage, difficulty=mission.difficulty)
    return f"{mode}:{mission.world_key}:{mission.chapter}:{mission.difficulty}"


def get_progress(mission):
    """Returns the shard count already banked for this exact stage, or
    0 if there's nothing saved yet."""
    return get_progress_by_key(stage_key(mission))


def set_progress(mission, total_shards):
    """Saves the running total for this stage - call this after every
    single run's shard count is added in, not just at the end, so a
    forced-quit or crash loses at most one run's worth of progress."""
    set_progress_by_key(stage_key(mission), total_shards)


def clear_progress(mission):
    """Wipes saved progress for this stage - call once its target is
    actually reached, so farming it again later starts at 0 instead of
    immediately reporting 'already done'."""
    clear_progress_by_key(stage_key(mission))


def get_progress_by_key(key):
    """Same as get_progress, but takes the raw identity string directly
    - used by the settings UI, which knows a stage's key (from
    stage_data.shard_target_rows()) without needing a full Mission."""
    return _load_all().get(key, 0)


def set_progress_by_key(key, total_shards):
    data = _load_all()
    data[key] = total_shards
    _save_all(data)


def clear_progress_by_key(key):
    data = _load_all()
    if key in data:
        del data[key]
        _save_all(data)


def clear_all():
    """Wipes ALL saved shard progress, for every stage - used by the
    daily auto-reset and the manual 'Reset All Trait Shards' button."""
    _save_all({})
