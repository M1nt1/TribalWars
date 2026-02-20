"""APIPanel — PanelInterface implementation that broadcasts over WebSocket.

Used in headless/API mode as a replacement for the in-browser SidePanel.
"""

from __future__ import annotations

from staemme.api.websocket import ConnectionManager
from staemme.core.logging import get_logger
from staemme.core.panel_interface import PanelInterface
from staemme.core.panel_state import VillageStatus

log = get_logger("api_panel")


class APIPanel(PanelInterface):
    """Panel that broadcasts state changes over WebSocket instead of browser DOM."""

    def __init__(self, ws_manager: ConnectionManager) -> None:
        super().__init__()
        self.ws = ws_manager

    async def setup(self) -> None:
        log.info("api_panel_initialized")

    async def update_status(self, state: str = "", **_kwargs) -> None:
        if state:
            self.state.bot_state = state
            await self.ws.broadcast("bot_state", {"state": state})

    async def add_log(self, message: str, level: str = "info") -> None:
        entry = self.state.add_log(message, level)
        await self.ws.broadcast("log", {
            "ts": entry.timestamp,
            "msg": entry.message,
            "lvl": entry.level,
        })

    async def update_timer(self, timer_id: str, label: str, end_ts: float) -> None:
        self.state.set_timer(timer_id, label, end_ts)
        await self.ws.broadcast("timer", {
            "id": timer_id,
            "label": label,
            "end_ts": end_ts,
        })

    async def update_village_status(self, vs: VillageStatus) -> None:
        self.state.set_village_status(vs)
        await self.ws.broadcast("village_status", {
            "village_id": vs.village_id,
            "name": vs.name, "x": vs.x, "y": vs.y, "points": vs.points,
            "wood": vs.wood, "stone": vs.stone, "iron": vs.iron,
            "storage": vs.storage, "pop": vs.population, "pop_max": vs.max_population,
            "incoming": vs.incoming,
            "wood_rate": vs.wood_rate, "stone_rate": vs.stone_rate, "iron_rate": vs.iron_rate,
        })

    async def update_toggles(self, toggles: dict[str, bool]) -> None:
        self.state.toggle_states.update(toggles)
        await self.ws.broadcast("toggles", self.state.toggle_states)

    async def update_build_queue(self, village_id: int) -> None:
        steps = self.state.build_queues.get(village_id, [])
        levels = self.state.building_levels.get(village_id, {})
        await self.ws.broadcast("build_queue", {
            "village_id": village_id,
            "steps": steps,
            "levels": levels,
        })

    async def update_troops_mode(self, mode: str, fill_units: list[str] | None = None) -> None:
        if mode == "fill_scavenge":
            unit_str = ", ".join(fill_units) if fill_units else "spear"
            label = f"(fill: {unit_str})"
        elif mode == "targets":
            label = "(targets)"
        else:
            label = ""
        self.state.troops_mode_label = label
        await self.ws.broadcast("troops_mode", {"label": label})

    async def update_bot_protection(self, detected: bool, pattern: str = "") -> None:
        self.state.bot_protection_detected = detected
        self.state.bot_protection_pattern = pattern
        await self.ws.broadcast("bot_protection", {
            "detected": detected,
            "pattern": pattern,
        })

    async def update_fill_unit(self, unit: str) -> None:
        self.state.fill_unit = unit
        await self.ws.broadcast("fill_unit", {"unit": unit})
