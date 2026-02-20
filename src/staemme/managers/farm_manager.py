"""Farming automation manager - uses Farm Assistant with Template C/A logic."""

from __future__ import annotations

from staemme.core.config import FarmingConfig
from staemme.core.logging import get_logger
from staemme.game.screens.farm_assistant import FarmAssistantScreen
from staemme.models.farm_target import FarmTarget

log = get_logger("manager.farm")


class FarmManager:
    """Manages farm automation using the Farm Assistant (am_farm) screen."""

    def __init__(
        self,
        config: FarmingConfig,
        farm_screen: FarmAssistantScreen,
        lc_carry: int = 80,
    ) -> None:
        self.config = config
        self.farm_screen = farm_screen
        self.lc_carry = lc_carry
        self.targets: dict[int, FarmTarget] = {}

    async def run(self, village_id: int) -> int:
        """Execute one farming cycle. Returns number of attacks sent."""
        if not self.config.enabled:
            return 0

        sent = await self.farm_screen.run_farm_cycle(
            village_id,
            lc_threshold=self.config.lc_threshold,
            lc_carry=self.lc_carry,
        )
        log.info("farm_run_complete", village=village_id, attacks=sent)
        return sent

    def blacklist_target(self, target_id: int) -> None:
        """Blacklist a target (has troops, high wall, etc.)."""
        if target_id in self.targets:
            self.targets[target_id].blacklisted = True
            log.info("target_blacklisted", target=target_id)

    def update_target_intel(
        self,
        target_id: int,
        wall_level: int | None = None,
        has_troops: bool | None = None,
        loot: dict | None = None,
    ) -> None:
        """Update farm target with intelligence from reports."""
        if target_id not in self.targets:
            return
        target = self.targets[target_id]
        if wall_level is not None:
            target.wall_level = wall_level
            if wall_level > 5:
                self.blacklist_target(target_id)
        if has_troops is not None:
            target.has_troops = has_troops
            if has_troops:
                self.blacklist_target(target_id)
        if loot:
            from staemme.models.village import Resources
            target.last_loot = Resources(**loot)
