"""Abstract panel interface — decouples bot logic from rendering target.

SidePanel renders to the browser DOM (headed mode).
APIPanel broadcasts over WebSocket (headless/API mode).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine

from staemme.core.panel_state import PanelStateStore, VillageStatus

ActionCallback = Callable[[str], Coroutine[Any, Any, None]]


class PanelInterface(ABC):
    """Base class for all panel implementations."""

    def __init__(self) -> None:
        self.state = PanelStateStore()
        self._action_handlers: dict[str, ActionCallback] = {}

    def on_action(self, action: str, callback: ActionCallback) -> None:
        """Register a callback for a panel action."""
        self._action_handlers[action] = callback

    async def _dispatch_action(self, action: str, value: str) -> None:
        """Dispatch an action to its registered handler."""
        handler = self._action_handlers.get(action)
        if handler:
            await handler(value)

    @abstractmethod
    async def setup(self) -> None:
        """Initialize the panel (inject DOM, start WebSocket, etc.)."""

    @abstractmethod
    async def update_status(self, state: str) -> None:
        """Update bot state (running/paused/stopped)."""

    @abstractmethod
    async def add_log(self, message: str, level: str = "info") -> None:
        """Add a log entry and push to UI."""

    @abstractmethod
    async def update_timer(self, timer_id: str, label: str, end_ts: float) -> None:
        """Set or update a countdown timer."""

    @abstractmethod
    async def update_village_status(self, status: VillageStatus) -> None:
        """Push updated village resources/info."""

    @abstractmethod
    async def update_toggles(self, toggles: dict[str, bool]) -> None:
        """Push toggle states to UI."""

    @abstractmethod
    async def update_build_queue(self, village_id: int) -> None:
        """Push build queue state for a village."""

    @abstractmethod
    async def update_troops_mode(self, mode: str, fill_units: list[str]) -> None:
        """Push troops mode label to UI."""

    @abstractmethod
    async def update_bot_protection(self, detected: bool, pattern: str = "") -> None:
        """Push bot protection alert state to UI."""

    @abstractmethod
    async def update_fill_unit(self, unit: str) -> None:
        """Push fill-scavenge training unit selection to UI."""
