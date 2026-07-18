"""
stage_data.py
---------------
The master list of everything selectable in the app - every world,
challenge, raid, and invasion, how many chapters each has, and which
specific stages drop Trait Shards. The app's dropdowns are built from
this list, and it's also used to double check whether a stage you
picked for shard farming actually drops shards or not.
"""

import re


def world_display_name(world_key):
    """'eclipse_before' -> 'Eclipse (Before)' - for showing clean labels
    in the Task List instead of raw internal keys."""
    return dict((key, display) for display, key in STORY_WORLDS).get(world_key, world_key)


def slugify(name):
    """'The Ultimate Evil' -> 'the_ultimate_evil' - used to build icon
    keys out of display names consistently everywhere."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


DIFFICULTIES = ["Normal", "Hard"]

# ---- Story ----
STORY_WORLDS = [
    ("GT City", "gt_city"),
    ("Marine Lobby", "marine_lobby"),
    ("Ninja Village", "ninja_village"),
    ("Eclipse (Before)", "eclipse_before"),
    ("The Ice Continent", "ice_continent"),
    ("Infinity Train", "infinity_train"),
]
STORY_CHAPTER_COUNT = 10  # every Story world goes up to chapter 10

# ---- Squadron: same worlds as Story, fewer chapters each ----
SQUADRON_WORLDS = STORY_WORLDS
SQUADRON_CHAPTER_COUNTS = {
    "gt_city": 3,
    "marine_lobby": 3,
    "ninja_village": 4,
    "eclipse_before": 4,
    "ice_continent": 4,
    "infinity_train": 4,
}

# ---- Challenge: some (Daily/Regular) have no stage selection - just
# click and go. Others (Katakara Bridge, Hero Hunter) have one named
# stage that drops Trait Shards. ----
CHALLENGES = {
    "daily_challenge": {"display": "Daily Challenge", "stages": [], "shard_stage": None, "shard_cap": None},
    "regular_challenge": {"display": "Regular Challenge", "stages": [], "shard_stage": None, "shard_cap": None},
    "katakara_bridge": {
        "display": "Katakara Bridge",
        "stages": ["A Dark Awakening"],
        "shard_stage": "A Dark Awakening",
        "shard_cap": 100,
    },
    "hero_hunter": {
        "display": "The Hero Hunter",
        "stages": ["The Hero Hunter Awakens"],
        "shard_stage": "The Hero Hunter Awakens",
        "shard_cap": 30,  # caps at 30/day, unlike the other shard stages
    },
}

# ---- Raid: shard_stage is the one stage per world that drops Trait
# Shards, or None if that world has none. ----
RAIDS = {
    "gt_city": {
        "display": "GT City",
        "stages": ["Hidden Danger", "Saiyan Hunt", "Ruler Dragon", "The Ultimate Evil"],
        "shard_stage": "The Ultimate Evil",
        "shard_cap": 100,
        "has_difficulty": True,
    },
    "eclipse": {
        "display": "Eclipse",
        "stages": ["Golden Age", "Golden Age II", "Golden Age III", "The Eclipse"],
        "shard_stage": "The Eclipse",
        "shard_cap": 100,
        "has_difficulty": True,
    },
    "infinity_train": {
        "display": "Infinity Train",
        "stages": ["Demon's Awakening", "Bloodmoon Rising", "Feast of Shadows", "Runaway Express"],
        "shard_stage": None,
        "shard_cap": None,
        "has_difficulty": True,
    },
}

# ---- Invasion: same shape as Raid, plus difficulty. shard_caps is
# informational only (the game's own per-difficulty daily cap) - queue
# Normal and Hard as separate tasks with those targets to reproduce it. ----
INVASIONS = {
    "lava_continent": {
        "display": "The Lava Continent",
        "stages": ["Infernal Landmass", "Ashfall Continent", "Magma Rift", "Scorched Horizon"],
        "shard_stage": "Scorched Horizon",
        "shard_caps": {"Normal": 40, "Hard": 60},
    },
}


def shard_stage_key(mode, **kwargs):
    """Canonical identity string for a shard-farming stage - same format
    shard_progress.py persists under, so the settings UI and the farming
    logic can never drift apart."""
    mode = mode.lower()
    if mode == "challenge":
        return f"challenge:{kwargs['challenge_key']}:{kwargs['challenge_stage']}"
    if mode == "raid":
        return f"raid:{kwargs['raid_key']}:{kwargs['raid_stage']}"
    if mode == "invasion":
        return f"invasion:{kwargs['invasion_key']}:{kwargs['invasion_stage']}:{kwargs['difficulty']}"
    raise ValueError(f"shard_stage_key: unsupported mode '{mode}'")


def shard_target_rows():
    """Every known Trait Shard-dropping stage as an editable row:
    (settings_key, label, default_target, progress_key) - ui.py uses
    this to build one target + manual-progress field per stage."""
    rows = []
    for challenge_key, challenge in CHALLENGES.items():
        if challenge["shard_stage"]:
            progress_key = shard_stage_key("challenge", challenge_key=challenge_key,
                                            challenge_stage=challenge["shard_stage"])
            rows.append((
                f"challenge:{challenge_key}",
                f"{challenge['display']} ({challenge['shard_stage']})",
                challenge["shard_cap"],
                progress_key,
            ))
    for raid_key, raid in RAIDS.items():
        if raid["shard_stage"]:
            progress_key = shard_stage_key("raid", raid_key=raid_key, raid_stage=raid["shard_stage"])
            rows.append((
                f"raid:{raid_key}",
                f"{raid['display']} Raid ({raid['shard_stage']})",
                raid["shard_cap"],
                progress_key,
            ))
    for invasion_key, invasion in INVASIONS.items():
        if invasion["shard_stage"]:
            for difficulty, cap in invasion.get("shard_caps", {}).items():
                progress_key = shard_stage_key("invasion", invasion_key=invasion_key,
                                                invasion_stage=invasion["shard_stage"],
                                                difficulty=difficulty.lower())
                rows.append((
                    f"invasion:{invasion_key}:{difficulty.lower()}",
                    f"{invasion['display']} ({difficulty})",
                    cap,
                    progress_key,
                ))
    return rows


def challenge_stage_icon_key(challenge_key, stage_name):
    return f"challenge_{challenge_key}_{slugify(stage_name)}"


def raid_stage_icon_key(raid_key, stage_name):
    return f"raid_{raid_key}_{slugify(stage_name)}"


def invasion_stage_icon_key(invasion_key, stage_name):
    return f"invasion_{invasion_key}_{slugify(stage_name)}"


def stage_drops_shards(mode, **kwargs):
    """Returns True if the given selection is known to drop Trait
    Shards, based on the data above. Used to warn (not block) if
    shard-farming is requested on a stage that doesn't drop any."""
    mode = mode.lower()
    if mode == "challenge":
        challenge_key = kwargs.get("challenge_key")
        stage_name = kwargs.get("stage_name")
        challenge = CHALLENGES.get(challenge_key)
        if not challenge or challenge["shard_stage"] is None:
            return False
        return challenge["shard_stage"] == stage_name
    if mode == "raid":
        raid_key = kwargs.get("raid_key")
        stage_name = kwargs.get("stage_name")
        raid = RAIDS.get(raid_key)
        if not raid or raid["shard_stage"] is None:
            return False
        return raid["shard_stage"] == stage_name
    if mode == "invasion":
        invasion_key = kwargs.get("invasion_key")
        stage_name = kwargs.get("stage_name")
        invasion = INVASIONS.get(invasion_key)
        if not invasion or invasion["shard_stage"] is None:
            return False
        return invasion["shard_stage"] == stage_name
    return False  # Story/Squadron aren't known to drop Trait Shards at all
