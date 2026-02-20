"""World configuration and game data models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from staemme.models.village import Resources


class UnitInfo(BaseModel):
    """Stats for a single unit type, from /interface.php?func=get_unit_info."""

    name: str
    pop: int = 1
    speed: float = 1.0
    attack: int = 0
    defense: int = 0
    defense_cavalry: int = 0
    defense_archer: int = 0
    carry: int = 0
    cost: Resources = Field(default_factory=Resources)
    build_time: float = 0


class BuildingInfo(BaseModel):
    """Base info for a building type, from /interface.php?func=get_building_info."""

    name: str
    max_level: int = 30
    min_level: int = 0
    wood_factor: float = 1.0
    stone_factor: float = 1.0
    iron_factor: float = 1.0
    pop_factor: float = 1.0
    build_time_factor: float = 1.0


class WorldConfig(BaseModel):
    """World-level config from /interface.php?func=get_config."""

    speed: float = 1.0
    unit_speed: float = 1.0
    moral: bool = True
    build_destroy: bool = True
    knight: bool = True
    archer: bool = False
    church: bool = False
    watchtower: bool = False
    milliseconds_arrival: bool = False
    max_build_queue: int = 2  # 1 without premium, 2 with
    night_active: bool = False
    night_start: str = "00:00"
    night_end: str = "08:00"
    units: dict[str, UnitInfo] = Field(default_factory=dict)
    buildings: dict[str, BuildingInfo] = Field(default_factory=dict)
