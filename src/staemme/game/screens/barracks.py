"""Barracks screen - infantry training."""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from staemme.core.browser_client import BrowserClient
from staemme.core.extractors import extract_troop_counts
from staemme.core.logging import get_logger
from staemme.models.troops import BARRACKS_UNITS, TrainQueue, TroopCounts

log = get_logger("screen.barracks")


class BarracksScreen:
    """Interact with the Barracks screen for infantry training."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def get_available_troops(self, village_id: int) -> TroopCounts:
        """Get current troop counts visible from barracks."""
        html = await self.browser.navigate_to_screen("barracks", village_id)
        return extract_troop_counts(html)

    async def get_train_queue(self, village_id: int) -> list[TrainQueue]:
        """Get current training queue."""
        html = await self.browser.navigate_to_screen("barracks", village_id)
        parser = HTMLParser(html)
        queue: list[TrainQueue] = []
        for row in parser.css("#trainqueue tr, .trainqueue_row"):
            unit_node = row.css_first("td:first-child img, .unit_link")
            count_node = row.css_first("td:nth-child(2), .train_count")
            if unit_node and count_node:
                unit = unit_node.attributes.get("data-unit", "")
                try:
                    count = int(count_node.text(strip=True).replace(".", ""))
                except ValueError:
                    count = 0
                queue.append(TrainQueue(unit=unit, count=count))
        return queue

    async def train_units(self, village_id: int, units: dict[str, int]) -> bool:
        """Submit a training order by filling input fields and clicking train."""
        if not units:
            return False

        await self.browser.navigate_to_screen("barracks", village_id)

        # Check if barracks screen actually loaded
        if "barracks" not in (self.browser.page.url or ""):
            log.warning("barracks_not_available", village=village_id)
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
            log.info("troops_training", village=village_id, units=units)
            return True

        return False

    async def get_training_info(self, village_id: int, unit: str) -> dict:
        """Navigate to barracks and return training info for a unit.

        Returns dict with keys:
          train_time: seconds per unit (0 if not found)
          max_affordable: max units player can afford (0 if not found)
          queue_seconds: remaining queue time in seconds (0 if no queue)
          barracks_available: whether the barracks page loaded
        """
        html = await self.browser.navigate_to_screen("barracks", village_id)

        if "barracks" not in (self.browser.page.url or ""):
            log.warning("barracks_not_available", village=village_id)
            return {
                "train_time": 0,
                "max_affordable": 0,
                "queue_seconds": 0,
                "barracks_available": False,
            }

        # Prefer JS-based extraction (unit_managers.units has exact build_time)
        js_info = await self._get_training_info_js(unit)
        train_time = js_info.get("train_time", 0)
        max_affordable = js_info.get("max_affordable", 0)
        queue_seconds = js_info.get("queue_seconds", 0)

        # Fallback to HTML parsing if JS didn't work
        if train_time <= 0:
            train_time = self._parse_train_time_from_html(html, unit) or 0
        if max_affordable <= 0:
            max_affordable = self._parse_max_affordable_from_html(html, unit)

        log.info(
            "training_info",
            village=village_id,
            unit=unit,
            train_time=round(train_time),
            max_affordable=max_affordable,
            queue_seconds=queue_seconds,
        )

        return {
            "train_time": round(train_time),
            "max_affordable": max_affordable,
            "queue_seconds": queue_seconds,
            "barracks_available": True,
        }

    async def _get_training_info_js(self, unit: str) -> dict:
        """Extract training info from the game's JS objects.

        Sources:
          - unit_managers.units[unit].build_time  → exact train time per unit
          - unit_build_block.res.pop              → available pop (for max calc)
          - #trainqueue_wrap_barracks rows        → queue completion times
          - Timing.getCurrentServerTime()         → server time for queue calc
        """
        try:
            return await self.browser.page.evaluate("""(unit) => {
                const result = {train_time: 0, max_affordable: 0, queue_seconds: 0};

                // 1. Build time from unit_managers.units
                if (typeof unit_managers !== 'undefined' && unit_managers.units && unit_managers.units[unit]) {
                    result.train_time = unit_managers.units[unit].build_time || 0;
                }

                // 2. Max affordable from the (N) link in the unit's row
                const inp = document.querySelector("input[name='" + unit + "']");
                if (inp) {
                    let row = inp.closest('tr');
                    if (row) {
                        const links = row.querySelectorAll('a');
                        for (const a of links) {
                            const m = a.textContent.match(/\\((\\d+)\\)/);
                            if (m) { result.max_affordable = parseInt(m[1]); break; }
                        }
                    }
                }

                // 3. Queue remaining: find the last completion time in the queue table
                const wrap = document.getElementById('trainqueue_wrap_barracks');
                if (wrap) {
                    const rows = wrap.querySelectorAll('tr.lit, tr.sortable_row');
                    if (rows.length > 0) {
                        // Last row has the final completion time
                        const lastRow = rows[rows.length - 1];
                        const cells = lastRow.querySelectorAll('td');
                        // Duration cell (2nd td) has the remaining time as H:MM:SS
                        if (cells.length >= 2) {
                            const durationText = cells[1].textContent.trim();
                            const m3 = durationText.match(/(\\d+):(\\d{2}):(\\d{2})/);
                            if (m3) {
                                // This is the duration of this specific order, not total remaining
                                // We need total: sum all durations or use completion time
                            }
                        }
                        // Completion time cell (3rd td) has "heute um HH:MM:SS"
                        if (cells.length >= 3) {
                            const compText = cells[2].textContent.trim();
                            const timeMatch = compText.match(/(\\d{2}):(\\d{2}):(\\d{2})/);
                            if (timeMatch) {
                                const h = parseInt(timeMatch[1]);
                                const m = parseInt(timeMatch[2]);
                                const s = parseInt(timeMatch[3]);
                                // Get current server time
                                const now = new Date();
                                const completionToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m, s);
                                // If completion is before now, it's tomorrow
                                if (completionToday < now) {
                                    completionToday.setDate(completionToday.getDate() + 1);
                                }
                                result.queue_seconds = Math.max(0, Math.floor((completionToday - now) / 1000));
                            }
                        }
                    }
                }

                return result;
            }""", unit)
        except Exception as e:
            log.debug("js_training_info_failed", error=str(e))
            return {"train_time": 0, "max_affordable": 0, "queue_seconds": 0}

    @staticmethod
    def _parse_train_time_from_html(html: str, unit: str) -> int | None:
        """Fallback: extract per-unit training time from HTML."""
        parser = HTMLParser(html)
        inp = parser.css_first(f"input[name='{unit}']")
        if not inp:
            return None

        row = inp.parent
        while row and row.tag != "tr":
            row = row.parent
        if not row:
            return None

        row_text = row.text()
        m = re.search(r"(\d+):(\d{2}):(\d{2})", row_text)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        m = re.search(r"(\d+):(\d{2})", row_text)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        return None

    @staticmethod
    def _parse_max_affordable_from_html(html: str, unit: str) -> int:
        """Fallback: extract max affordable from the (N) link in HTML."""
        parser = HTMLParser(html)
        inp = parser.css_first(f"input[name='{unit}']")
        if not inp:
            return 0

        row = inp.parent
        while row and row.tag != "tr":
            row = row.parent
        if not row:
            return 0

        for link in row.css("a"):
            m = re.search(r"\((\d+)\)", link.text(strip=True))
            if m:
                return int(m.group(1))

        m = re.search(r"\((\d+)\)", row.text())
        if m:
            return int(m.group(1))
        return 0

    async def get_queue_remaining_seconds(self, village_id: int) -> int:
        """Get remaining seconds on the current training queue.

        Parses the last completion time from the trainqueue DOM rows
        and compares against current time.
        """
        try:
            remaining = await self.browser.page.evaluate("""() => {
                const wrap = document.getElementById('trainqueue_wrap_barracks');
                if (!wrap) return 0;
                const rows = wrap.querySelectorAll('tr.lit, tr.sortable_row');
                if (rows.length === 0) return 0;
                const lastRow = rows[rows.length - 1];
                const cells = lastRow.querySelectorAll('td');
                if (cells.length < 3) return 0;
                const compText = cells[2].textContent.trim();
                const timeMatch = compText.match(/(\\d{2}):(\\d{2}):(\\d{2})/);
                if (!timeMatch) return 0;
                const h = parseInt(timeMatch[1]);
                const m = parseInt(timeMatch[2]);
                const s = parseInt(timeMatch[3]);
                const now = new Date();
                const comp = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m, s);
                if (comp < now) comp.setDate(comp.getDate() + 1);
                return Math.max(0, Math.floor((comp - now) / 1000));
            }""")
            return max(0, int(remaining))
        except Exception as e:
            log.debug("queue_timer_read_failed", error=str(e))
            return 0
