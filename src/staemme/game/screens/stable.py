"""Stable screen - cavalry training."""

from __future__ import annotations

from staemme.core.browser_client import BrowserClient
from staemme.core.extractors import extract_troop_counts
from staemme.core.logging import get_logger
from staemme.models.troops import STABLE_UNITS, TroopCounts

log = get_logger("screen.stable")


class StableScreen:
    """Interact with the Stable screen for cavalry training."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def get_available_troops(self, village_id: int) -> TroopCounts:
        """Get current cavalry troop counts."""
        html = await self.browser.navigate_to_screen("stable", village_id)
        # If stable isn't built, page redirects elsewhere
        if "stable" not in (self.browser.page.url or ""):
            log.debug("stable_not_available_for_troops", village=village_id)
            return TroopCounts()
        return extract_troop_counts(html)

    async def train_units(self, village_id: int, units: dict[str, int]) -> bool:
        """Submit a cavalry training order by filling inputs and clicking train."""
        if not units:
            return False

        html = await self.browser.navigate_to_screen("stable", village_id)

        # Check if stable screen actually loaded (building might not exist)
        if "stable" not in (self.browser.page.url or ""):
            log.warning("stable_not_available", village=village_id)
            return False

        filled_any = False
        for unit, count in units.items():
            if count > 0:
                selector = f"input[name='{unit}']"
                if await self.browser.element_exists(selector):
                    await self.browser.fill_input(selector, str(count))
                    filled_any = True
                else:
                    log.debug("unit_input_not_found", unit=unit, village=village_id)

        if not filled_any:
            return False

        submit = "input.btn-train, .btn-recruit, input[type='submit']"
        if await self.browser.element_exists(submit):
            await self.browser.click_element(submit)
            log.info("cavalry_training", village=village_id, units=units)
            return True

        return False
