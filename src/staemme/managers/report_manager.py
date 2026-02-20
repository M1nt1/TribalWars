"""Report parsing manager - extract intelligence from battle reports."""

from __future__ import annotations

from staemme.core.logging import get_logger
from staemme.game.screens.report import ReportScreen
from staemme.managers.farm_manager import FarmManager

log = get_logger("manager.report")


class ReportManager:
    """Parses battle reports to update farm target intelligence."""

    def __init__(self, report_screen: ReportScreen, farm_manager: FarmManager) -> None:
        self.screen = report_screen
        self.farm = farm_manager
        self._processed_reports: set[int] = set()

    async def run(self, village_id: int) -> int:
        """Process new battle reports. Returns count of reports processed."""
        reports = await self.screen.get_report_list(village_id)
        processed = 0

        for report in reports:
            rid = report["id"]
            if rid in self._processed_reports:
                continue

            # Only process attack reports with loot
            if not report.get("is_attack"):
                self._processed_reports.add(rid)
                continue

            detail = await self.screen.get_report_detail(village_id, rid)
            self._update_farm_intel(detail)
            self._processed_reports.add(rid)
            processed += 1

        if processed:
            log.info("reports_processed", village=village_id, count=processed)
        return processed

    def _update_farm_intel(self, report: dict) -> None:
        """Update farm manager with intel from a battle report."""
        target_x = report.get("target_x")
        target_y = report.get("target_y")
        if target_x is None or target_y is None:
            return

        # Find matching target by coordinates
        target_id = None
        for tid, target in self.farm.targets.items():
            if target.x == target_x and target.y == target_y:
                target_id = tid
                break

        if target_id is None:
            return

        wall_level = report.get("wall_level")
        has_troops = report.get("defender_had_troops", False)
        loot = report.get("loot")
        loot_dict = loot.model_dump() if loot else None

        self.farm.update_target_intel(
            target_id,
            wall_level=wall_level,
            has_troops=has_troops,
            loot=loot_dict,
        )
