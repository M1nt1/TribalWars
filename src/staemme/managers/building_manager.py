"""Auto-building manager with template-based upgrade ordering."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from staemme.core.config import BuildingConfig
from staemme.core.exceptions import BuildQueueFullError
from staemme.core.logging import get_logger
from staemme.game.screens.headquarters import HeadquartersScreen
from staemme.models.buildings import BuildStep
from staemme.models.village import Resources, Village

log = get_logger("manager.building")


@dataclass
class BuildResult:
    """Result of a building cycle."""

    ordered: bool = False
    building_name: str = ""
    queue_finish_ts: float = 0  # unix ts of last queue item
    resource_wait: float = 0  # seconds until next build affordable


class BuildingManager:
    """Manages automatic building upgrades based on templates."""

    def __init__(self, config: BuildingConfig, hq: HeadquartersScreen) -> None:
        self.config = config
        self.hq = hq
        self.target_levels: dict[str, int] = {}
        self.priority_order: list[str] = []
        self.mode: str = "priority"
        self.build_steps: list[BuildStep] = []
        self._last_levels: dict[str, int] = {}

    def load_template(self, config_dir: Path) -> None:
        """Load building template from TOML file."""
        template_path = config_dir / self.config.template
        if not template_path.exists():
            log.warning("template_not_found", path=str(template_path))
            return

        with open(template_path, "rb") as f:
            data = tomllib.load(f)

        self.mode = data.get("mode", "priority")

        if self.mode == "sequential":
            self.build_steps = [
                BuildStep(**step) for step in data.get("steps", [])
            ]
            log.info(
                "template_loaded",
                path=str(template_path),
                mode="sequential",
                steps=len(self.build_steps),
            )
        else:
            self.target_levels = data.get("buildings", {})
            priority = data.get("priority", {})
            self.priority_order = priority.get("order", list(self.target_levels.keys()))
            log.info(
                "template_loaded",
                path=str(template_path),
                mode="priority",
                buildings=len(self.target_levels),
            )

    async def run(self, village: Village, village_id: int) -> BuildResult:
        """Execute one building cycle. Returns BuildResult with details."""
        result = BuildResult()

        if not self.config.enabled:
            return result

        if not self.target_levels and not self.build_steps:
            log.debug("no_template_loaded", village=village_id)
            return result

        # Get consolidated HQ state (single navigation)
        state = await self.hq.get_hq_state(village_id)
        self._last_levels = dict(state.get("levels", {}))

        # Detect max queue size (2 with premium, 1 without)
        max_queue = 2 if state.get("premium", False) else 2  # fallback to 2

        # Log state for debugging
        log.info(
            "build_state",
            village=village_id,
            mode=self.mode,
            levels_count=len(state.get("levels", {})),
            queue_size=len(state.get("queue", [])),
            available_count=len(state.get("available", {})),
            premium=state.get("premium", False),
        )

        # Multi-queue loop: try to fill all queue slots
        for _attempt in range(max_queue):
            queue = state.get("queue", [])

            # Record queue finish time — use max endtime across all entries
            for entry in queue:
                if entry.finish_time:
                    ts = entry.finish_time.timestamp()
                    if ts > result.queue_finish_ts:
                        result.queue_finish_ts = ts

            if len(queue) >= max_queue:
                log.info("build_queue_full", village=village_id, queue_size=len(queue))
                break

            # Pick next building based on mode
            queue_buildings = [q.building for q in queue]
            next_building = self._pick_next_building(
                state["levels"], queue_buildings
            )
            if not next_building:
                log.info(
                    "all_buildings_at_target",
                    village=village_id,
                    levels={k: v for k, v in state["levels"].items()
                            if k in ("storage", "stone", "wood", "iron")},
                    steps=len(self.build_steps),
                )
                break

            building_name, current_level, target_level = next_building

            # Check affordability if we have cost data
            available = state.get("available", {})
            if building_name in available:
                building_info = available[building_name]
                cost = building_info["cost"]
                if not village.resources.can_afford(cost):
                    wait = self._calculate_resource_wait(
                        village.resources, cost, village.production
                    )
                    result.resource_wait = wait
                    result.building_name = building_name
                    log.info(
                        "insufficient_resources",
                        village=village_id,
                        building=building_name,
                        cost=cost.model_dump(),
                        wait_seconds=round(wait),
                    )
                    break
            elif available:
                # We parsed buildings but this one isn't listed
                log.info(
                    "building_not_available",
                    village=village_id,
                    building=building_name,
                )
                break
            # If available is empty, skip cost check and try to click directly

            # Order the upgrade
            try:
                success = await self.hq.upgrade_building(village_id, building_name)
                if success:
                    result.ordered = True
                    result.building_name = building_name
                    log.info(
                        "building_upgrade_ordered",
                        village=village_id,
                        building=building_name,
                        from_level=current_level,
                        to_level=current_level + 1,
                        target=target_level,
                    )
                    # Refresh state for next iteration (page reloaded after upgrade)
                    state = await self.hq.get_hq_state(village_id)
                else:
                    break
            except BuildQueueFullError:
                log.debug("queue_full_during_order", village=village_id)
                break

        # Final queue finish time — max across all entries
        for entry in state.get("queue", []):
            if entry.finish_time:
                ts = entry.finish_time.timestamp()
                if ts > result.queue_finish_ts:
                    result.queue_finish_ts = ts

        return result

    def _pick_next_building(
        self,
        current_levels: dict[str, int],
        queue_buildings: list[str] | None = None,
    ) -> tuple[str, int, int] | None:
        """Pick the next building to upgrade.

        Dispatches to priority or sequential mode.
        Returns (building_name, current_level, target_level) or None.
        """
        if self.mode == "sequential":
            return self._pick_next_building_sequential(
                current_levels, queue_buildings or []
            )
        return self._pick_next_building_priority(current_levels)

    def _pick_next_building_priority(
        self, current_levels: dict[str, int]
    ) -> tuple[str, int, int] | None:
        """Pick the highest-priority building that's below target level."""
        for building_name in self.priority_order:
            if building_name not in self.target_levels:
                continue
            target = self.target_levels[building_name]
            current = current_levels.get(building_name, 0)
            if current < target:
                return (building_name, current, target)
        return None

    def _pick_next_building_sequential(
        self,
        current_levels: dict[str, int],
        queue_buildings: list[str],
    ) -> tuple[str, int, int] | None:
        """Walk steps in order, find first where building is below step level.

        Accounts for buildings already queued (not yet reflected in current_levels).
        """
        # Count how many times each building appears in the queue
        queued_counts: dict[str, int] = {}
        for b in queue_buildings:
            queued_counts[b] = queued_counts.get(b, 0) + 1

        for step in self.build_steps:
            current = current_levels.get(step.building, 0)
            queued = queued_counts.get(step.building, 0)
            effective_level = current + queued
            if effective_level < step.level:
                return (step.building, current, step.level)

        return None

    @staticmethod
    def _calculate_resource_wait(
        current: Resources, cost: Resources, production: Resources
    ) -> float:
        """Calculate seconds until resources are sufficient.

        Production rates are per-hour. Returns max wait across all resource types.
        Caps at 3600s if production rate is 0 for a needed resource.
        """
        max_wait = 0.0
        for res_type in ("wood", "stone", "iron"):
            have = getattr(current, res_type)
            need = getattr(cost, res_type)
            deficit = need - have
            if deficit <= 0:
                continue
            rate = getattr(production, res_type)  # per hour
            if rate <= 0:
                return 3600.0  # cap at 1 hour if no production
            wait = deficit / (rate / 3600)  # rate/3600 = per second
            if wait > max_wait:
                max_wait = wait
        return min(max_wait, 3600.0)
