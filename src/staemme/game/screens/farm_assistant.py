"""Farm Assistant screen (am_farm) - mass farming interface."""

from __future__ import annotations

import asyncio
import math
import random
import re
from typing import Any

from selectolax.parser import HTMLParser

from staemme.core.browser_client import BrowserClient
from staemme.core.logging import get_logger

log = get_logger("screen.farm")


class FarmAssistantScreen:
    """Interact with the Farm Assistant (am_farm) screen."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def get_farm_list(self, village_id: int) -> list[dict[str, Any]]:
        """Fetch the farm target list from the farm assistant."""
        html = await self.browser.navigate_to_screen("am_farm", village_id)
        parser = HTMLParser(html)
        targets: list[dict[str, Any]] = []

        for row in parser.css("#plunder_list tbody tr"):
            row_id = row.attributes.get("id", "")
            vid_match = re.search(r"(\d+)", row_id)
            if not vid_match:
                continue

            target_id = int(vid_match.group(1))

            coord_node = row.css_first("td:nth-child(2) a, .village_anchor")
            coord_text = coord_node.text(strip=True) if coord_node else ""
            coord_match = re.search(r"\((\d+)\|(\d+)\)", coord_text)
            x = int(coord_match.group(1)) if coord_match else 0
            y = int(coord_match.group(2)) if coord_match else 0

            dist_node = row.css_first("td:nth-child(3), .distance")
            distance = 0.0
            if dist_node:
                try:
                    distance = float(dist_node.text(strip=True).replace(",", "."))
                except ValueError:
                    pass

            loot_node = row.css_first("td .res, .loot")
            last_loot = loot_node.text(strip=True) if loot_node else ""

            wall_node = row.css_first(".wall_level, td:nth-child(5)")
            wall_level = 0
            if wall_node:
                wall_text = wall_node.text(strip=True)
                wall_match = re.search(r"\d+", wall_text)
                if wall_match:
                    wall_level = int(wall_match.group())

            targets.append({
                "id": target_id,
                "x": x,
                "y": y,
                "distance": distance,
                "wall_level": wall_level,
                "last_loot": last_loot,
            })

        log.info("farm_list_fetched", village=village_id, count=len(targets))
        return targets

    async def run_farm_cycle(
        self,
        village_id: int,
        lc_threshold: int,
        lc_carry: int,
    ) -> int:
        """Run one farm cycle using Template C / Template A logic.

        For each target row:
        - Parse estimated haul from the row
        - Calculate lc_needed = ceil(total_haul / lc_carry)
        - If lc_needed <= lc_threshold -> click Template C
        - If lc_needed > lc_threshold -> click Template A
        - Skip if the chosen button is disabled
        - Stop when all rows processed or troops exhausted

        Returns number of attacks sent.
        """
        html = await self.browser.navigate_to_screen("am_farm", village_id)
        parser = HTMLParser(html)
        rows = parser.css("#plunder_list tbody tr")

        if not rows:
            log.info("farm_no_targets", village=village_id)
            return 0

        sent = 0
        for row in rows:
            row_id = row.attributes.get("id", "")
            if not re.search(r"\d+", row_id):
                continue

            # Parse estimated haul from the row
            total_haul = self._parse_haul(row)
            if total_haul <= 0:
                # No haul estimate — use Template A as safe fallback
                template = "a"
            else:
                lc_needed = math.ceil(total_haul / lc_carry) if lc_carry > 0 else 999
                template = "c" if lc_needed <= lc_threshold else "a"

            # Build selector for the enabled template button
            enabled_sel = f"#{row_id} a.farm_icon_{template}:not(.farm_icon_disabled)"
            if not await self.browser.element_exists(enabled_sel):
                enabled_sel = f"tr[id='{row_id}'] a.farm_icon_{template}:not(.farm_icon_disabled)"
                if not await self.browser.element_exists(enabled_sel):
                    continue

            try:
                await self.browser.click_element(enabled_sel, timeout=3000)
                # Wait for AJAX response
                await asyncio.sleep(random.uniform(0.5, 0.9))
                # Verify: a successful send disables the button (adds farm_icon_disabled).
                # If the button is still enabled, the click had no effect — troops exhausted.
                if await self.browser.element_exists(enabled_sel):
                    log.info("farm_troops_exhausted", sent=sent, row=row_id)
                    break
                sent += 1
                log.debug(
                    "farm_attack_clicked",
                    row=row_id,
                    template=template,
                    haul=total_haul,
                )
            except Exception:
                log.debug("farm_click_failed", row=row_id, template=template)
                break

        log.info("farm_cycle_complete", village=village_id, sent=sent)
        return sent

    @staticmethod
    def _parse_haul(row) -> int:
        """Parse estimated haul from a farm assistant row.

        The farm assistant shows expected resources in a cell with
        resource icons and numbers (e.g. "1.200 800 600").
        """
        # Look for the haul/expected resources cell
        # Farm assistant typically has a "Erwartete Beute" (expected loot) column
        # with spans containing resource amounts
        haul_node = row.css_first(".expected-resources, td.haul, .estimate")
        if haul_node:
            numbers = re.findall(r"[\d.]+", haul_node.text(strip=True))
            total = 0
            for n in numbers:
                try:
                    total += int(n.replace(".", ""))
                except ValueError:
                    pass
            return total

        # Fallback: scan for resource spans in the loot column
        # The farm assistant shows loot as individual resource icons with values
        res_nodes = row.css("span.res, .icon-container + span")
        if res_nodes:
            total = 0
            for node in res_nodes:
                text = node.text(strip=True).replace(".", "")
                m = re.search(r"\d+", text)
                if m:
                    total += int(m.group())
            return total

        # Last resort: look for any resource-like numbers in the row
        # (beyond coordinate and distance columns)
        cells = row.css("td")
        if len(cells) >= 6:
            # Typically columns: checkbox, village, distance, loot/resources, wall, buttons
            # Try parsing the resources cell (usually 4th or 5th)
            for cell_idx in range(3, min(6, len(cells))):
                cell_text = cells[cell_idx].text(strip=True)
                numbers = re.findall(r"[\d.]+", cell_text)
                if len(numbers) >= 2:
                    total = 0
                    for n in numbers:
                        try:
                            val = int(n.replace(".", ""))
                            if val > 0:
                                total += val
                        except ValueError:
                            pass
                    if total > 0:
                        return total

        return 0
