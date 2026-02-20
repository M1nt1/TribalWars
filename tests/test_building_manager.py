"""Tests for the building manager."""

from __future__ import annotations

import pytest

from staemme.core.config import BuildingConfig
from staemme.managers.building_manager import BuildingManager
from staemme.models.buildings import BuildStep
from staemme.models.village import Resources


class TestBuildingManagerPriority:
    def setup_method(self):
        config = BuildingConfig(enabled=True, template="templates/offensive.toml")
        # We pass None for hq since we're only testing priority logic
        self.manager = BuildingManager(config, hq=None)
        self.manager.target_levels = {
            "main": 20,
            "barracks": 25,
            "farm": 30,
            "wall": 20,
        }
        self.manager.priority_order = ["main", "farm", "barracks", "wall"]

    def test_picks_highest_priority_below_target(self):
        current = {"main": 20, "barracks": 10, "farm": 15, "wall": 5}
        result = self.manager._pick_next_building(current)
        assert result is not None
        assert result[0] == "farm"  # first priority below target
        assert result[1] == 15  # current level
        assert result[2] == 30  # target level

    def test_all_at_target(self):
        current = {"main": 20, "barracks": 25, "farm": 30, "wall": 20}
        result = self.manager._pick_next_building(current)
        assert result is None

    def test_missing_buildings_treated_as_zero(self):
        current = {}  # no buildings built
        result = self.manager._pick_next_building(current)
        assert result is not None
        assert result[0] == "main"  # first in priority
        assert result[1] == 0

    def test_respects_priority_order(self):
        current = {"main": 5, "farm": 5, "barracks": 5, "wall": 5}
        result = self.manager._pick_next_building(current)
        assert result[0] == "main"  # highest priority


class TestBuildingManagerSequential:
    def setup_method(self):
        config = BuildingConfig(enabled=True, template="templates/early_game.toml")
        self.manager = BuildingManager(config, hq=None)
        self.manager.mode = "sequential"
        self.manager.build_steps = [
            BuildStep(building="main", level=3),
            BuildStep(building="wood", level=1),
            BuildStep(building="stone", level=1),
            BuildStep(building="iron", level=1),
            BuildStep(building="farm", level=2),
            BuildStep(building="main", level=5),
            BuildStep(building="barracks", level=1),
        ]

    def test_picks_first_incomplete_step(self):
        current = {"main": 1}
        result = self.manager._pick_next_building(current)
        assert result is not None
        assert result[0] == "main"
        assert result[1] == 1  # current level
        assert result[2] == 3  # step target

    def test_skips_completed_steps(self):
        current = {"main": 3, "wood": 1, "stone": 1}
        result = self.manager._pick_next_building(current)
        assert result is not None
        assert result[0] == "iron"
        assert result[1] == 0  # not built yet
        assert result[2] == 1

    def test_accounts_for_queued_buildings(self):
        # main is at 2, but 1 is queued -> effective 3, so step main->3 is done
        current = {"main": 2}
        result = self.manager._pick_next_building(current, queue_buildings=["main"])
        assert result is not None
        assert result[0] == "wood"  # main->3 is satisfied by 2+1 queued

    def test_all_steps_complete(self):
        current = {
            "main": 5, "wood": 1, "stone": 1, "iron": 1,
            "farm": 2, "barracks": 1,
        }
        result = self.manager._pick_next_building(current)
        assert result is None

    def test_same_building_multiple_levels(self):
        # main at 2 → should pick main->3, not skip to main->5
        current = {"main": 2, "wood": 1, "stone": 1, "iron": 1, "farm": 2}
        result = self.manager._pick_next_building(current)
        assert result is not None
        assert result[0] == "main"
        assert result[2] == 3  # targets level 3, not 5

    def test_queued_double_counts(self):
        # main at 1, 2 in queue -> effective 3 -> main->3 satisfied, next is wood
        current = {"main": 1}
        result = self.manager._pick_next_building(
            current, queue_buildings=["main", "main"]
        )
        assert result is not None
        assert result[0] == "wood"


class TestResourceWaitCalculation:
    def test_no_deficit(self):
        current = Resources(wood=500, stone=500, iron=500)
        cost = Resources(wood=100, stone=100, iron=100)
        production = Resources(wood=100, stone=100, iron=100)
        wait = BuildingManager._calculate_resource_wait(current, cost, production)
        assert wait == 0.0

    def test_single_resource_deficit(self):
        current = Resources(wood=0, stone=500, iron=500)
        cost = Resources(wood=100, stone=100, iron=100)
        production = Resources(wood=360, stone=360, iron=360)  # 360/hr = 0.1/s
        wait = BuildingManager._calculate_resource_wait(current, cost, production)
        # Need 100 wood at 0.1/s = 1000s
        assert abs(wait - 1000.0) < 0.1

    def test_multiple_deficit_takes_max(self):
        current = Resources(wood=0, stone=0, iron=500)
        cost = Resources(wood=100, stone=200, iron=100)
        production = Resources(wood=360, stone=360, iron=360)  # 0.1/s each
        wait = BuildingManager._calculate_resource_wait(current, cost, production)
        # Wood: 100/0.1 = 1000s, Stone: 200/0.1 = 2000s -> max is 2000
        assert abs(wait - 2000.0) < 0.1

    def test_zero_production_caps_at_3600(self):
        current = Resources(wood=0, stone=500, iron=500)
        cost = Resources(wood=100, stone=100, iron=100)
        production = Resources(wood=0, stone=360, iron=360)
        wait = BuildingManager._calculate_resource_wait(current, cost, production)
        assert wait == 3600.0

    def test_caps_at_3600_for_very_long_wait(self):
        current = Resources(wood=0, stone=0, iron=0)
        cost = Resources(wood=10000, stone=10000, iron=10000)
        production = Resources(wood=100, stone=100, iron=100)  # 100/hr
        wait = BuildingManager._calculate_resource_wait(current, cost, production)
        # Would be 360000s but capped at 3600
        assert wait == 3600.0
