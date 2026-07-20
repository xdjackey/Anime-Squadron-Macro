"""
mission_queue.py
------------------
Keeps track of the list of tasks (missions) you've queued up - just
plain data, no visual stuff here.

A "Mission" is one row in the Task List: a mode/world/chapter/
difficulty combo, plus how many times in a row you want that exact
map repeated before moving on to the next queued task.
"""

from dataclasses import dataclass
from typing import Optional

import stage_data
import shard_progress


@dataclass
class Mission:
    mode: str                      # "Story", "Squadron", "Challenge", "Raid", "Invasion"
    # Fixed-run missions: exact run count. Shard-target missions: a safety
    # cap on max attempts. None = no limit, run/farm until Stop.
    repeat_count: Optional[int] = None

    # Story / Squadron
    world_key: Optional[str] = None
    chapter: Optional[int] = None
    difficulty: Optional[str] = None

    # Challenge
    challenge_key: Optional[str] = None
    challenge_stage: Optional[str] = None  # None if no sub-stage (Daily/Regular)

    # Raid
    raid_key: Optional[str] = None
    raid_stage: Optional[str] = None

    # Invasion (difficulty above is reused here too)
    invasion_key: Optional[str] = None
    invasion_stage: Optional[str] = None

    shard_farming: bool = False         # True = this mission farms Trait Shards
    # Farm until banked shards >= this (may overshoot by a run). None while
    # shard_farming = farm with no target, until Stop.
    shard_target: Optional[int] = None

    def label(self):
        """Short human-readable summary for the queue list box - uses
        display names (e.g. 'Eclipse (Before)', 'Hard') rather than raw
        internal keys (e.g. 'eclipse_before', 'hard')."""
        mode = self.mode
        if mode in ("Story", "Squadron"):
            world_display = stage_data.world_display_name(self.world_key)
            diff_display = (self.difficulty or "").capitalize()
            base = f"{mode} | {world_display} | Ch.{self.chapter} | {diff_display}"
        elif mode == "Challenge":
            challenge = stage_data.CHALLENGES.get(self.challenge_key, {})
            base = f"Challenge | {challenge.get('display', self.challenge_key)}"
            if self.challenge_stage:
                base += f" | {self.challenge_stage}"
            if self.difficulty:
                base += f" | {self.difficulty.capitalize()}"
        elif mode == "Raid":
            raid = stage_data.RAIDS.get(self.raid_key, {})
            base = f"Raid | {raid.get('display', self.raid_key)} | {self.raid_stage}"
            if self.difficulty:
                base += f" | {self.difficulty.capitalize()}"
        elif mode == "Invasion":
            invasion = stage_data.INVASIONS.get(self.invasion_key, {})
            diff_display = (self.difficulty or "").capitalize()
            base = f"Invasion | {invasion.get('display', self.invasion_key)} | {self.invasion_stage} | {diff_display}"
        else:
            base = mode

        if self.shard_farming:
            if self.shard_target:
                banked = shard_progress.get_progress(self)
                return f"{base} | {banked}/{self.shard_target} shards"
            return f"{base} | farm shards (runs until stopped)"
        if self.repeat_count is None:
            return f"{base} | runs until stopped"
        return f"{base} × {self.repeat_count}"


class MissionQueue:
    """Ordered list of Mission objects with simple add/remove/pop access.
    Kept dead simple on purpose - launcher.py just calls next_mission()
    in a loop until it returns None."""

    def __init__(self):
        self._missions = []

    def add(self, mission: Mission):
        self._missions.append(mission)

    def remove_at(self, index: int):
        if 0 <= index < len(self._missions):
            self._missions.pop(index)

    def clear(self):
        self._missions.clear()

    def all(self):
        return list(self._missions)

    def is_empty(self):
        return len(self._missions) == 0

    def pop_next(self):
        """Removes and returns the first mission in line, or None if the
        queue is empty."""
        if self.is_empty():
            return None
        return self._missions.pop(0)

    def push_front(self, mission: Mission):
        """Puts a mission back at the front of the queue - used when
        Stop interrupts it partway through, so Start resumes it first."""
        self._missions.insert(0, mission)

    def move_up(self, index: int):
        if 0 < index < len(self._missions):
            self._missions[index - 1], self._missions[index] = \
                self._missions[index], self._missions[index - 1]

    def move_down(self, index: int):
        if 0 <= index < len(self._missions) - 1:
            self._missions[index + 1], self._missions[index] = \
                self._missions[index], self._missions[index + 1]

    def total_runs(self):
        """Sum of repeat_count across all queued missions - unlimited
        (None) missions count as 0; see has_unlimited_mission()."""
        return sum(m.repeat_count for m in self._missions if m.repeat_count is not None)

    def has_unlimited_mission(self):
        return any(m.repeat_count is None for m in self._missions)

    def __len__(self):
        return len(self._missions)
