"""FastAPI application factory — runs in the same asyncio loop as the bot."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from staemme.api.routes import router, set_app
from staemme.api.websocket import ConnectionManager
from staemme.core.logging import get_logger

if TYPE_CHECKING:
    from staemme.app import Application

log = get_logger("api_server")

# Dashboard build output (relative to project root)
DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "dashboard" / "dist"


def create_app(application: Application, ws_manager: ConnectionManager) -> FastAPI:
    """Create the FastAPI app and wire it to the bot Application."""
    api = FastAPI(title="Staemme Bot API", version="1.0.0")

    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Inject bot reference into routes
    set_app(application)

    api.include_router(router)

    @api.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws_manager.connect(ws)
        # Send full state on connect
        state_dict = application.panel.state.to_json_dict()
        await ws_manager.send_full_state(ws, state_dict)
        try:
            while True:
                # Listen for client messages (commands)
                data = await ws.receive_json()
                action = data.get("action", "")
                value = data.get("value", "")
                if action:
                    await application.panel._dispatch_action(action, value)
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)
        except Exception:
            ws_manager.disconnect(ws)

    # Serve dashboard static files (production build)
    if DASHBOARD_DIR.exists():
        # Serve assets (JS, CSS, etc.) at /assets/
        assets_dir = DASHBOARD_DIR / "assets"
        if assets_dir.exists():
            api.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # SPA fallback: serve index.html for any non-API, non-WS route
        index_html = DASHBOARD_DIR / "index.html"

        @api.get("/{path:path}")
        async def serve_spa(path: str) -> FileResponse:
            # Try serving static file first
            file_path = DASHBOARD_DIR / path
            if path and file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            # Fall back to index.html for SPA routing
            return FileResponse(str(index_html))

        log.info("dashboard_static_files_mounted", path=str(DASHBOARD_DIR))
    else:
        log.warning("dashboard_not_built", expected=str(DASHBOARD_DIR))

    return api


async def run_api_server(
    application: Application,
    ws_manager: ConnectionManager,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Run the API server as an asyncio task (non-blocking)."""
    api = create_app(application, ws_manager)
    config = uvicorn.Config(
        app=api,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    log.info("api_server_starting", host=host, port=port)
    await server.serve()
