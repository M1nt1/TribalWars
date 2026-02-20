"""Battle report screen - parse reports for farm intelligence."""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from staemme.core.browser_client import BrowserClient
from staemme.core.logging import get_logger
from staemme.models.village import Resources

log = get_logger("screen.report")


class ReportScreen:
    """Interact with the battle report screen."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def get_report_list(self, village_id: int, page: int = 0) -> list[dict[str, Any]]:
        """Fetch list of battle reports."""
        extra_params: dict[str, str] = {"mode": "all"}
        if page > 0:
            extra_params["from"] = str(page * 12)

        html = await self.browser.navigate_to_screen(
            "report", village_id, extra_params=extra_params
        )
        parser = HTMLParser(html)
        reports: list[dict[str, Any]] = []

        for row in parser.css("#report_list tbody tr, .report-list tr"):
            link = row.css_first("a[href*='view=']")
            if not link:
                continue

            href = link.attributes.get("href", "")
            view_match = re.search(r"view=(\d+)", href)
            if not view_match:
                continue

            report_id = int(view_match.group(1))
            title = link.text(strip=True)

            is_attack = bool(row.css_first(".report_attack, img[src*='attack']"))
            is_defense = bool(row.css_first(".report_defense, img[src*='def']"))
            has_loot = bool(row.css_first(".report_haul, img[src*='haul']"))

            reports.append({
                "id": report_id,
                "title": title,
                "is_attack": is_attack,
                "is_defense": is_defense,
                "has_loot": has_loot,
            })

        log.debug("reports_listed", village=village_id, count=len(reports))
        return reports

    async def get_report_detail(
        self, village_id: int, report_id: int
    ) -> dict[str, Any]:
        """Parse a single battle report for detailed information."""
        html = await self.browser.navigate_to_screen(
            "report", village_id, extra_params={"view": str(report_id)}
        )
        parser = HTMLParser(html)
        detail: dict[str, Any] = {"id": report_id}

        defender_node = parser.css_first(
            "#attack_info_def .village_anchor, .report_defender a"
        )
        if defender_node:
            coord_text = defender_node.text(strip=True)
            coord_match = re.search(r"\((\d+)\|(\d+)\)", coord_text)
            if coord_match:
                detail["target_x"] = int(coord_match.group(1))
                detail["target_y"] = int(coord_match.group(2))

        loot_node = parser.css_first("#attack_results .report_loot, .loot")
        if loot_node:
            loot_text = loot_node.text(strip=True)
            wood_match = re.search(r"Holz:\s*([\d.]+)", loot_text)
            stone_match = re.search(r"Lehm:\s*([\d.]+)", loot_text)
            iron_match = re.search(r"Eisen:\s*([\d.]+)", loot_text)
            detail["loot"] = Resources(
                wood=int(wood_match.group(1).replace(".", "")) if wood_match else 0,
                stone=int(stone_match.group(1).replace(".", "")) if stone_match else 0,
                iron=int(iron_match.group(1).replace(".", "")) if iron_match else 0,
            )

        wall_node = parser.css_first(".report_wall, #attack_spy_building_wall")
        if wall_node:
            wall_text = wall_node.text(strip=True)
            wall_match = re.search(r"(\d+)", wall_text)
            if wall_match:
                detail["wall_level"] = int(wall_match.group(1))

        def_troops_node = parser.css_first(
            "#attack_info_def_units, .defender_units"
        )
        detail["defender_had_troops"] = False
        if def_troops_node:
            for cell in def_troops_node.css("td.unit-item"):
                try:
                    count = int(cell.text(strip=True).replace(".", ""))
                    if count > 0:
                        detail["defender_had_troops"] = True
                        break
                except ValueError:
                    continue

        detail["attacker_losses"] = {}
        loss_node = parser.css_first("#attack_info_att_units .unit_casualties")
        if loss_node:
            for cell in loss_node.css("td"):
                unit_name = cell.attributes.get("class", "")
                try:
                    count = int(cell.text(strip=True).replace(".", ""))
                    if count > 0:
                        detail["attacker_losses"][unit_name] = count
                except ValueError:
                    continue

        log.debug("report_parsed", report_id=report_id, detail=detail)
        return detail
