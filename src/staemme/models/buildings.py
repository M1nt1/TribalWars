"""Building definitions, levels, and queue models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from staemme.models.village import Resources


class Building(BaseModel):
    name: str
    level: int = 0
    max_level: int = 30
    cost: Resources = Resources()
    build_time: int = 0  # seconds


class BuildStep(BaseModel):
    """A single step in a sequential build order."""

    building: str
    level: int


class BuildQueue(BaseModel):
    """An entry in the building queue."""

    building: str
    target_level: int
    finish_time: datetime | None = None


# Building internal names used by the game
BUILDING_NAMES = [
    "main",       # Headquarters
    "barracks",   # Barracks
    "stable",     # Stable
    "garage",     # Workshop
    "watchtower", # Watchtower
    "snob",       # Academy
    "smith",      # Smithy
    "place",      # Rally Point
    "statue",     # Statue
    "market",     # Market
    "wood",       # Timber Camp
    "stone",      # Clay Pit
    "iron",       # Iron Mine
    "farm",       # Farm
    "storage",    # Warehouse
    "hide",       # Hiding Place
    "wall",       # Wall
]

# Display names for the side panel dropdown
BUILDING_LABELS: dict[str, str] = {
    "main": "Headquarters",
    "barracks": "Barracks",
    "stable": "Stable",
    "garage": "Workshop",
    "watchtower": "Watchtower",
    "snob": "Academy",
    "smith": "Smithy",
    "place": "Rally Point",
    "statue": "Statue",
    "market": "Market",
    "wood": "Timber Camp",
    "stone": "Clay Pit",
    "iron": "Iron Mine",
    "farm": "Farm",
    "storage": "Warehouse",
    "hide": "Hiding Place",
    "wall": "Wall",
}
