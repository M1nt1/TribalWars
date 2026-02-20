"""Scavenging automation manager."""

from __future__ import annotations

import time

from staemme.core.config import ScavengingConfig
from staemme.core.logging import get_logger
from staemme.core.scavenge_formulas import (
    SCAVENGE_UNITS,
    allocate_by_ratio,
    calculate_carry_capacity,
    calculate_duration,
    calculate_loot,
    calculate_rph,
    equal_runtime_weights,
)
from staemme.game.screens.scavenge import ScavengeScreen

log = get_logger("manager.scavenge")


class ScavengeManager:
    """Manages scavenging missions with configurable modes."""

    def __init__(
        self,
        config: ScavengingConfig,
        scavenge_screen: ScavengeScreen,
        world_speed: float = 1.0,
        unit_carries: dict[str, int] | None = None,
    ) -> None:
        self.config = config
        self.screen = scavenge_screen
        self.world_speed = world_speed
        self.unit_carries = unit_carries or {}
        # Unix timestamp when the last running mission completes
        self.next_return: float = 0

    def _filter_troops(self, idle_troops: dict[str, int]) -> dict[str, int]:
        """Apply exclusions and reserves to idle troops."""
        available = {}
        for u in SCAVENGE_UNITS:
            if u in self.config.scavenge_exclude:
                continue
            count = idle_troops.get(u, 0) if isinstance(idle_troops, dict) else idle_troops.get(u)
            reserve = self.config.scavenge_reserve.get(u, 0)
            usable = count - reserve
            if usable > 0:
                available[u] = usable
        return available

    def seconds_until_return(self) -> float:
        """Seconds until all running missions complete (0 if none)."""
        if self.next_return <= 0:
            return 0
        remaining = self.next_return - time.time()
        return max(0, remaining)

    async def run(self, village_id: int) -> int:
        """Execute one scavenging cycle. Returns number of missions sent."""
        if not self.config.enabled:
            return 0

        if self.config.mode == "ratio":
            return await self._run_ratio(village_id)

        return await self._run_legacy(village_id)

    async def _run_ratio(self, village_id: int) -> int:
        """Ratio-based scavenging with real game formulas."""
        # Human-like: go to rally point first, then scavenge tab
        await self.screen.browser.navigate_to_screen("place", village_id)
        state = await self.screen.get_state(village_id)
        options = state["options"]
        idle_troops = state["idle_troops"]

        # Auto-detect all unlocked tiers
        unlocked_tiers = {opt["tier"] for opt in options if not opt["locked"]}
        running_tiers = {opt["tier"] for opt in options if opt["running"]}

        if not unlocked_tiers:
            log.debug("no_unlocked_scavenge_tiers", village=village_id)
            return 0

        # If ANY unlocked tier is still running, check how long
        if running_tiers & unlocked_tiers:
            await self._update_return_times(village_id, unlocked_tiers)
            wait = self.seconds_until_return()
            running = sorted(running_tiers & unlocked_tiers)

            if wait <= 90:
                # Almost done — wait it out and re-read state so we can send immediately
                log.info("scavenge_wait_brief", village=village_id, running=running, wait_sec=round(wait))
                import asyncio
                await asyncio.sleep(wait + 5)
                # Re-fetch state after waiting
                state = await self.screen.get_state(village_id)
                options = state["options"]
                idle_troops = state["idle_troops"]
                running_tiers = {opt["tier"] for opt in options if opt["running"]}
                # If still running somehow, bail
                if running_tiers & unlocked_tiers:
                    log.info("scavenge_still_running_after_wait", village=village_id, running=sorted(running_tiers))
                    return 0
            else:
                log.info("scavenge_waiting", village=village_id, running=running, wait_min=round(wait / 60, 1))
                return 0

        if idle_troops.total() == 0:
            log.debug("no_idle_troops_for_scavenge", village=village_id)
            return 0

        # Compute weights for equal runtime from game loot ratios
        active_ratios = equal_runtime_weights(unlocked_tiers)

        log.info("scavenge_tiers_detected", village=village_id, tiers=sorted(unlocked_tiers), weights=active_ratios)

        # Get scavengeable troops (filtered by exclusions + reserves)
        available = self._filter_troops(
            {u: idle_troops.get(u) for u in SCAVENGE_UNITS}
        )

        if not available:
            log.debug("no_scavengeable_troops", village=village_id)
            return 0

        # Allocate troops across tiers by ratio (carry-capacity-based)
        allocations = allocate_by_ratio(available, active_ratios, self.unit_carries)

        if not allocations:
            log.debug("allocation_empty", village=village_id)
            return 0

        # Log expected stats for each tier
        for tier, troops in sorted(allocations.items()):
            cap = calculate_carry_capacity(troops, self.unit_carries)
            duration = calculate_duration(cap, tier, self.world_speed)
            loot = calculate_loot(cap, tier)
            rph = calculate_rph(cap, tier, self.world_speed)
            log.info(
                "scavenge_plan",
                village=village_id,
                tier=tier,
                troops=troops,
                carry_cap=cap,
                duration_min=round(duration / 60, 1),
                expected_loot=round(loot),
                rph=round(rph, 1),
            )

        if self.config.dry_run:
            # Fill forms only, don't click start
            await self.screen.fill_all_options(village_id, allocations)
            log.info("scavenge_dry_run_complete", village=village_id, tiers=list(allocations))
            return len(allocations)

        # Actually send each tier (highest first)
        sent = 0
        for tier, troops in sorted(allocations.items(), reverse=True):
            success = await self.screen.send_scavenge(village_id, tier, troops)
            if success:
                sent += 1

        # Fetch actual return times from the game to know when to run next
        if sent > 0:
            await self._update_return_times(village_id, set(active_ratios.keys()))

        log.info("scavenge_cycle_complete", village=village_id, missions_sent=sent)
        return sent

    async def _update_return_times(
        self, village_id: int, unlocked_tiers: set[int] | None = None
    ) -> None:
        """Fetch return timestamps from the game and set next_return to the latest."""
        try:
            return_times = await self.screen.get_return_times(village_id)
            if return_times:
                # Wait for the LONGEST running mission among unlocked tiers
                relevant = [
                    ts for tier, ts in return_times.items()
                    if unlocked_tiers is None or tier in unlocked_tiers
                ]
                if relevant:
                    self.next_return = max(relevant)
                    wait = self.seconds_until_return()
                    log.info(
                        "scavenge_next_return",
                        village=village_id,
                        wait_min=round(wait / 60, 1),
                        return_times=return_times,
                    )
        except Exception as e:
            log.debug("return_time_fetch_failed", error=str(e))

    async def _run_legacy(self, village_id: int) -> int:
        """Legacy modes: send_all, time_based, max_efficiency."""
        # Human-like: go to rally point first, then scavenge tab
        await self.screen.browser.navigate_to_screen("place", village_id)
        state = await self.screen.get_state(village_id)
        options = state["options"]
        idle_troops = state["idle_troops"]

        if idle_troops.total() == 0:
            log.debug("no_idle_troops_for_scavenge", village=village_id)
            return 0

        available_tiers = [
            opt for opt in options
            if not opt["locked"] and not opt["running"]
        ]

        if not available_tiers:
            log.debug("no_available_scavenge_tiers", village=village_id)
            return 0

        sent = 0
        remaining_troops = dict(idle_troops.counts)

        for opt in sorted(available_tiers, key=lambda o: o["tier"], reverse=True):
            tier = opt["tier"]
            allocation = self._allocate_troops(remaining_troops, tier, len(available_tiers) - sent)

            if not allocation or sum(allocation.values()) == 0:
                continue

            success = await self.screen.send_scavenge(village_id, tier, allocation)
            if success:
                sent += 1
                for unit, count in allocation.items():
                    remaining_troops[unit] = max(0, remaining_troops.get(unit, 0) - count)

        log.info("scavenge_cycle_complete", village=village_id, missions_sent=sent)
        return sent

    def _allocate_troops(
        self,
        available: dict[str, int],
        tier: int,
        remaining_tiers: int,
    ) -> dict[str, int]:
        """Allocate troops for a scavenge tier based on legacy mode."""
        scavenge_available = self._filter_troops(available)

        if not scavenge_available:
            return {}

        if self.config.mode == "send_all":
            return self._allocate_send_all(scavenge_available, remaining_tiers)
        elif self.config.mode == "time_based":
            return self._allocate_time_based(scavenge_available, tier, remaining_tiers)
        else:  # max_efficiency
            return self._allocate_max_efficiency(scavenge_available, tier, remaining_tiers)

    def _allocate_send_all(
        self, available: dict[str, int], remaining_tiers: int
    ) -> dict[str, int]:
        if remaining_tiers <= 1:
            return dict(available)
        allocation: dict[str, int] = {}
        for unit, count in available.items():
            allocation[unit] = count // remaining_tiers
        return {u: c for u, c in allocation.items() if c > 0}

    def _allocate_time_based(
        self,
        available: dict[str, int],
        tier: int,
        remaining_tiers: int,
    ) -> dict[str, int]:
        target_seconds = self.config.target_minutes * 60
        allocation = self._allocate_send_all(available, remaining_tiers)
        estimated = ScavengeScreen.calculate_duration(allocation, tier)
        if estimated > 0:
            ratio = target_seconds / estimated
            allocation = {
                u: max(1, int(c * ratio))
                for u, c in allocation.items()
            }
            allocation = {
                u: min(c, available.get(u, 0))
                for u, c in allocation.items()
            }
        return {u: c for u, c in allocation.items() if c > 0}

    def _allocate_max_efficiency(
        self,
        available: dict[str, int],
        tier: int,
        remaining_tiers: int,
    ) -> dict[str, int]:
        tier_weights = {1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4}
        weight = tier_weights.get(tier, 0.25)
        allocation: dict[str, int] = {}
        for unit, count in available.items():
            allocation[unit] = max(1, int(count * weight))
        return {u: c for u, c in allocation.items() if c > 0}
