"""Farm target tracking model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from staemme.models.village import Resources


class FarmTarget(BaseModel):
    id: int  # village ID
    x: int = 0
    y: int = 0
    points: int = 0
    is_barbarian: bool = True
    wall_level: int = 0
    last_loot: Resources = Field(default_factory=Resources)
    has_troops: bool = False
    blacklisted: bool = False
    last_attacked: datetime | None = None
    attack_count: int = 0

    def distance_from(self, x: int, y: int) -> float:
        return ((self.x - x) ** 2 + (self.y - y) ** 2) ** 0.5
