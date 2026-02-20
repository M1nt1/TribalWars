"""Headquarters (main building) screen - building upgrades."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from selectolax.parser import HTMLParser

from staemme.core.browser_client import BrowserClient
from staemme.core.exceptions import BuildQueueFullError
from staemme.core.extractors import (
    _german_name_to_id,
    extract_build_queue,
    extract_building_levels,
)
from staemme.core.logging import get_logger
from staemme.models.buildings import BuildQueue
from staemme.models.village import Resources

log = get_logger("screen.hq")


class HeadquartersScreen:
    """Interact with the Headquarters (main) screen."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def get_hq_state(self, village_id: int) -> dict[str, Any]:
        """Fetch full HQ state in a single navigation.

        Returns dict with keys: html, levels, queue, available, premium.
        """
        html = await self.browser.navigate_to_screen("main", village_id)
        levels = extract_building_levels(html)

        # Try JS-based queue extraction first (more reliable for timers)
        queue = await self._get_build_queue_js()
        if not queue:
            queue = extract_build_queue(html)

        # Try JS-based available buildings (more reliable selectors)
        available = await self._get_available_buildings_js()
        if not available:
            available = _parse_available_buildings(html)

        # Detect premium status
        premium = await self._detect_premium()

        log.debug(
            "hq_state",
            village=village_id,
            levels_count=len(levels),
            queue_size=len(queue),
            available_count=len(available),
            premium=premium,
        )

        return {
            "html": html,
            "levels": levels,
            "queue": queue,
            "available": available,
            "premium": premium,
        }

    async def get_building_levels(self, village_id: int) -> dict[str, int]:
        """Fetch current building levels."""
        html = await self.browser.navigate_to_screen("main", village_id)
        levels = extract_building_levels(html)
        log.debug("building_levels", village=village_id, levels=levels)
        return levels

    async def get_build_queue(self, village_id: int) -> list[BuildQueue]:
        """Fetch current building queue."""
        html = await self.browser.navigate_to_screen("main", village_id)
        return extract_build_queue(html)

    async def get_available_buildings(self, village_id: int) -> dict[str, dict]:
        """Get buildings available for upgrade and their costs."""
        html = await self.browser.navigate_to_screen("main", village_id)
        return _parse_available_buildings(html)

    async def upgrade_building(self, village_id: int, building_name: str) -> bool:
        """Submit a building upgrade by clicking the upgrade button."""
        html = await self.browser.navigate_to_screen("main", village_id)

        # Check queue capacity
        queue = extract_build_queue(html)
        if len(queue) >= 2:
            raise BuildQueueFullError(f"Build queue full ({len(queue)} items)")

        # Try multiple selector strategies
        selectors = [
            f"#main_buildrow_{building_name} .btn-build",
            f"#main_buildrow_{building_name} a[class*='btn-build']",
            f"a.btn-build[data-building='{building_name}']",
            f"a.btn-build[href*='id={building_name}']",
            f"#main_buildrow_{building_name} a[href*='action=upgrade']",
            f"#main_buildrow_{building_name} a[href*='id={building_name}']",
        ]
        for selector in selectors:
            if await self.browser.element_exists(selector):
                await self.browser.click_element(selector)
                log.info("building_ordered", village=village_id, building=building_name, selector=selector)
                return True

        # JS fallback: find and click any upgrade link in the building row
        clicked = await self.browser.page.evaluate(f"""
            (() => {{
                const row = document.getElementById('main_buildrow_{building_name}');
                if (!row) return false;
                // Find any link with action=upgrade or id={building_name} in href
                const links = row.querySelectorAll('a[href]');
                for (const a of links) {{
                    if (a.href.includes('action=upgrade') ||
                        (a.href.includes('id={building_name}') && a.href.includes('screen=main'))) {{
                        a.click();
                        return true;
                    }}
                }}
                return false;
            }})()
        """)
        if clicked:
            log.info("building_ordered_js", village=village_id, building=building_name)
            return True

        log.warning("build_button_not_found", village=village_id, building=building_name)
        return False

    async def _get_build_queue_js(self) -> list[BuildQueue]:
        """Extract build queue via JS for more reliable timer data."""
        try:
            result = await self.browser.page.evaluate("""
                (() => {
                    const rows = document.querySelectorAll('#buildqueue tr');
                    const queue = [];
                    rows.forEach(row => {
                        const tds = row.querySelectorAll('td');
                        if (tds.length < 2) return;

                        // Get building display name from first td text
                        const nameText = tds[0] ? tds[0].textContent.trim() : '';
                        if (!nameText) return;

                        // Get target level from second td
                        let level = 0;
                        const levelText = tds[1] ? tds[1].textContent : '';
                        const lm = levelText.match(/(\\d+)/);
                        if (lm) level = parseInt(lm[1]);

                        // Get finish time from data-endtime
                        let endtime = 0;
                        const timerEl = row.querySelector('[data-endtime]');
                        if (timerEl) {
                            endtime = parseInt(timerEl.getAttribute('data-endtime') || '0');
                        }

                        queue.push({name: nameText, level, endtime});
                    });
                    return queue;
                })()
            """)
            if not result:
                return []
            queue = []
            for item in result:
                # Map German display name to internal building ID
                display_name = item.get("name", "")
                building_id = _german_name_to_id(display_name)
                if not building_id:
                    log.info("unknown_building_name", name=display_name)
                    continue

                finish_time = None
                if item.get("endtime", 0) > 0:
                    finish_time = datetime.fromtimestamp(item["endtime"])
                log.info(
                    "build_queue_entry",
                    building=building_id,
                    display=display_name,
                    level=item.get("level"),
                    endtime=item.get("endtime"),
                )
                queue.append(BuildQueue(
                    building=building_id,
                    target_level=item.get("level", 0),
                    finish_time=finish_time,
                ))
            return queue
        except Exception as e:
            log.info("js_queue_extraction_failed", error=str(e))
            return []

    async def _get_available_buildings_js(self) -> dict[str, dict]:
        """Extract available buildings via JS from building rows."""
        try:
            result = await self.browser.page.evaluate("""
                (() => {
                    const available = {};
                    const rows = document.querySelectorAll('tr[id^="main_buildrow_"]');
                    rows.forEach(row => {
                        const buildingName = row.id.replace('main_buildrow_', '');
                        // Check if there's a clickable upgrade link
                        const links = row.querySelectorAll('a[href]');
                        let hasUpgrade = false;
                        for (const a of links) {
                            if (a.href.includes('action=upgrade') ||
                                (a.href.includes('id=' + buildingName) &&
                                 a.href.includes('screen=main') &&
                                 a.textContent.match(/Stufe/))) {
                                hasUpgrade = true;
                                break;
                            }
                        }
                        // Also check for btn-build class
                        if (!hasUpgrade && row.querySelector('.btn-build, a[class*="btn-build"]')) {
                            hasUpgrade = true;
                        }
                        if (!hasUpgrade) return;

                        // Parse costs from spans with class cost_wood etc or icons
                        let wood = 0, stone = 0, iron = 0;
                        const spans = row.querySelectorAll('span[class*="cost_"]');
                        spans.forEach(s => {
                            const val = parseInt(s.textContent.replace(/\\./g, '').replace(/,/g, '')) || 0;
                            if (s.className.includes('wood')) wood = val;
                            else if (s.className.includes('stone')) stone = val;
                            else if (s.className.includes('iron')) iron = val;
                        });
                        available[buildingName] = {wood, stone, iron};
                    });
                    return available;
                })()
            """)
            if not result:
                return {}
            available: dict[str, dict] = {}
            for name, costs in result.items():
                available[name] = {
                    "cost": Resources(
                        wood=costs.get("wood", 0),
                        stone=costs.get("stone", 0),
                        iron=costs.get("iron", 0),
                    ),
                }
            log.info("available_buildings_js", count=len(available), buildings=list(available.keys()))
            return available
        except Exception as e:
            log.info("js_available_extraction_failed", error=str(e))
            return {}

    async def _detect_premium(self) -> bool:
        """Detect if the account has premium (allows 2-slot build queue)."""
        try:
            result = await self.browser.page.evaluate(
                "typeof game_data !== 'undefined' && game_data.features && "
                "game_data.features.Premium && game_data.features.Premium.active || false"
            )
            return bool(result)
        except Exception:
            return False


def _parse_available_buildings(html: str) -> dict[str, dict]:
    """Parse available buildings and their costs from HQ HTML."""
    parser = HTMLParser(html)
    available: dict[str, dict] = {}

    for row in parser.css("#buildings .buildorder_building, .build_options tr"):
        build_link = row.css_first("a.btn-build, .order_feature a[href]")
        if not build_link:
            continue

        href = build_link.attributes.get("href", "")
        building_match = re.search(r"id=(\w+)", href)
        if not building_match:
            continue

        building_name = building_match.group(1)

        wood_node = row.css_first(".cost_wood, .wood")
        stone_node = row.css_first(".cost_stone, .stone")
        iron_node = row.css_first(".cost_iron, .iron")

        def _parse_cost(node) -> int:
            if node is None:
                return 0
            text = node.text(strip=True).replace(".", "").replace(",", "")
            return int(text) if text.isdigit() else 0

        available[building_name] = {
            "cost": Resources(
                wood=_parse_cost(wood_node),
                stone=_parse_cost(stone_node),
                iron=_parse_cost(iron_node),
            ),
            "href": href,
        }

    return available
