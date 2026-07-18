"""
shard_progress.py
--------------------
Saves trait-shard farming progress per stage, so a task can be stopped
and resumed later without losing banked shards. Progress clears once a
stage's target is reached, so farming it again starts fresh at 0.
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
    """Stable identity string for a mission's exact stage, used to look
    up its saved progress."""
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
    """Shard count already banked for this stage, or 0."""
    return get_progress_by_key(stage_key(mission))


def set_progress(mission, total_shards):
    """Saves the running total - call after every run, not just at the
    end, so a crash loses at most one run's progress."""
    set_progress_by_key(stage_key(mission), total_shards)


def clear_progress(mission):
    """Wipes saved progress for this stage - call once its target is
    reached, so farming it again starts at 0."""
    clear_progress_by_key(stage_key(mission))


def get_progress_by_key(key):
    """Same as get_progress, but takes the raw key directly - used by
    the settings UI, which doesn't have a full Mission."""
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
    """Wipes saved progress for every stage - used by the daily auto-
    reset and the manual 'Reset All Trait Shards' button."""
    _save_all({})
