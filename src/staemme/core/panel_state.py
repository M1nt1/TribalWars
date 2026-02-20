"""Panel state store — survives DOM resets, serialized to JS on reinject."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogEntry:
    timestamp: float
    message: str
    level: str = "info"


@dataclass
class TimerState:
    label: str
    end_ts: float  # unix timestamp
    category: str = ""


@dataclass
class VillageStatus:
    village_id: int
    name: str = ""
    x: int = 0
    y: int = 0
    points: int = 0
    wood: int = 0
    stone: int = 0
    iron: int = 0
    storage: int = 0
    population: int = 0
    max_population: int = 0
    incoming: int = 0
    wood_rate: int = 0
    stone_rate: int = 0
    iron_rate: int = 0


@dataclass
class VillageConfig:
    """Per-village feature overrides. None = inherit global."""

    building: bool | None = None
    farming: bool | None = None
    scavenging: bool | None = None
    troops: bool | None = None


class PanelStateStore:
    """Holds all side-panel state in Python so it survives DOM resets."""

    def __init__(self) -> None:
        self.logs: list[LogEntry] = []
        self.timers: dict[str, TimerState] = {}
        self.village_statuses: dict[int, VillageStatus] = {}
        self.village_configs: dict[int, VillageConfig] = {}
        self.village_ids: list[int] = []
        self.active_village_id: int = 0
        self.bot_state: str = "stopped"
        self.toggle_states: dict[str, bool] = {}
        self.active_tab: str = "dashboard"
        self.troops_mode_label: str = ""
        self.log_filter: str = "all"
        self.farm_lc_threshold: int = 20
        # Build queue editor state (per-village)
        self.build_queues: dict[int, list[dict]] = {}  # {vid: [{"building":"main","level":10}, ...]}
        self.building_levels: dict[int, dict[str, int]] = {}  # {vid: {"main":5, ...}}
        # Scavenge troop config: {unit: {"enabled": bool, "reserve": int}}
        self.scavenge_troops: dict[str, dict] = {}
        # Bot protection state
        self.bot_protection_detected: bool = False
        self.bot_protection_pattern: str = ""
        # Fill-scavenge training unit
        self.fill_unit: str = "spear"

    def add_log(self, message: str, level: str = "info") -> LogEntry:
        entry = LogEntry(timestamp=time.time(), message=message, level=level)
        self.logs.append(entry)
        # Cap at 200
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]
        return entry

    def set_timer(self, timer_id: str, label: str, end_ts: float, category: str = "") -> None:
        self.timers[timer_id] = TimerState(label=label, end_ts=end_ts, category=category)

    def clear_timer(self, timer_id: str) -> None:
        self.timers.pop(timer_id, None)

    def set_village_status(self, status: VillageStatus) -> None:
        self.village_statuses[status.village_id] = status

    def sync_scavenge_troops(self, config) -> None:
        """Populate scavenge_troops from ScavengingConfig."""
        from staemme.core.scavenge_formulas import SCAVENGE_UNITS

        for unit in SCAVENGE_UNITS:
            self.scavenge_troops[unit] = {
                "enabled": unit not in config.scavenge_exclude,
                "reserve": config.scavenge_reserve.get(unit, 0),
            }

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize full state for JS hydration."""
        now = time.time()

        # Filter expired timers
        active_timers = {
            tid: {"label": t.label, "end_ts": t.end_ts, "category": t.category}
            for tid, t in self.timers.items()
            if t.end_ts > now
        }

        logs_data = [
            {"ts": e.timestamp, "msg": e.message, "lvl": e.level}
            for e in self.logs[-200:]
        ]

        statuses = {}
        for vid, vs in self.village_statuses.items():
            statuses[vid] = {
                "name": vs.name, "x": vs.x, "y": vs.y, "points": vs.points,
                "wood": vs.wood, "stone": vs.stone, "iron": vs.iron,
                "storage": vs.storage, "pop": vs.population, "pop_max": vs.max_population,
                "incoming": vs.incoming,
                "wood_rate": vs.wood_rate, "stone_rate": vs.stone_rate, "iron_rate": vs.iron_rate,
            }

        configs = {}
        for vid, vc in self.village_configs.items():
            configs[vid] = {
                "building": vc.building, "farming": vc.farming,
                "scavenging": vc.scavenging, "troops": vc.troops,
            }

        # Build queues — keys must be strings for JSON
        bq = {str(vid): steps for vid, steps in self.build_queues.items()}
        bl = {str(vid): lvls for vid, lvls in self.building_levels.items()}

        return {
            "logs": logs_data,
            "timers": active_timers,
            "village_statuses": statuses,
            "village_configs": configs,
            "village_ids": self.village_ids,
            "active_village_id": self.active_village_id,
            "bot_state": self.bot_state,
            "toggle_states": self.toggle_states,
            "active_tab": self.active_tab,
            "troops_mode_label": self.troops_mode_label,
            "log_filter": self.log_filter,
            "build_queues": bq,
            "building_levels": bl,
            "farm_lc_threshold": self.farm_lc_threshold,
            "scavenge_troops": self.scavenge_troops,
            "bot_protection_detected": self.bot_protection_detected,
            "bot_protection_pattern": self.bot_protection_pattern,
            "fill_unit": self.fill_unit,
        }
