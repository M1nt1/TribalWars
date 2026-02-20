"""WebSocket connection manager for live bot state broadcasting."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket

from staemme.core.logging import get_logger

log = get_logger("ws")


class ConnectionManager:
    """Manages WebSocket connections and broadcasts state updates."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        log.info("ws_connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        log.info("ws_disconnected", total=len(self._connections))

    async def broadcast(self, event: str, data: Any) -> None:
        """Broadcast a JSON message to all connected clients."""
        if not self._connections:
            return
        message = json.dumps({"event": event, "data": data}, separators=(",", ":"))
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def send_full_state(self, ws: WebSocket, state_dict: dict) -> None:
        """Send the complete state to a single newly-connected client."""
        message = json.dumps(
            {"event": "full_state", "data": state_dict}, separators=(",", ":")
        )
        try:
            await ws.send_text(message)
        except Exception:
            self.disconnect(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)
