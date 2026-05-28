"""Boss mechanic registry and base data structures."""

from dataclasses import dataclass


@dataclass
class DeathInfo:
    player_name: str
    player_id: int
    timestamp_ms: int
    fight_relative_ms: int
    cause_id: str
    cause_label: str
    cause_description: str
    killing_ability: str
    killing_ability_id: int
    death_order: int
    is_wipe_death: bool


@dataclass
class WipeInfo:
    cause_id: str
    cause_label: str
    cause_description: str
    timestamp_ms: int


@dataclass
class PullResult:
    pull_number: int
    fight_id: int
    duration_ms: int
    phase_reached: str
    is_kill: bool
    wipe: WipeInfo | None
    deaths: list[DeathInfo]
    fight_start_ms: int


BOSS_REGISTRY: dict[str, object] = {}


def register_boss(name: str):
    def decorator(cls):
        BOSS_REGISTRY[name] = cls()
        return cls
    return decorator


def get_boss(fight_name: str):
    return BOSS_REGISTRY.get(fight_name)
