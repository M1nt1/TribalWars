"""Troop type definitions and counts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class UnitType(StrEnum):
    SPEAR = "spear"
    SWORD = "sword"
    AXE = "axe"
    ARCHER = "archer"
    SPY = "spy"
    LIGHT = "light"
    MARCHER = "marcher"
    HEAVY = "heavy"
    RAM = "ram"
    CATAPULT = "catapult"
    KNIGHT = "knight"
    SNOB = "snob"


# Units trained in each building
BARRACKS_UNITS = [UnitType.SPEAR, UnitType.SWORD, UnitType.AXE, UnitType.ARCHER]
STABLE_UNITS = [UnitType.SPY, UnitType.LIGHT, UnitType.MARCHER, UnitType.HEAVY]
WORKSHOP_UNITS = [UnitType.RAM, UnitType.CATAPULT]


class TroopCounts(BaseModel):
    """Troop counts keyed by unit type name."""

    counts: dict[str, int] = Field(default_factory=dict)

    def get(self, unit: str) -> int:
        return self.counts.get(unit, 0)

    def set(self, unit: str, count: int) -> None:
        self.counts[unit] = count

    def total(self) -> int:
        return sum(self.counts.values())

    def has_enough(self, required: dict[str, int]) -> bool:
        return all(self.get(unit) >= count for unit, count in required.items())

    def subtract(self, other: dict[str, int]) -> TroopCounts:
        new_counts = dict(self.counts)
        for unit, count in other.items():
            new_counts[unit] = max(0, new_counts.get(unit, 0) - count)
        return TroopCounts(counts=new_counts)


class TrainQueue(BaseModel):
    """Training queue entry."""

    unit: str
    count: int
    finish_time: datetime | None = None
