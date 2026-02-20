"""Village state, resources, and overview models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Resources(BaseModel):
    wood: int = 0
    stone: int = 0
    iron: int = 0

    @property
    def total(self) -> int:
        return self.wood + self.stone + self.iron

    def can_afford(self, cost: Resources) -> bool:
        return self.wood >= cost.wood and self.stone >= cost.stone and self.iron >= cost.iron

    def __sub__(self, other: Resources) -> Resources:
        return Resources(
            wood=self.wood - other.wood,
            stone=self.stone - other.stone,
            iron=self.iron - other.iron,
        )

    def __add__(self, other: Resources) -> Resources:
        return Resources(
            wood=self.wood + other.wood,
            stone=self.stone + other.stone,
            iron=self.iron + other.iron,
        )


class Village(BaseModel):
    id: int
    name: str = ""
    x: int = 0
    y: int = 0
    points: int = 0
    resources: Resources = Field(default_factory=Resources)
    storage: int = 0
    population: int = 0
    max_population: int = 0
    production: Resources = Field(default_factory=Resources)  # per-hour rates
    buildings: dict[str, int] = Field(default_factory=dict)  # name -> level
    incoming_attacks: int = 0
    last_updated: datetime | None = None

    def distance_to(self, x: int, y: int) -> float:
        return ((self.x - x) ** 2 + (self.y - y) ** 2) ** 0.5
