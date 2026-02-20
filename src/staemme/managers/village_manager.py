"""Village manager - orchestrates all per-village automation tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from staemme.core.config import AppConfig, is_feature_enabled
from staemme.core.humanizer import Humanizer
from staemme.core.logging import get_logger
from staemme.game.api import GameAPI
from staemme.game.screens.barracks import BarracksScreen
from staemme.game.screens.farm_assistant import FarmAssistantScreen
from staemme.game.screens.headquarters import HeadquartersScreen
from staemme.game.screens.overview import OverviewScreen
from staemme.game.screens.rally_point import RallyPointScreen
from staemme.game.screens.report import ReportScreen
from staemme.game.screens.scavenge import ScavengeScreen
from staemme.game.screens.stable import StableScreen
from staemme.managers.building_manager import BuildingManager, BuildResult
from staemme.managers.defense_manager import DefenseManager
from staemme.managers.farm_manager import FarmManager
from staemme.managers.report_manager import ReportManager
from staemme.managers.scavenge_manager import ScavengeManager
from staemme.managers.troop_manager import TroopManager

log = get_logger("manager.village")


class VillageManager:
    """Orchestrates all automation managers for a single village."""

    def __init__(
        self,
        config: AppConfig,
        overview: OverviewScreen,
        hq: HeadquartersScreen,
        barracks: BarracksScreen,
        stable: StableScreen,
        rally: RallyPointScreen,
        farm_screen: FarmAssistantScreen,
        scavenge_screen: ScavengeScreen,
        report_screen: ReportScreen,
        api: GameAPI,
        humanizer: Humanizer,
        config_dir: Path,
        world_speed: float = 1.0,
        unit_carries: dict[str, int] | None = None,
        feature_resolver: Callable[[int, str], bool] | None = None,
    ) -> None:
        self.config = config
        self.overview = overview
        self.humanizer = humanizer
        self._feature_resolver = feature_resolver or (
            lambda vid, feat: is_feature_enabled(config, vid, feat)
        )

        lc_carry = (unit_carries or {}).get("light", 80)

        # Initialize sub-managers
        self.defense = DefenseManager(overview, rally)
        self.building = BuildingManager(config.building, hq)
        self.building.load_template(config_dir)
        self.troops = TroopManager(config.troops, barracks, stable, humanizer)
        self.farm = FarmManager(config.farming, farm_screen, lc_carry)
        self.scavenge = ScavengeManager(
            config.scavenging, scavenge_screen, world_speed, unit_carries
        )
        self.reports = ReportManager(report_screen, self.farm)

    def _is_enabled(self, village_id: int, feature: str) -> bool:
        """Check if a feature is enabled for a village (respects overrides)."""
        return self._feature_resolver(village_id, feature)

    def _any_feature_needs_overview(self, village_id: int) -> bool:
        """Check if any enabled feature requires the overview screen."""
        return (
            self._is_enabled(village_id, "building")
            or self._is_enabled(village_id, "farming")
            or self._is_enabled(village_id, "troops")
        )

    async def run_cycle(self, village_id: int) -> dict[str, Any]:
        """Run a complete automation cycle for one village.

        Order: refresh state -> check defense -> build -> train -> farm -> scavenge -> reports
        Returns a summary dict including village object and queue times.
        """
        result: dict[str, Any] = {}
        log.info("cycle_start", village=village_id)

        # Only navigate to overview if a feature actually needs it
        village = None
        if self._any_feature_needs_overview(village_id):
            village = await self.overview.get_village_state(village_id)
            result["village_name"] = village.name
            result["village"] = village

            # Check for incoming attacks (highest priority)
            under_attack = await self.defense.check(village, village_id)
            result["under_attack"] = under_attack

            if under_attack:
                log.warning("cycle_paused_attack", village=village_id)
                if self._is_enabled(village_id, "farming"):
                    result["reports_processed"] = await self.reports.run(village_id)
                return result

        # Build list of enabled managers only
        managers = []
        if self._is_enabled(village_id, "building") and village:
            managers.append(("building", self._run_building, village, village_id))
        if self._is_enabled(village_id, "troops"):
            managers.append(("troops", self._run_troops, village_id))
        if self._is_enabled(village_id, "farming"):
            managers.append(("farming", self._run_farming, village_id))
        if self._is_enabled(village_id, "scavenging"):
            managers.append(("scavenging", self._run_scavenge, village_id))

        managers = self.humanizer.shuffle_order(managers)

        for name, func, *args in managers:
            try:
                res = await func(*args)
                result[name] = res
                # Extract BuildResult fields for building manager
                if name == "building" and isinstance(res, BuildResult):
                    if res.queue_finish_ts > 0:
                        result["build_queue_finish"] = res.queue_finish_ts
                    if res.resource_wait > 0:
                        result["build_resource_wait"] = res.resource_wait
                        result["build_waiting_for"] = res.building_name
                # Navigate back to overview between tasks (human-like)
                await self.overview.browser.navigate_to_screen(
                    "overview", village_id
                )
                await self.humanizer.wait(f"after_{name}")
            except Exception as e:
                log.error("manager_error", manager=name, village=village_id, error=str(e))
                result[name] = False

        # Process reports (only if farming is enabled, since reports feed farm targets)
        if self._is_enabled(village_id, "farming"):
            try:
                result["reports_processed"] = await self.reports.run(village_id)
            except Exception as e:
                log.error("report_error", village=village_id, error=str(e))

        # Add scavenge wait time if available
        wait = self.scavenge.seconds_until_return()
        if wait > 0:
            result["scavenge_wait_seconds"] = round(wait)

        log.info("cycle_complete", village=village_id, result=result)
        return result

    async def _run_building(self, village, village_id: int) -> BuildResult:
        return await self.building.run(village, village_id)

    async def _run_troops(self, village_id: int):
        return await self.troops.run(village_id)

    async def _run_farming(self, village_id: int):
        return await self.farm.run(village_id)

    async def _run_scavenge(self, village_id: int):
        return await self.scavenge.run(village_id)
