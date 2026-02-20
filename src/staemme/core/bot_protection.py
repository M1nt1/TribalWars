"""Bot protection detection and Telegram alerting.

Detects in-page bot protection indicators (padlock icon, popups, etc.)
and alerts the user via Telegram. Detection is extensible via config.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from staemme.core.logging import get_logger

if TYPE_CHECKING:
    from patchright.async_api import Page

log = get_logger("bot_protection")


@dataclass
class DetectionPattern:
    name: str
    selector: str
    description: str = ""


# Default CSS selectors covering both DE and EN variants
DEFAULT_PATTERNS: list[DetectionPattern] = [
    DetectionPattern(
        name="bot_check_link",
        selector='a[href*="screen=bot_check"], a[href*="screen=bot_protection"]',
        description="Link to bot check / bot protection screen",
    ),
    DetectionPattern(
        name="bot_schutz_tooltip_de",
        selector='[data-title*="Bot-Schutz"]',
        description="German tooltip: Bot-Schutz",
    ),
    DetectionPattern(
        name="bot_protection_tooltip_en",
        selector='[data-title*="Bot Protection"]',
        description="English tooltip: Bot Protection",
    ),
    DetectionPattern(
        name="manager_icon",
        selector='.manager_icon[href*="bot_check"]',
        description="Manager icon linking to bot_check",
    ),
    DetectionPattern(
        name="bot_protection_class",
        selector='[class*="bot-protection"], [class*="bot_protection"]',
        description="Element with bot-protection CSS class",
    ),
    DetectionPattern(
        name="bot_check_popup",
        selector="#popup_box_bot_check, #popup_box_bot_protection",
        description="Bot check popup box",
    ),
]


class BotProtectionMonitor:
    """Monitors pages for bot protection indicators and sends Telegram alerts."""

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        alert_cooldown: int = 300,
        check_interval: int = 30,
        extra_selectors: list[str] | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._alert_cooldown = alert_cooldown
        self._check_interval = check_interval
        self._detected = False
        self._last_alert_time: float = 0
        self._periodic_task: asyncio.Task | None = None
        self._resolved_event = asyncio.Event()

        # Build pattern list: defaults + extras
        self._patterns: list[DetectionPattern] = list(DEFAULT_PATTERNS)
        if extra_selectors:
            for i, sel in enumerate(extra_selectors):
                self._patterns.append(
                    DetectionPattern(
                        name=f"custom_{i}",
                        selector=sel,
                        description="User-configured selector",
                    )
                )

    @property
    def detected(self) -> bool:
        return self._detected

    def check_url(self, url: str) -> str | None:
        """Check if URL indicates bot protection (works even when page won't load).

        Returns pattern name if detected, None otherwise.
        """
        url_lower = url.lower()
        if "bot_check" in url_lower or "bot_protection" in url_lower:
            return "url_bot_check"
        return None

    async def check_page(self, page: Page) -> str | None:
        """Check current page for bot protection indicators.

        Returns the pattern name if detected, None otherwise.
        First checks URL (works even when DOM is broken), then DOM selectors.
        """
        # URL-based check first (works even when page fails to load)
        try:
            url = page.url or ""
            url_result = self.check_url(url)
            if url_result:
                return url_result
        except Exception:
            pass

        # DOM-based check
        try:
            for pattern in self._patterns:
                el = await page.query_selector(pattern.selector)
                if el:
                    try:
                        visible = await el.is_visible()
                    except Exception:
                        visible = True  # assume visible if check fails
                    if visible:
                        log.warning(
                            "bot_protection_detected",
                            pattern=pattern.name,
                            selector=pattern.selector,
                        )
                        return pattern.name
        except Exception as e:
            log.debug("bot_protection_check_error", error=str(e))
        return None

    async def on_detection(
        self,
        pattern: str,
        profile: str = "",
        world: str = "",
        village_info: str = "",
    ) -> None:
        """Called when bot protection is detected. Sends Telegram alert with cooldown."""
        self._detected = True

        now = time.time()
        if now - self._last_alert_time < self._alert_cooldown:
            log.debug("telegram_cooldown", remaining=round(self._alert_cooldown - (now - self._last_alert_time)))
            return

        self._last_alert_time = now
        message = (
            f"Bot Protection Detected!\n"
            f"Profile: {profile}\n"
            f"World: {world}\n"
            f"Village: {village_info}\n"
            f"Pattern: {pattern}"
        )
        await self._send_telegram(message)

    def manual_resolve(self) -> None:
        """Signal that bot protection was manually resolved by the user."""
        self._resolved_event.set()

    async def on_clear(self, profile: str = "", world: str = "") -> None:
        """Called when bot protection is no longer detected. Resets state."""
        if not self._detected:
            return
        self._detected = False
        message = (
            f"Bot Protection Cleared\n"
            f"Profile: {profile}\n"
            f"World: {world}\n"
            f"Bot resuming normal operation."
        )
        await self._send_telegram(message)

    async def _send_telegram(self, message: str) -> None:
        """Send a Telegram message via Bot API. Fails silently."""
        if not self._bot_token or not self._chat_id:
            log.debug("telegram_disabled", reason="no token or chat_id")
            return

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode("utf-8")

        def _blocking_send() -> None:
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read()
                log.info("telegram_sent")
            except (urllib.error.URLError, OSError) as e:
                log.warning("telegram_send_failed", error=str(e))

        try:
            await asyncio.to_thread(_blocking_send)
        except Exception as e:
            log.warning("telegram_thread_error", error=str(e))

    def start_periodic_check(
        self,
        page: Page,
        profile: str,
        world: str,
        on_detected: Callable[[str], Coroutine] | None = None,
        on_cleared: Callable[[], Coroutine] | None = None,
    ) -> None:
        """Start a background task that checks for bot protection every N seconds."""
        self.stop_periodic_check()
        self._periodic_task = asyncio.create_task(
            self._periodic_loop(page, profile, world, on_detected, on_cleared)
        )

    def stop_periodic_check(self) -> None:
        """Cancel the periodic background check task."""
        if self._periodic_task and not self._periodic_task.done():
            self._periodic_task.cancel()
            self._periodic_task = None

    async def _periodic_loop(
        self,
        page: Page,
        profile: str,
        world: str,
        on_detected: Callable[[str], Coroutine] | None,
        on_cleared: Callable[[], Coroutine] | None,
    ) -> None:
        """Background loop: check page for bot protection indicators."""
        while True:
            try:
                await asyncio.sleep(self._check_interval)
                pattern = await self.check_page(page)
                if pattern and not self._detected:
                    await self.on_detection(pattern, profile, world)
                    if on_detected:
                        await on_detected(pattern)
                elif not pattern and self._detected:
                    await self.on_clear(profile, world)
                    if on_cleared:
                        await on_cleared()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("periodic_check_error", error=str(e))
