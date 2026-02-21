"""Patchright (stealth Playwright) browser automation engine.

Replaces the previous HTTP client approach -- all game interactions now happen
visually through the browser so the user can watch the bot work.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from patchright.async_api import async_playwright, Browser, BrowserContext, Page

from staemme.core.exceptions import (
    BotProtectionDetectedError,
    CaptchaRequiredError,
    CSRFTokenError,
    RateLimitError,
    SessionExpiredError,
)
from staemme.core.logging import get_logger

if TYPE_CHECKING:
    from staemme.core.humanizer import Humanizer

log = get_logger("browser")

# Domain mapping: world prefix → (login URL, game domain)
DOMAIN_MAP = {
    "de": ("https://www.die-staemme.de", "die-staemme.de"),
    "en": ("https://www.tribalwars.net", "tribalwars.net"),
    "nl": ("https://www.tribalwars.nl", "tribalwars.nl"),
    "pl": ("https://www.plemiona.pl", "plemiona.pl"),
}
DEFAULT_DOMAIN = ("https://www.die-staemme.de", "die-staemme.de")


def _domain_for_world(world: str) -> tuple[str, str]:
    """Return (login_url, game_domain) for a world like 'en153' or 'de250'."""
    prefix = "".join(c for c in world if c.isalpha())
    return DOMAIN_MAP.get(prefix, DEFAULT_DOMAIN)

CSRF_PATTERN = re.compile(r"csrf['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]", re.IGNORECASE)
H_PARAM_PATTERN = re.compile(r"[?&]h=([a-f0-9]+)", re.IGNORECASE)

# Known game popup selectors that should be auto-dismissed
POPUP_SELECTORS = [
    ".popup_box_container .popup_box_close",
    "#popup_box_daily_bonus .btn-confirm-yes",
    ".night_bonus_popup .popup_box_close",
    "#ds_body .btn-confirm-yes",
]


class BrowserClient:
    """Full browser automation engine for game interaction."""

    def __init__(
        self,
        session_dir: Path,
        humanizer: Humanizer | None = None,
        headless_mode: str = "headed",
        viewport_width: int = 1280,
        viewport_height: int = 720,
    ) -> None:
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.humanizer = humanizer
        self.headless_mode = headless_mode
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.base_url: str = ""
        self.world: str = ""
        self.csrf_token: str = ""
        self.h_param: str = ""
        self._panel_injector: Any = None  # set by SidePanel after init
        self._bot_monitor: Any = None  # set by App after init

    def _is_game_url(self, url: str) -> bool:
        """Check if a URL is a game page on any supported domain."""
        return any(f"{d[1]}/game.php" in url for d in DOMAIN_MAP.values())

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not launched")
        return self._page

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_headless(self) -> bool:
        return self.headless_mode in ("headless", "xvfb")

    async def launch(self) -> None:
        """Launch stealth browser. Mode depends on headless_mode config."""
        storage_path = self.session_dir / "storage_state.json"
        self._playwright = await async_playwright().start()

        launch_args = ["--disable-blink-features=AutomationControlled"]

        if self.headless_mode == "headed":
            # Desktop mode: maximized window with side panel space
            launch_args.append("--start-maximized")
            headless = False
        elif self.headless_mode == "xvfb":
            # Xvfb mode: real X11 display (preserves stealth), NOT true headless
            # Requires Xvfb to be running (e.g. via entrypoint.sh)
            headless = False
        else:
            # True headless (detectable, use only for testing)
            headless = True

        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=launch_args,
        )

        context_kwargs: dict[str, Any] = {
            "locale": "de-DE",
            "timezone_id": "Europe/Berlin",
        }

        if self.headless_mode == "headed":
            # Desktop: no_viewport lets the browser size itself
            context_kwargs["no_viewport"] = True
        else:
            # Headless/Xvfb: fixed viewport
            context_kwargs["viewport"] = {
                "width": self.viewport_width,
                "height": self.viewport_height,
            }

        if storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)

        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()
        log.info("browser_launched", mode=self.headless_mode)

    async def save_session(self) -> None:
        """Persist browser session (cookies + localStorage) to disk."""
        if self._context:
            storage_path = self.session_dir / "storage_state.json"
            await self._context.storage_state(path=str(storage_path))
            log.debug("session_saved")

    async def close(self) -> None:
        """Save session and close browser."""
        await self.save_session()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        log.info("browser_closed")

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def navigate_to_login(self, world: str = "") -> None:
        """Navigate to the login page."""
        login_url, _ = _domain_for_world(world or self.world or "de")
        await self.page.goto(login_url, wait_until="domcontentloaded")
        log.info("navigated_to_login", url=login_url)

    async def wait_for_game_page(self, timeout: float = 300) -> str:
        """Wait until user completes login. Returns world identifier."""
        log.info("waiting_for_login", timeout_seconds=timeout)
        game_domains = [d[1] for d in DOMAIN_MAP.values()]
        for _ in range(int(timeout)):
            current_url = self.page.url or ""
            if any(f"{d}/game.php" in current_url for d in game_domains):
                break
            await asyncio.sleep(1)
        else:
            raise TimeoutError("Login timed out waiting for game page")

        url = self.page.url
        self.world = url.split("//")[1].split(".")[0] if "//" in url else ""
        _, game_domain = _domain_for_world(self.world)
        self.base_url = f"https://{self.world}.{game_domain}"
        log.info("login_complete", world=self.world, url=url)

        # Extract initial tokens from the landing page
        html = await self.page.content()
        self._extract_tokens(html)
        await self.save_session()

        return self.world

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def navigate_to_screen(
        self,
        screen: str,
        village_id: int,
        extra_params: dict[str, str] | None = None,
    ) -> str:
        """Navigate to a game screen and return the page HTML.

        Uses window.location for in-domain navigation (avoids DNS re-lookup).
        After navigation: dismiss popups, extract tokens, re-inject panel.
        """
        params = f"village={village_id}&screen={screen}"
        if extra_params:
            for k, v in extra_params.items():
                params += f"&{k}={v}"

        if self.humanizer:
            await self.humanizer.wait(f"navigate_{screen}")

        # Use JS navigation to stay within the browser's existing connection.
        # expect_navigation() ensures we wait for the new page to load.
        async with self.page.expect_navigation(wait_until="domcontentloaded"):
            await self.page.evaluate(f"window.location.href = '/game.php?{params}'")
        await self._post_navigation()

        html = await self.page.content()
        self._extract_tokens(html)
        return html

    async def _post_navigation(self) -> None:
        """Actions to perform after every navigation."""
        self._check_page_state()
        await self.dismiss_popups()
        if self._bot_monitor:
            result = await self._bot_monitor.check_page(self.page)
            if result:
                raise BotProtectionDetectedError(result.pattern)
        if self._panel_injector:
            await self._panel_injector()

    def _attach_nav_listener(self) -> None:
        """Listen for ALL navigations (including manual user clicks) to re-inject panel."""
        if getattr(self, "_nav_listener_attached", False):
            return
        self._nav_listener_attached = True

        async def _on_load() -> None:
            """Re-inject panel after any page load (bot or user-initiated)."""
            try:
                url = self.page.url or ""
                if self._is_game_url(url) and self._panel_injector:
                    await self._panel_injector()
            except Exception:
                pass

        self.page.on("load", lambda: asyncio.ensure_future(_on_load()))

    def _check_page_state(self) -> None:
        """Check for captcha or session expiration based on URL."""
        url = self.page.url or ""
        if "bot_check" in url or "captcha" in url.lower():
            raise CaptchaRequiredError("Captcha page detected")
        _, game_domain = _domain_for_world(self.world or "de")
        if f"{game_domain}/game.php" not in url and self.base_url and game_domain in url:
            raise SessionExpiredError(f"Redirected away from game: {url}")

    async def dismiss_popups(self) -> None:
        """Close any known game popups/dialogs."""
        for selector in POPUP_SELECTORS:
            try:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Browser interactions
    # ------------------------------------------------------------------

    async def click_element(self, selector: str, timeout: float = 5000) -> None:
        """Wait for an element and click it with human-like behavior."""
        if self.humanizer:
            await self.humanizer.short_wait()
        await self.page.wait_for_selector(selector, timeout=timeout)
        await self.page.click(selector)

    async def fill_input(self, selector: str, value: str, timeout: float = 5000) -> None:
        """Clear and fill an input field."""
        if self.humanizer:
            await self.humanizer.short_wait()
        await self.page.wait_for_selector(selector, timeout=timeout)
        await self.page.fill(selector, value)

    async def get_content(self) -> str:
        """Return the current page HTML."""
        return await self.page.content()

    async def get_element_text(self, selector: str) -> str:
        """Get text content of an element."""
        el = await self.page.query_selector(selector)
        if el:
            return (await el.text_content()) or ""
        return ""

    async def element_exists(self, selector: str) -> bool:
        """Check if an element exists on the page."""
        el = await self.page.query_selector(selector)
        return el is not None

    # ------------------------------------------------------------------
    # Public/Interface data (no game session needed)
    # ------------------------------------------------------------------

    async def get_public_data(self, path: str) -> str:
        """Fetch public data (village.txt etc.) by navigating to the URL."""
        url = f"{self.base_url}{path}"
        resp = await self.page.evaluate(
            """async (url) => {
                const resp = await fetch(url);
                return await resp.text();
            }""",
            url,
        )
        return resp

    async def get_interface_data(self, func: str) -> str:
        """Fetch world interface data (XML) via fetch() to avoid navigation."""
        url = f"{self.base_url}/interface.php?func={func}"
        resp = await self.page.evaluate(
            """async (url) => {
                const resp = await fetch(url);
                return await resp.text();
            }""",
            url,
        )
        return resp

    # ------------------------------------------------------------------
    # Form submission via browser
    # ------------------------------------------------------------------

    async def submit_form(
        self,
        form_data: dict[str, str],
        submit_selector: str | None = None,
    ) -> str:
        """Fill form fields and optionally click submit. Returns page HTML after."""
        for name, value in form_data.items():
            selector = f"input[name='{name}'], select[name='{name}']"
            el = await self.page.query_selector(selector)
            if el:
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    await self.page.select_option(selector, value)
                else:
                    input_type = await el.get_attribute("type") or "text"
                    if input_type == "hidden":
                        await el.evaluate(f"el => el.value = '{value}'")
                    else:
                        await self.page.fill(selector, value)

        if submit_selector:
            if self.humanizer:
                await self.humanizer.short_wait()
            await self.page.click(submit_selector)
            await self.page.wait_for_load_state("domcontentloaded")
            await self._post_navigation()

        html = await self.page.content()
        self._extract_tokens(html)
        return html

    # ------------------------------------------------------------------
    # Token extraction
    # ------------------------------------------------------------------

    def _extract_tokens(self, html: str) -> None:
        """Extract CSRF token and h parameter from HTML."""
        csrf_match = CSRF_PATTERN.search(html)
        if csrf_match:
            self.csrf_token = csrf_match.group(1)

        h_match = H_PARAM_PATTERN.search(html)
        if h_match:
            self.h_param = h_match.group(1)

    # ------------------------------------------------------------------
    # Captcha handling
    # ------------------------------------------------------------------

    async def show_for_captcha(self) -> None:
        """Bring the browser to focus for captcha solving."""
        await self.page.bring_to_front()
        log.warning("captcha_detected", msg="Browser shown for captcha solving")

    async def wait_for_captcha_resolved(self, timeout: float = 120) -> bool:
        """Wait for the user to solve a captcha and return to game page."""
        for _ in range(int(timeout)):
            current_url = self.page.url or ""
            if self._is_game_url(current_url) and "bot_check" not in current_url:
                await self.save_session()
                return True
            await asyncio.sleep(1)
        return False
