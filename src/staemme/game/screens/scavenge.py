"""Scavenging screen - send and manage scavenge missions."""

from __future__ import annotations

import asyncio
from typing import Any

from staemme.core.browser_client import BrowserClient
from staemme.core.extractors import extract_scavenge_options, extract_troop_counts
from staemme.core.logging import get_logger

log = get_logger("screen.scavenge")


class ScavengeScreen:
    """Interact with the scavenging screen (place&mode=scavenge).

    The scavenge page has a SHARED troop input area (candidate-squad-widget)
    and separate Start buttons per option (.scavenge-option:nth-child(N)).
    Flow: fill shared inputs → click an option's Start button.
    After each send the page DOM updates via AJAX, so we must re-navigate
    before filling/sending the next option.
    """

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def navigate(self, village_id: int) -> str:
        """Navigate to the scavenge page, return HTML."""
        return await self.browser.navigate_to_screen(
            "place", village_id, extra_params={"mode": "scavenge"}
        )

    async def get_state(self, village_id: int) -> dict[str, Any]:
        """Get scavenge state: available tiers, running missions, idle troops."""
        html = await self.navigate(village_id)
        options = extract_scavenge_options(html)
        troops = extract_troop_counts(html)

        running: list[dict[str, Any]] = []
        for opt in options:
            if opt["running"]:
                running.append(opt)

        return {
            "options": options,
            "idle_troops": troops,
            "running": running,
        }

    async def _fill_shared_inputs(self, troops: dict[str, int]) -> bool:
        """Fill the shared candidate-squad-widget inputs via JS.

        page.fill() is incompatible with the game's input JS — values get cleared.
        Setting .value directly + dispatching input/change events works reliably.
        """
        filled = False
        for unit, count in troops.items():
            if count <= 0:
                continue
            result = await self.browser.page.evaluate(f"""
                (() => {{
                    const inp = document.querySelector("input.unitsInput[name='{unit}']");
                    if (!inp) return false;
                    inp.value = '{count}';
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }})()
            """)
            if result:
                filled = True
            else:
                log.debug("fill_input_not_found", unit=unit)
        return filled

    async def _clear_shared_inputs(self) -> None:
        """Clear all troop inputs to prepare for next option."""
        await self.browser.page.evaluate("""
            document.querySelectorAll('input.unitsInput').forEach(inp => {
                inp.value = '';
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
            })
        """)

    def _option_selector(self, tier: int) -> str:
        """CSS selector for the nth scavenge option (1-based tier)."""
        return f".scavenge-option:nth-child({tier})"

    async def send_scavenge(
        self,
        village_id: int,
        tier: int,
        troops: dict[str, int],
    ) -> bool:
        """Send troops on a scavenging mission.

        Navigates to the scavenge page (ensures clean DOM), fills inputs, clicks Start.
        """
        await self.navigate(village_id)

        await self._clear_shared_inputs()
        filled = await self._fill_shared_inputs(troops)
        if not filled:
            log.warning("scavenge_fill_failed", village=village_id, tier=tier)
            return False

        # Short pause for the game JS to process input events
        await asyncio.sleep(0.5)

        # Click the send button for this tier's option
        option_sel = self._option_selector(tier)
        send_sel = f"{option_sel} a.free_send_button"
        try:
            await self.browser.click_element(send_sel, timeout=3000)
        except Exception:
            log.warning("scavenge_send_failed", village=village_id, tier=tier)
            return False

        # Wait for AJAX response to complete
        await asyncio.sleep(1.5)

        log.info("scavenge_sent", village=village_id, tier=tier, troops=troops)
        return True

    async def get_return_times(self, village_id: int) -> dict[int, int]:
        """Extract return timestamps for running scavenge missions from JS.

        Returns {tier: unix_timestamp} for each running option.
        """
        await self.navigate(village_id)
        raw = await self.browser.page.evaluate("""
            (() => {
                const result = {};
                if (typeof ScavengeScreen === 'undefined') return result;
                const options = ScavengeScreen.village?.options;
                if (!options) return result;
                for (const [id, opt] of Object.entries(options)) {
                    if (opt.scavenging_squad && opt.scavenging_squad.return_time) {
                        result[id] = opt.scavenging_squad.return_time;
                    }
                }
                return result;
            })()
        """)
        # JS object keys are always strings — convert to int
        return {int(k): v for k, v in raw.items()}

    async def fill_all_options(
        self,
        village_id: int,
        allocations: dict[int, dict[str, int]],
    ) -> bool:
        """Fill troop inputs for the first allocated option (dry-run preview).

        Since inputs are shared, we can only show one option's values at a time.
        Fills the lowest-tier allocation so the user can see it in-browser.
        """
        await self.navigate(village_id)

        if not allocations:
            return False

        first_tier = min(allocations)
        troops = allocations[first_tier]

        await self._clear_shared_inputs()
        filled = await self._fill_shared_inputs(troops)

        if filled:
            log.info(
                "scavenge_filled_preview",
                village=village_id,
                tier=first_tier,
                troops=troops,
            )

        return filled

    @staticmethod
    def calculate_duration(troops: dict[str, int], tier: int) -> int:
        """Estimate scavenge duration in seconds based on troop count and tier."""
        total_troops = sum(troops.values())
        tier_factors = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25}
        factor = tier_factors.get(tier, 1.0)
        return int(total_troops * 10 * factor)
