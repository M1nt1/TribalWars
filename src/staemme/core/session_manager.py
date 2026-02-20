"""Authentication lifecycle: login via persistent browser, session validation."""

from __future__ import annotations

from pathlib import Path

from staemme.core.browser_client import BrowserClient, GAME_URL_PATTERN
from staemme.core.logging import get_logger

log = get_logger("session")


class SessionManager:
    """Manages game session lifecycle with a persistent browser instance.

    The browser stays open permanently -- no more cookie→httpx conversion.
    Session is persisted via Playwright's storage_state (cookies + localStorage).
    """

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    @property
    def world(self) -> str:
        return self.browser.world

    @property
    def base_url(self) -> str:
        return self.browser.base_url

    async def login(self) -> None:
        """Navigate existing browser page to login, wait for game page."""
        await self.browser.navigate_to_login()
        await self.browser.wait_for_game_page()
        log.info("session_established", world=self.world)

    async def validate_session(self) -> bool:
        """Check if the current session is still valid.

        First navigates to the game URL, then checks if we ended up on game.php
        (vs being redirected to login).
        """
        try:
            await self.browser.page.goto(
                f"{self.base_url}/game.php", wait_until="domcontentloaded"
            )
            url = self.browser.page.url or ""
            valid = GAME_URL_PATTERN in url
            if valid:
                log.info("session_valid", url=url)
            else:
                log.warning("session_invalid", url=url)
            return valid
        except Exception as e:
            log.error("session_validation_failed", error=str(e))
            return False

    async def refresh_session(self) -> None:
        """Re-login via browser when session expires."""
        log.info("session_refresh_starting")
        await self.login()

    async def handle_captcha(self) -> bool:
        """Show browser for captcha solving, wait for resolution."""
        await self.browser.show_for_captcha()
        resolved = await self.browser.wait_for_captcha_resolved()
        if resolved:
            log.info("captcha_resolved")
        else:
            log.error("captcha_not_resolved")
        return resolved
