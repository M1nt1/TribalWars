"""Auto-recruitment manager - train troops to meet target counts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from staemme.core.config import TroopsConfig
from staemme.core.logging import get_logger
from staemme.game.screens.barracks import BarracksScreen
from staemme.game.screens.stable import StableScreen
from staemme.models.troops import BARRACKS_UNITS, STABLE_UNITS, TroopCounts

if TYPE_CHECKING:
    from staemme.core.humanizer import Humanizer

log = get_logger("manager.troops")


class TroopManager:
    """Manages automatic troop recruitment to meet configured targets."""

    def __init__(
        self,
        config: TroopsConfig,
        barracks: BarracksScreen,
        stable: StableScreen,
        humanizer: "Humanizer | None" = None,
    ) -> None:
        self.config = config
        self.barracks = barracks
        self.stable = stable
        self.humanizer = humanizer

    async def run(self, village_id: int) -> bool:
        """Execute one recruitment cycle. Returns True if any troops were queued."""
        if not self.config.enabled:
            return False
        if self.config.mode != "targets" or not self.config.targets:
            return False

        trained_any = False

        # Train barracks units
        barracks_needs = await self._get_barracks_needs(village_id)
        if barracks_needs:
            success = await self.barracks.train_units(village_id, barracks_needs)
            if success:
                trained_any = True

        # Train stable units
        stable_needs = await self._get_stable_needs(village_id)
        if stable_needs:
            success = await self.stable.train_units(village_id, stable_needs)
            if success:
                trained_any = True

        return trained_any

    async def _get_barracks_needs(self, village_id: int) -> dict[str, int]:
        """Calculate how many barracks units need to be trained."""
        current = await self.barracks.get_available_troops(village_id)
        queue = await self.barracks.get_train_queue(village_id)

        # Count units in queue
        queued: dict[str, int] = {}
        for entry in queue:
            queued[entry.unit] = queued.get(entry.unit, 0) + entry.count

        needs: dict[str, int] = {}
        for unit in BARRACKS_UNITS:
            unit_name = unit.value
            target = self.config.targets.get(unit_name, 0)
            if target <= 0:
                continue

            owned = current.get(unit_name) + queued.get(unit_name, 0)
            deficit = target - owned
            if deficit > 0:
                # Train in batches (don't queue too many at once)
                batch = min(deficit, 50)
                needs[unit_name] = batch

        if needs:
            log.debug("barracks_needs", village=village_id, needs=needs)
        return needs

    async def _get_stable_needs(self, village_id: int) -> dict[str, int]:
        """Calculate how many stable units need to be trained."""
        current = await self.stable.get_available_troops(village_id)

        needs: dict[str, int] = {}
        for unit in STABLE_UNITS:
            unit_name = unit.value
            target = self.config.targets.get(unit_name, 0)
            if target <= 0:
                continue

            owned = current.get(unit_name)
            deficit = target - owned
            if deficit > 0:
                batch = min(deficit, 25)
                needs[unit_name] = batch

        if needs:
            log.debug("stable_needs", village=village_id, needs=needs)
        return needs

    # ------------------------------------------------------------------
    # Fill-scavenge mode: train troops during scavenge wait
    # ------------------------------------------------------------------

    async def run_fill_scavenge(
        self,
        village_id: int,
        get_scavenge_remaining: Callable[[], float],
        panel_log: Callable[[str, str], object] | None = None,
        should_stop: Callable[[], bool] | None = None,
        timer_callback: Callable[[str, str, float], object] | None = None,
    ) -> None:
        """Queue troops to fill the remaining scavenge wait time in one shot.

        Calculates how many troops are needed so the training queue ends
        shortly after scavenging returns, queues them, and returns immediately.
        """
        units = self.config.fill_units
        if not units:
            log.debug("fill_scavenge_no_units_configured")
            return

        unit = units[0]
        remaining = get_scavenge_remaining()
        if remaining <= 30:
            return

        info = await self.barracks.get_training_info(village_id, unit)

        if not info["barracks_available"]:
            log.warning("fill_scavenge_no_barracks", village=village_id)
            if panel_log:
                await panel_log("No barracks available", "warn")
            return

        queue_seconds = info["queue_seconds"]

        # Queue already extends past scavenge return — nothing to do
        if queue_seconds >= remaining - 30:
            log.info("fill_scavenge_queue_sufficient", queue_secs=queue_seconds, remaining=round(remaining))
            return

        train_time = info["train_time"]
        max_affordable = info["max_affordable"]

        if train_time <= 0:
            log.warning("fill_scavenge_no_train_time", unit=unit)
            return

        if max_affordable <= 0:
            log.info("fill_scavenge_no_resources", unit=unit)
            if panel_log:
                await panel_log(f"No resources for {unit}", "warn")
            return

        # How many seconds of training to add so queue ends shortly after scavenge
        gap = remaining - queue_seconds
        batch = max(1, int(gap / train_time) + 1)
        batch = min(batch, max_affordable)

        log.info(
            "fill_scavenge_training",
            village=village_id,
            unit=unit,
            batch=batch,
            train_time=train_time,
            max_affordable=max_affordable,
            queue_duration=queue_seconds + batch * train_time,
        )

        success = await self.barracks.train_units(village_id, {unit: batch})
        if not success:
            log.warning("fill_scavenge_train_failed", unit=unit, batch=batch)
            if panel_log:
                await panel_log(f"Training failed for {unit}", "warn")
            return

        total_queue = queue_seconds + batch * train_time
        if panel_log:
            await panel_log(f"Queued {batch} {unit} ({round(total_queue / 60, 1)}min)")

        if timer_callback:
            import time as _time
            await timer_callback("troop_queue", "Troop Queue", _time.time() + total_queue)

        log.info("fill_scavenge_done", village=village_id, total_queue_min=round(total_queue / 60, 1))
