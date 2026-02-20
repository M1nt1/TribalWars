"""Village overview screen interaction."""

from __future__ import annotations

from typing import Any

from staemme.core.browser_client import BrowserClient
from staemme.core.extractors import (
    extract_game_data,
    extract_incoming_attacks,
    extract_resources,
    extract_village_list,
)
from staemme.core.logging import get_logger
from staemme.models.village import Resources, Village

log = get_logger("screen.overview")


class OverviewScreen:
    """Reads village overview data."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def get_village_state(self, village_id: int) -> Village:
        """Fetch full village state from the overview screen."""
        html = await self.browser.navigate_to_screen("overview", village_id)
        game_data = extract_game_data(html)
        vd = game_data.get("village", {})

        resources = extract_resources(html)
        incoming = extract_incoming_attacks(html)

        # Extract production rates from game_data JS object via browser
        production = await self._extract_production_rates()

        return Village(
            id=int(vd.get("id", village_id)),
            name=vd.get("name", ""),
            x=int(vd.get("x", 0)),
            y=int(vd.get("y", 0)),
            points=int(vd.get("points", 0)),
            resources=resources,
            storage=int(vd.get("storage_max", 0)),
            population=int(vd.get("pop", 0)),
            max_population=int(vd.get("pop_max", 0)),
            production=production,
            incoming_attacks=incoming,
        )

    async def _extract_production_rates(self) -> Resources:
        """Extract per-hour production rates from the game's JS data.

        Tries multiple sources: game_data.village fields, Accountmanager,
        and the production overview tooltip.
        """
        try:
            rates = await self.browser.page.evaluate("""
                (() => {
                    try {
                        // Try game_data.village production fields
                        if (typeof game_data !== 'undefined' && game_data.village) {
                            var v = game_data.village;
                            var w = parseInt(v.wood_prod || v.wood_float || 0);
                            var s = parseInt(v.stone_prod || v.stone_float || 0);
                            var i = parseInt(v.iron_prod || v.iron_float || 0);
                            if (w > 0 || s > 0 || i > 0) return {wood: w, stone: s, iron: i};
                        }
                        // Try Accountmanager production data
                        if (typeof Accountmanager !== 'undefined' && Accountmanager.farm) {
                            var f = Accountmanager.farm;
                            return {
                                wood: parseInt(f.wood) || 0,
                                stone: parseInt(f.stone) || 0,
                                iron: parseInt(f.iron) || 0,
                            };
                        }
                        // Try production elements in the DOM
                        var wp = document.querySelector('#wood_prod, .res_wood .production');
                        var sp = document.querySelector('#stone_prod, .res_stone .production');
                        var ip = document.querySelector('#iron_prod, .res_iron .production');
                        if (wp) {
                            return {
                                wood: parseInt(wp.textContent) || 0,
                                stone: sp ? parseInt(sp.textContent) || 0 : 0,
                                iron: ip ? parseInt(ip.textContent) || 0 : 0,
                            };
                        }
                    } catch(e) {}
                    return {wood: 0, stone: 0, iron: 0};
                })()
            """)
            return Resources(
                wood=rates.get("wood", 0),
                stone=rates.get("stone", 0),
                iron=rates.get("iron", 0),
            )
        except Exception:
            return Resources()

    async def get_village_ids(self, village_id: int) -> list[int]:
        """Get list of all owned village IDs."""
        html = await self.browser.navigate_to_screen("overview", village_id)
        villages = extract_village_list(html)
        ids = [int(v["id"]) for v in villages]
        log.info("villages_found", count=len(ids))
        return ids
