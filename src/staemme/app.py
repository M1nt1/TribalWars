"""Application orchestrator - pure asyncio with browser automation and API server."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from datetime import datetime, time as dtime
from pathlib import Path

from staemme.core.bot_protection import BotProtectionMonitor
from staemme.core.browser_client import BrowserClient
from staemme.core.config import (
    AppConfig,
    VillageOverride,
    is_feature_enabled,
    load_config,
)
from staemme.core.database import Database
from staemme.core.exceptions import (
    BotProtectionDetectedError,
    CaptchaRequiredError,
    SessionExpiredError,
)
from staemme.core.humanizer import Humanizer
from staemme.core.logging import get_logger, setup_logging
from staemme.core.panel_interface import PanelInterface
from staemme.core.panel_state import VillageConfig, VillageStatus
from staemme.core.session_manager import SessionManager
from staemme.game.api import GameAPI
from staemme.game.screens.barracks import BarracksScreen
from staemme.game.screens.farm_assistant import FarmAssistantScreen
from staemme.game.screens.headquarters import HeadquartersScreen
from staemme.game.screens.overview import OverviewScreen
from staemme.game.screens.rally_point import RallyPointScreen
from staemme.game.screens.report import ReportScreen
from staemme.game.screens.scavenge import ScavengeScreen
from staemme.game.screens.stable import StableScreen
from staemme.managers.village_manager import VillageManager
from staemme.models.buildings import BuildStep

log = get_logger("app")

PROJECT_ROOT = Path(os.environ.get("STAEMME_ROOT", Path(__file__).resolve().parent.parent.parent))


class Application:
    """Main application orchestrator -- pure asyncio, browser-based."""

    def __init__(
        self,
        profile: str = "default",
        headless: bool = False,
        api_port: int | None = None,
    ) -> None:
        self.profile = profile
        self._headless = headless
        self._api_port = api_port
        # Config: config/<profile>.toml, fallback to config/config.toml
        self.config_dir = PROJECT_ROOT / "config"
        self.config_file = self.config_dir / f"{profile}.toml"
        if not self.config_file.exists():
            self.config_file = self.config_dir / "config.toml"
        # Data and logs are profile-isolated
        self.data_dir = PROJECT_ROOT / "data" / profile
        self.log_dir = PROJECT_ROOT / "logs" / profile

        self.config: AppConfig | None = None
        self.browser: BrowserClient | None = None
        self.session: SessionManager | None = None
        self.panel: PanelInterface | None = None
        self.db: Database | None = None
        self.humanizer: Humanizer | None = None
        self.village_manager: VillageManager | None = None
        self._bot_monitor: BotProtectionMonitor | None = None
        self._running = False
        self._paused = False
        self._village_ids: list[int] = []
        self._next_farm_time: float = 0
        self._start_time: float = 0
        # Action handlers map (used by API routes for toggle dispatch)
        self._action_handlers: dict[str, object] = {}

    async def run(self) -> int:
        """Entry point -- launch browser, login, run bot loop."""
        setup_logging(self.log_dir)
        log.info("application_starting", profile=self.profile)
        self._start_time = time.time()

        # Install SIGTERM handler for graceful K8s shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._handle_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            await self._initialize()
            await self._login()
            await self._setup_panel()

            # Setup + main loop may hit bot protection — stop and wait for user restart
            while True:
                try:
                    self._running = True
                    await self._setup_game()

                    # Run API server alongside bot loop if enabled
                    if self._use_api():
                        from staemme.api.server import run_api_server
                        from staemme.api.websocket import ConnectionManager

                        ws_manager = ConnectionManager()
                        # If panel is APIPanel, give it the ws_manager
                        if hasattr(self.panel, "ws"):
                            self.panel.ws = ws_manager

                        port = self._api_port or self.config.api.port
                        host = self.config.api.host
                        await asyncio.gather(
                            self._main_loop(),
                            run_api_server(self, ws_manager, host=host, port=port),
                        )
                    else:
                        await self._main_loop()
                    break  # clean exit from main loop
                except BotProtectionDetectedError as e:
                    pattern = str(e)
                    await self._handle_bot_protection(pattern)
                    # Bot is now stopped — wait for user to click Start
                    log.info("waiting_for_user_restart_after_bot_protection")
                    while not self._running:
                        await asyncio.sleep(1)
                    log.info("retrying_after_bot_protection")
                    continue
        except KeyboardInterrupt:
            log.info("keyboard_interrupt")
        except Exception as e:
            log.error("fatal_error", error=str(e))
        finally:
            await self._shutdown()
        return 0

    def _use_api(self) -> bool:
        """Whether to start the API server."""
        if self._api_port:
            return True
        if self.config and self.config.api.enabled:
            return True
        return self._headless

    def _handle_signal(self) -> None:
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        log.info("signal_received_shutting_down")
        self._running = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Load config, init DB, launch browser."""
        self.config = load_config(self.config_file)
        log.info("config_loaded", world=self.config.server.world)

        # Override headless mode from CLI
        if self._headless:
            self.config.browser.headless_mode = "xvfb"

        self.db = Database(self.data_dir / "staemme.db")
        await self.db.init()

        self.humanizer = Humanizer(self.config.humanizer)

        self.browser = BrowserClient(
            session_dir=self.data_dir / "session",
            humanizer=self.humanizer,
            headless_mode=self.config.browser.headless_mode,
            viewport_width=self.config.browser.viewport_width,
            viewport_height=self.config.browser.viewport_height,
        )
        await self.browser.launch()

        # Bot protection monitor
        self._bot_monitor = BotProtectionMonitor(
            bot_token=self.config.telegram.bot_token,
            chat_id=self.config.telegram.chat_id,
            alert_cooldown=self.config.telegram.alert_cooldown,
            check_interval=self.config.bot_protection.check_interval,
            extra_selectors=self.config.bot_protection.extra_selectors or None,
        )
        self.browser._bot_monitor = self._bot_monitor

        self.session = SessionManager(self.browser)

    async def _login(self) -> None:
        """Handle login -- try restoring session, fall back to manual login."""
        from staemme.core.browser_client import _domain_for_world
        # Always set world so login navigates to the correct domain
        self.browser.world = self.config.server.world
        _, game_domain = _domain_for_world(self.config.server.world)

        storage_path = self.data_dir / "session" / "storage_state.json"
        if storage_path.exists() and self.browser.base_url == "":
            self.browser.base_url = f"https://{self.config.server.world}.{game_domain}"

        if self.browser.base_url:
            valid = await self.session.validate_session()
            if valid:
                log.info("session_restored", world=self.browser.world)
                return

        log.info("no_valid_session_login_required")
        await self.session.login()

    async def _setup_panel(self) -> None:
        """Initialize the panel — SidePanel (headed) or APIPanel (headless)."""
        if self.browser.is_headless:
            from staemme.api.panel_adapter import APIPanel
            from staemme.api.websocket import ConnectionManager

            # APIPanel broadcasts over WebSocket; ws_manager set later in run()
            self.panel = APIPanel(ConnectionManager())
        else:
            from staemme.core.side_panel import SidePanel

            self.panel = SidePanel(self.browser)

        await self.panel.setup()

        # Register panel action callbacks
        actions = {
            "start": self._on_panel_start,
            "pause": self._on_panel_pause,
            "stop": self._on_panel_stop,
            "toggle_building": self._on_toggle_building,
            "toggle_farming": self._on_toggle_farming,
            "toggle_scavenging": self._on_toggle_scavenging,
            "toggle_troops": self._on_toggle_troops,
            "tab_switch": self._on_tab_switch,
            "log_filter": self._on_log_filter,
            "select_village": self._on_select_village,
            "village_toggle": self._on_village_toggle,
            "farm_threshold": self._on_farm_threshold,
            "bq_add": self._on_bq_add,
            "bq_remove": self._on_bq_remove,
            "bq_move": self._on_bq_move,
            "bq_clear": self._on_bq_clear,
            "scav_troop": self._on_scav_troop,
            "fill_unit": self._on_fill_unit,
            "bot_protection_resolved": self._on_bot_protection_resolved,
        }
        for action, cb in actions.items():
            self.panel.on_action(action, cb)

        # Store handlers map for API route access
        self._action_handlers = {
            f"toggle_{f}": getattr(self, f"_on_toggle_{f}")
            for f in ("building", "farming", "scavenging", "troops")
        }

        # Restore toggle states from disk (defaults to OFF)
        saved = self._load_toggle_states()
        for section in ("building", "farming", "scavenging", "troops"):
            getattr(self.config, section).enabled = saved.get(section, False)
        await self.panel.update_toggles({
            s: saved.get(s, False) for s in ("building", "farming", "scavenging", "troops")
        })
        await self.panel.update_troops_mode(
            self.config.troops.mode, self.config.troops.fill_units
        )
        self.panel.state.farm_lc_threshold = self.config.farming.lc_threshold
        self.panel.state.fill_unit = self.config.troops.fill_units[0] if self.config.troops.fill_units else "spear"

        await self.panel.add_log("Panel initialized", "info")

    async def _setup_game(self) -> None:
        """Initialize game screens and village manager."""
        api = GameAPI(self.browser)
        overview = OverviewScreen(self.browser)
        hq = HeadquartersScreen(self.browser)
        barracks = BarracksScreen(self.browser)
        stable = StableScreen(self.browser)
        rally = RallyPointScreen(self.browser)
        farm_screen = FarmAssistantScreen(self.browser)
        scavenge_screen = ScavengeScreen(self.browser)
        report_screen = ReportScreen(self.browser)

        # Fetch world config for speed and unit carry values
        world_speed = 1.0
        unit_carries: dict[str, int] = {}
        try:
            world_config = await api.fetch_world_config()
            world_speed = world_config.speed
            unit_carries = {
                name: info.carry for name, info in world_config.units.items()
            }
            log.info("world_config_loaded", speed=world_speed, units=len(unit_carries))
        except Exception as e:
            log.warning("world_config_fetch_failed", error=str(e))

        # Feature resolver using per-village overrides
        def feature_resolver(village_id: int, feature: str) -> bool:
            return is_feature_enabled(self.config, village_id, feature)

        self.village_manager = VillageManager(
            config=self.config,
            overview=overview,
            hq=hq,
            barracks=barracks,
            stable=stable,
            rally=rally,
            farm_screen=farm_screen,
            scavenge_screen=scavenge_screen,
            report_screen=report_screen,
            api=api,
            humanizer=self.humanizer,
            config_dir=self.config_dir,
            world_speed=world_speed,
            unit_carries=unit_carries,
            feature_resolver=feature_resolver,
        )

        # Extract initial village ID from the current page (we're already on game.php)
        from staemme.core.extractors import extract_game_data
        html = await self.browser.get_content()
        game_data = extract_game_data(html)
        first_village_id = int(game_data.get("village", {}).get("id", 0))
        if first_village_id == 0:
            import re
            url = self.browser.page.url or ""
            m = re.search(r"village=(\d+)", url)
            if m:
                first_village_id = int(m.group(1))

        # Discover all villages using the known first village ID
        self._village_ids = await overview.get_village_ids(first_village_id)
        log.info("villages_discovered", count=len(self._village_ids))
        await self.panel.add_log(f"Found {len(self._village_ids)} village(s)", "info")

        # Push village IDs to panel state
        self.panel.state.village_ids = self._village_ids
        if self._village_ids:
            self.panel.state.active_village_id = self._village_ids[0]

        # Sync village overrides into panel state
        for vid in self._village_ids:
            override = self.config.village_overrides.get(vid)
            if override:
                self.panel.state.village_configs[vid] = VillageConfig(
                    building=override.building,
                    farming=override.farming,
                    scavenging=override.scavenging,
                    troops=override.troops,
                )

        # Load persisted build queues
        self._load_build_queues()

        # Sync scavenge troop config into panel state
        self.panel.state.sync_scavenge_troops(self.config.scavenging)

        # Push full state to UI so village list appears immediately
        if hasattr(self.panel, "_push_state"):
            await self.panel._push_state()

        # Start periodic bot protection monitor
        self._bot_monitor.start_periodic_check(
            page=self.browser.page,
            profile=self.profile,
            world=self.browser.world,
            on_detected=self._on_bot_protection_detected,
            on_cleared=self._on_bot_protection_cleared,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _main_loop(self) -> None:
        """Run the main bot loop."""
        self._running = True
        await self.panel.update_status(state="running")
        await self.panel.add_log("Bot started", "info")
        log.info("bot_started", villages=len(self._village_ids))

        while self._running:
            try:
                if self._paused:
                    await asyncio.sleep(5)
                    continue

                if not self._is_active_hours():
                    delay = self.humanizer.random_cycle_delay(self.config.bot.inactive_delay)
                    log.debug("inactive_hours_waiting", seconds=delay)
                    await self.panel.add_log("Outside active hours, waiting...", "debug")
                    await asyncio.sleep(delay)
                    continue

                # Process all villages in randomized order
                village_order = self.humanizer.shuffle_order(self._village_ids)
                min_resource_wait = float("inf")
                min_build_finish = float("inf")
                for village_id in village_order:
                    if not self._running or self._paused:
                        break
                    rw, bf = await self._process_village(village_id)
                    if rw and 0 < rw < min_resource_wait:
                        min_resource_wait = rw
                    if bf and bf > time.time() and bf < min_build_finish:
                        min_build_finish = bf

                # Wait between full cycles — use earliest event time
                scavenge_wait = self.village_manager.scavenge.seconds_until_return()

                # Build queue wait — seconds until first slot opens
                build_queue_wait = 0.0
                if min_build_finish < float("inf"):
                    build_queue_wait = min_build_finish - time.time()
                    if build_queue_wait < 0:
                        build_queue_wait = 0

                # Factor in resource wait (wake up when we can afford to build)
                resource_wait = min_resource_wait if min_resource_wait < float("inf") else 0

                # Farm wait — seconds until next farm run
                farm_wait = 0.0
                if self._next_farm_time > 0:
                    farm_wait = self._next_farm_time - time.time()
                    if farm_wait < 0:
                        farm_wait = 0

                # Pick earliest event to wake up for
                wait_events = []
                if scavenge_wait > 30:
                    wait_events.append(("scavenge", scavenge_wait))
                if build_queue_wait > 30:
                    wait_events.append(("build_queue", build_queue_wait))
                if resource_wait > 30:
                    wait_events.append(("resources", resource_wait))
                if farm_wait > 30:
                    wait_events.append(("farming", farm_wait))

                if wait_events:
                    earliest_name, earliest_wait = min(wait_events, key=lambda x: x[1])
                else:
                    earliest_name, earliest_wait = None, 0

                # Determine delay from earliest event
                if earliest_name:
                    delay = earliest_wait + self.humanizer.random_cycle_delay((10, 30))
                    log.info(
                        f"cycle_wait_{earliest_name}",
                        seconds=round(delay),
                        wait_min=round(earliest_wait / 60, 1),
                    )
                    await self.panel.add_log(
                        f"Waiting {round(earliest_wait/60)}min ({earliest_name})", "info"
                    )
                else:
                    delay = self.humanizer.random_cycle_delay(self.config.bot.active_delay)
                    log.info("cycle_wait", seconds=round(delay))
                    await self.panel.add_log(f"Cycle done, waiting {round(delay)}s", "info")

                await self.panel.update_timer(
                    "next_cycle", "Next Cycle", time.time() + delay
                )

                # Train troops during any wait if scavenge is running
                if (
                    self.config.troops.enabled
                    and self.config.troops.mode == "fill_scavenge"
                    and scavenge_wait > 120
                    and delay > 120
                ):
                    log.info("fill_scavenge_during_wait", scavenge_min=round(scavenge_wait / 60, 1))
                    await self.panel.add_log(
                        f"Training troops while waiting ({round(scavenge_wait/60)}min scavenge)", "info"
                    )
                    vid = village_order[0] if village_order else self._village_ids[0]
                    await self.village_manager.troops.run_fill_scavenge(
                        village_id=vid,
                        get_scavenge_remaining=self.village_manager.scavenge.seconds_until_return,
                        panel_log=self.panel.add_log,
                        should_stop=lambda: not self._running or self._paused,
                        timer_callback=self.panel.update_timer,
                    )
                    # After training exits, wait for the earliest remaining event
                    post_events = []
                    scavenge_remaining = self.village_manager.scavenge.seconds_until_return()
                    if scavenge_remaining > 0:
                        post_events.append(("scavenge", scavenge_remaining))
                    if self._next_farm_time > 0:
                        farm_remaining = self._next_farm_time - time.time()
                        if farm_remaining > 0:
                            post_events.append(("farming", farm_remaining))
                    if post_events:
                        evt_name, evt_wait = min(post_events, key=lambda x: x[1])
                        buffer = self.humanizer.random_cycle_delay((10, 30))
                        wait = evt_wait + buffer
                        log.info("post_training_wait", seconds=round(wait), wake_event=evt_name)
                        await self.panel.update_timer(
                            "next_cycle", "Next Cycle", time.time() + wait
                        )
                        await asyncio.sleep(wait)
                else:
                    await asyncio.sleep(delay)

            except Exception as e:
                log.error("main_loop_error", error=str(e))
                await self.panel.add_log(f"Error: {e}", "error")
                # Check if this error was caused by bot protection
                try:
                    url = self.browser.page.url or ""
                    url_pattern = self._bot_monitor.check_url(url)
                    if url_pattern:
                        await self._handle_bot_protection(url_pattern)
                except Exception:
                    pass
                await asyncio.sleep(30)

    async def _process_village(self, village_id: int) -> tuple[float, float]:
        """Process one village with error handling.

        Returns (resource_wait_seconds, build_queue_finish_ts).
        """
        try:
            # Sync panel build queue into building manager
            self._sync_build_queue_to_manager(village_id)

            result = await self.village_manager.run_cycle(village_id)

            # Auto-remove completed build steps and update levels
            await self._auto_remove_completed_steps(village_id)

            # Update panel with village info
            vname = result.get("village_name", "")
            if vname:
                await self.panel.add_log(f"Processed: {vname}", "info")

            # Push village status to panel dashboard
            village = result.get("village")
            if village:
                vs = VillageStatus(
                    village_id=village.id,
                    name=village.name,
                    x=village.x,
                    y=village.y,
                    points=village.points,
                    wood=village.resources.wood,
                    stone=village.resources.stone,
                    iron=village.resources.iron,
                    storage=village.storage,
                    population=village.population,
                    max_population=village.max_population,
                    incoming=village.incoming_attacks,
                    wood_rate=village.production.wood,
                    stone_rate=village.production.stone,
                    iron_rate=village.production.iron,
                )
                await self.panel.update_village_status(vs)

                # Set active village in panel
                self.panel.state.active_village_id = village.id

            # Push timers
            scavenge_wait = result.get("scavenge_wait_seconds", 0)
            if scavenge_wait > 0:
                await self.panel.update_timer(
                    "scavenge_return", "Scavenge Return",
                    time.time() + scavenge_wait,
                )

            # Build queue finish timer
            build_finish_ts = result.get("build_queue_finish", 0)
            if build_finish_ts > time.time():
                await self.panel.update_timer(
                    "building_queue", "Build Queue",
                    build_finish_ts,
                )

            # Resource wait timer
            build_res_wait = result.get("build_resource_wait", 0)
            build_name = result.get("build_waiting_for", "")
            if build_res_wait > 0:
                await self.panel.update_timer(
                    "building_resources",
                    f"Resources for {build_name}",
                    time.time() + build_res_wait,
                )

            # Farm timer — schedule next farm run in 20 min
            if self.config.farming.enabled and result.get("farming") is not False:
                self._next_farm_time = time.time() + 1200  # 20 min
                await self.panel.update_timer(
                    "farm_next", "Next Farm Run", self._next_farm_time
                )

            return (build_res_wait, build_finish_ts)

        except SessionExpiredError:
            log.warning("session_expired_relogin")
            await self.panel.add_log("Session expired, re-logging in...", "warn")
            await self.panel.update_status(state="stopped")
            await self.session.refresh_session()
            await self.panel.setup()
            await self.panel.update_status(state="running")
            return (0, 0)

        except CaptchaRequiredError:
            log.warning("captcha_required")
            await self.panel.add_log("CAPTCHA! Solve it in the browser", "error")
            await self.panel.update_status(state="paused")
            resolved = await self.session.handle_captcha()
            if resolved:
                await self.panel.update_status(state="running")
                await self.panel.add_log("Captcha resolved, resuming", "info")
            else:
                log.error("captcha_not_resolved_pausing")
                self._paused = True
            return (0, 0)

        except BotProtectionDetectedError as e:
            pattern = str(e)
            await self._handle_bot_protection(pattern, village_id)
            return (0, 0)

        except Exception as e:
            log.error("village_cycle_error", village=village_id, error=str(e))
            await self.panel.add_log(f"Village error: {e}", "error")
            # Check if this error was caused by bot protection (page redirect/abort)
            try:
                url = self.browser.page.url or ""
                url_pattern = self._bot_monitor.check_url(url)
                if url_pattern:
                    await self._handle_bot_protection(url_pattern, village_id)
            except Exception:
                pass
            return (0, 0)

    # ------------------------------------------------------------------
    # Panel callbacks
    # ------------------------------------------------------------------

    async def _on_panel_start(self, _value: str) -> None:
        self._running = True
        self._paused = False
        await self.panel.update_status(state="running")
        await self.panel.add_log("Bot started", "info")
        log.info("bot_started_via_panel")

    async def _on_panel_pause(self, _value: str) -> None:
        self._paused = True
        await self.panel.update_status(state="paused")
        await self.panel.add_log("Bot paused", "warn")
        log.info("bot_paused_via_panel")

    async def _on_panel_stop(self, _value: str) -> None:
        self._running = False
        self._paused = False
        await self.panel.update_status(state="stopped")
        await self.panel.add_log("Bot stopped", "warn")
        log.info("bot_stopped_via_panel")

    async def _on_toggle_building(self, value: str) -> None:
        enabled = value == "true"
        self.config.building.enabled = enabled
        self.panel.state.toggle_states["building"] = enabled
        self._save_toggle_states()
        await self.panel.add_log(
            f"Building {'enabled' if enabled else 'disabled'}", "info"
        )

    async def _on_toggle_farming(self, value: str) -> None:
        enabled = value == "true"
        self.config.farming.enabled = enabled
        self.panel.state.toggle_states["farming"] = enabled
        self._save_toggle_states()
        await self.panel.add_log(
            f"Farming {'enabled' if enabled else 'disabled'}", "info"
        )

    async def _on_toggle_scavenging(self, value: str) -> None:
        enabled = value == "true"
        self.config.scavenging.enabled = enabled
        self.panel.state.toggle_states["scavenging"] = enabled
        self._save_toggle_states()
        await self.panel.add_log(
            f"Scavenging {'enabled' if enabled else 'disabled'}", "info"
        )

    async def _on_toggle_troops(self, value: str) -> None:
        enabled = value == "true"
        self.config.troops.enabled = enabled
        self.panel.state.toggle_states["troops"] = enabled
        self._save_toggle_states()
        await self.panel.add_log(
            f"Troops {'enabled' if enabled else 'disabled'}", "info"
        )

    async def _on_farm_threshold(self, value: str) -> None:
        try:
            threshold = int(value)
            if 1 <= threshold <= 100:
                self.config.farming.lc_threshold = threshold
                self.panel.state.farm_lc_threshold = threshold
                await self.panel.add_log(f"Farm LC threshold set to {threshold}", "info")
        except (ValueError, TypeError):
            pass

    async def _on_fill_unit(self, value: str) -> None:
        """Handle fill unit change from panel dropdown."""
        valid_units = {"spear", "sword", "axe", "archer"}
        if value in valid_units:
            self.config.troops.fill_units = [value]
            self.panel.state.fill_unit = value
            await self.panel.update_troops_mode(
                self.config.troops.mode, self.config.troops.fill_units
            )
            await self.panel.add_log(f"Training unit set to {value}", "info")

    async def _on_scav_troop(self, value: str) -> None:
        """Handle scav_troop: unit:field:value."""
        parts = value.split(":")
        if len(parts) != 3:
            return
        unit, field, val = parts
        if field == "enabled":
            enabled = val == "true"
            if enabled:
                self.config.scavenging.scavenge_exclude = [
                    u for u in self.config.scavenging.scavenge_exclude if u != unit
                ]
            else:
                if unit not in self.config.scavenging.scavenge_exclude:
                    self.config.scavenging.scavenge_exclude.append(unit)
        elif field == "reserve":
            try:
                count = int(val)
                if count >= 0:
                    self.config.scavenging.scavenge_reserve[unit] = count
            except ValueError:
                return
        else:
            return
        # Update panel state
        self.panel.state.scavenge_troops[unit] = {
            "enabled": unit not in self.config.scavenging.scavenge_exclude,
            "reserve": self.config.scavenging.scavenge_reserve.get(unit, 0),
        }
        state_str = "enabled" if unit not in self.config.scavenging.scavenge_exclude else "disabled"
        reserve = self.config.scavenging.scavenge_reserve.get(unit, 0)
        await self.panel.add_log(
            f"Scavenge {unit}: {state_str}" + (f", reserve {reserve}" if reserve else ""), "info"
        )

    async def _on_tab_switch(self, value: str) -> None:
        self.panel.state.active_tab = value
        if not self.browser.is_headless:
            await self.browser.page.evaluate(
                f"window.__sp && window.__sp._switchTabUI({json.dumps(value)})"
            )

    async def _on_log_filter(self, value: str) -> None:
        self.panel.state.log_filter = value
        if not self.browser.is_headless:
            await self.browser.page.evaluate(f"""
                (() => {{
                    if (window.__sp && window.__sp._state) {{
                        window.__sp._state.log_filter = {json.dumps(value)};
                        window.__sp._renderLog();
                    }}
                }})()
            """)

    async def _on_select_village(self, value: str) -> None:
        try:
            vid = int(value)
            self.panel.state.active_village_id = vid
            # Re-render dashboard for new village
            if hasattr(self.panel, "_push_state"):
                await self.panel._push_state()
        except (ValueError, TypeError):
            pass

    async def _on_village_toggle(self, value: str) -> None:
        """Handle per-village feature toggle: vid:feature:value."""
        try:
            parts = value.split(":")
            if len(parts) != 3:
                return
            vid = int(parts[0])
            feature = parts[1]
            raw_val = parts[2]

            # Parse three-state value
            if raw_val == "null":
                enabled = None
            elif raw_val == "true":
                enabled = True
            else:
                enabled = False

            # Update config
            if vid not in self.config.village_overrides:
                self.config.village_overrides[vid] = VillageOverride()
            setattr(self.config.village_overrides[vid], feature, enabled)

            # Update panel state
            if vid not in self.panel.state.village_configs:
                self.panel.state.village_configs[vid] = VillageConfig()
            setattr(self.panel.state.village_configs[vid], feature, enabled)

            state_label = "inherit" if enabled is None else ("on" if enabled else "off")
            await self.panel.add_log(
                f"Village {vid} {feature}: {state_label}", "info"
            )
        except (ValueError, TypeError, AttributeError) as e:
            log.error("village_toggle_error", value=value, error=str(e))

    # ------------------------------------------------------------------
    # Build queue panel callbacks
    # ------------------------------------------------------------------

    async def _on_bq_add(self, value: str) -> None:
        """Handle bq_add: vid:building:level."""
        try:
            parts = value.split(":")
            if len(parts) != 3:
                return
            vid = int(parts[0])
            building = parts[1]
            level = int(parts[2])
            if level < 1 or level > 30:
                return
            queue = self.panel.state.build_queues.setdefault(vid, [])
            queue.append({"building": building, "level": level})
            self._save_build_queues()
            await self.panel.update_build_queue(vid)
            await self.panel.add_log(f"Added {building} Lv {level} to build queue", "info")
        except (ValueError, TypeError) as e:
            log.error("bq_add_error", value=value, error=str(e))

    async def _on_bq_remove(self, value: str) -> None:
        """Handle bq_remove: vid:index."""
        try:
            parts = value.split(":")
            if len(parts) != 2:
                return
            vid = int(parts[0])
            idx = int(parts[1])
            queue = self.panel.state.build_queues.get(vid, [])
            if 0 <= idx < len(queue):
                removed = queue.pop(idx)
                self._save_build_queues()
                await self.panel.update_build_queue(vid)
                await self.panel.add_log(
                    f"Removed {removed['building']} Lv {removed['level']} from queue", "info"
                )
        except (ValueError, TypeError) as e:
            log.error("bq_remove_error", value=value, error=str(e))

    async def _on_bq_move(self, value: str) -> None:
        """Handle bq_move: vid:index:direction."""
        try:
            parts = value.split(":")
            if len(parts) != 3:
                return
            vid = int(parts[0])
            idx = int(parts[1])
            direction = parts[2]
            queue = self.panel.state.build_queues.get(vid, [])
            if direction == "up" and 0 < idx < len(queue):
                queue[idx - 1], queue[idx] = queue[idx], queue[idx - 1]
            elif direction == "down" and 0 <= idx < len(queue) - 1:
                queue[idx], queue[idx + 1] = queue[idx + 1], queue[idx]
            else:
                return
            self._save_build_queues()
            await self.panel.update_build_queue(vid)
        except (ValueError, TypeError) as e:
            log.error("bq_move_error", value=value, error=str(e))

    async def _on_bq_clear(self, _value: str) -> None:
        """Clear all build steps for the active village."""
        vid = self.panel.state.active_village_id
        if vid and vid in self.panel.state.build_queues:
            self.panel.state.build_queues[vid] = []
            self._save_build_queues()
            await self.panel.update_build_queue(vid)
            await self.panel.add_log("Build queue cleared", "info")

    # ------------------------------------------------------------------
    # Bot protection handling
    # ------------------------------------------------------------------

    async def _handle_bot_protection(self, pattern: str, village_id: int = 0) -> None:
        """Pause bot, show banner, alert Telegram. Bot stays stopped until user restarts."""
        log.warning("bot_protection_handling", pattern=pattern, village=village_id)
        self._running = False
        self._paused = False
        await self.panel.update_status(state="stopped")
        await self.panel.update_bot_protection(True, pattern)
        await self.panel.add_log(
            "BOT PROTECTION — solve it in the browser, then click Resolved", "error"
        )
        try:
            await self.browser.page.bring_to_front()
        except Exception:
            pass  # page may be broken

        village_info = self._current_village_info(village_id)
        await self._bot_monitor.on_detection(
            pattern,
            profile=self.profile,
            world=self.browser.world,
            village_info=village_info,
        )

    async def _on_bot_protection_resolved(self, _value: str) -> None:
        """Panel callback: user clicked 'Resolved' — clear banner and restart bot."""
        log.info("bot_protection_resolved_by_user")
        self._bot_monitor._detected = False
        await self.panel.update_bot_protection(False)
        await self._bot_monitor.on_clear(
            profile=self.profile, world=self.browser.world
        )
        # Restart the bot
        self._running = True
        self._paused = False
        await self.panel.update_status(state="running")
        await self.panel.add_log("Bot protection resolved, restarting", "info")

    async def _on_bot_protection_detected(self, pattern: str) -> None:
        """Callback from periodic monitor when bot protection appears."""
        if not self._running:
            return  # already stopped
        await self._handle_bot_protection(pattern)

    async def _on_bot_protection_cleared(self) -> None:
        """Callback from periodic monitor when bot protection disappears."""
        # Don't auto-resume — user must click Resolved then Start
        pass

    def _current_village_info(self, village_id: int = 0) -> str:
        """Build a village info string for alert messages."""
        if village_id:
            vs = self.panel.state.village_statuses.get(village_id)
            if vs:
                return f"{vs.name} ({village_id})"
            return str(village_id)
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_active_hours(self) -> bool:
        """Check if current time is within configured active hours."""
        if not self.config:
            return True
        hours_str = self.config.bot.active_hours
        try:
            start_str, end_str = hours_str.split("-")
            sh, sm = map(int, start_str.strip().split(":"))
            eh, em = map(int, end_str.strip().split(":"))
            now = datetime.now().time()
            return dtime(sh, sm) <= now <= dtime(eh, em)
        except (ValueError, AttributeError):
            return True

    # ------------------------------------------------------------------
    # Build queue persistence
    # ------------------------------------------------------------------

    def _bq_path(self) -> Path:
        return self.data_dir / "build_queues.json"

    def _load_build_queues(self) -> None:
        """Load build queues from disk into panel state."""
        path = self._bq_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            # JSON keys are strings, convert to int
            self.panel.state.build_queues = {
                int(vid): steps for vid, steps in raw.items()
            }
            total = sum(len(s) for s in self.panel.state.build_queues.values())
            log.info("build_queues_loaded", villages=len(raw), total_steps=total)
        except Exception as e:
            log.warning("build_queues_load_failed", error=str(e))

    def _save_build_queues(self) -> None:
        """Save build queues from panel state to disk."""
        path = self._bq_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # JSON keys must be strings
        data = {str(vid): steps for vid, steps in self.panel.state.build_queues.items()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _sync_build_queue_to_manager(self, village_id: int) -> None:
        """Overwrite BuildingManager steps from panel queue if present."""
        steps = self.panel.state.build_queues.get(village_id)
        if steps:
            self.village_manager.building.mode = "sequential"
            self.village_manager.building.build_steps = [
                BuildStep(building=s["building"], level=s["level"]) for s in steps
            ]
        # If no panel queue, leave TOML template as-is

    async def _auto_remove_completed_steps(self, village_id: int) -> None:
        """Remove completed build steps and push updated queue to panel."""
        levels = self.village_manager.building._last_levels
        if not levels:
            return

        # Update building_levels in panel state
        self.panel.state.building_levels[village_id] = dict(levels)

        steps = self.panel.state.build_queues.get(village_id)
        if not steps:
            await self.panel.update_build_queue(village_id)
            return

        original_len = len(steps)
        remaining = [
            s for s in steps
            if levels.get(s["building"], 0) < s["level"]
        ]

        if len(remaining) < original_len:
            removed = original_len - len(remaining)
            self.panel.state.build_queues[village_id] = remaining
            self._save_build_queues()
            log.info("build_steps_auto_removed", village=village_id, removed=removed, remaining=len(remaining))
            await self.panel.add_log(f"Removed {removed} completed build step(s)", "info")

        await self.panel.update_build_queue(village_id)

    # ------------------------------------------------------------------
    # Toggle state persistence
    # ------------------------------------------------------------------

    def _toggle_path(self) -> Path:
        return self.data_dir / "toggle_states.json"

    def _load_toggle_states(self) -> dict[str, bool]:
        path = self._toggle_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_toggle_states(self) -> None:
        path = self._toggle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.panel.state.toggle_states), encoding="utf-8")

    async def _shutdown(self) -> None:
        """Graceful shutdown."""
        if self._bot_monitor:
            self._bot_monitor.stop_periodic_check()
        if self.browser:
            await self.browser.close()
        if self.db:
            await self.db.close()
        log.info("application_shutdown")
