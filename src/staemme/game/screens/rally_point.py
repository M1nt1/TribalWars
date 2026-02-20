"""Rally Point screen - send attacks, view troops."""

from __future__ import annotations

from staemme.core.browser_client import BrowserClient
from staemme.core.extractors import extract_incoming_attacks, extract_troop_counts
from staemme.core.logging import get_logger
from staemme.models.troops import TroopCounts

log = get_logger("screen.rally")


class RallyPointScreen:
    """Interact with the Rally Point (place) screen."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def get_troops_home(self, village_id: int) -> TroopCounts:
        """Get troops currently in the village."""
        html = await self.browser.navigate_to_screen("place", village_id)
        return extract_troop_counts(html)

    async def get_incoming_attacks(self, village_id: int) -> int:
        """Get number of incoming attacks."""
        html = await self.browser.navigate_to_screen("place", village_id)
        return extract_incoming_attacks(html)

    async def send_attack(
        self, village_id: int, target_x: int, target_y: int, troops: dict[str, int]
    ) -> bool:
        """Send an attack to a target coordinate.

        Two-step process:
        1. Fill target coords + troop counts, click attack
        2. Click confirm on the confirmation page
        """
        await self.browser.navigate_to_screen("place", village_id)

        # Step 1: Fill the attack form
        await self.browser.fill_input("input[name='x']", str(target_x))
        await self.browser.fill_input("input[name='y']", str(target_y))

        for unit, count in troops.items():
            if count > 0:
                await self.browser.fill_input(f"input[name='{unit}']", str(count))

        # Click the attack button
        await self.browser.click_element("#target_attack, input[name='attack']")
        await self.browser.page.wait_for_load_state("domcontentloaded")

        # Step 2: Click confirm on the confirmation page
        confirm_exists = await self.browser.element_exists(
            "#troop_confirm_go, input[name='submit']"
        )
        if not confirm_exists:
            log.warning(
                "attack_no_confirm", village=village_id, target=f"{target_x}|{target_y}"
            )
            return False

        await self.browser.click_element("#troop_confirm_go, input[name='submit']")
        await self.browser.page.wait_for_load_state("domcontentloaded")

        log.info(
            "attack_sent",
            village=village_id,
            target=f"{target_x}|{target_y}",
            troops=troops,
        )
        return True

    async def send_support(
        self, village_id: int, target_x: int, target_y: int, troops: dict[str, int]
    ) -> bool:
        """Send support troops to a target."""
        await self.browser.navigate_to_screen("place", village_id)

        await self.browser.fill_input("input[name='x']", str(target_x))
        await self.browser.fill_input("input[name='y']", str(target_y))

        for unit, count in troops.items():
            if count > 0:
                await self.browser.fill_input(f"input[name='{unit}']", str(count))

        await self.browser.click_element("#target_support, input[name='support']")
        await self.browser.page.wait_for_load_state("domcontentloaded")

        confirm_exists = await self.browser.element_exists(
            "#troop_confirm_go, input[name='submit']"
        )
        if confirm_exists:
            await self.browser.click_element("#troop_confirm_go, input[name='submit']")
            await self.browser.page.wait_for_load_state("domcontentloaded")

        log.info("support_sent", village=village_id, target=f"{target_x}|{target_y}")
        return True
