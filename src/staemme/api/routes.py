"""REST API routes for bot control and status."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:
    from staemme.app import Application

router = APIRouter(prefix="/api")

# Application reference — set by server.py at startup
_app: Application | None = None


def set_app(app: Application) -> None:
    global _app
    _app = app


def _get_app() -> Application:
    if _app is None:
        raise HTTPException(503, "Bot not initialized")
    return _app


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, Any]:
    app = _get_app()
    return {
        "status": "ok",
        "bot_state": app.panel.state.bot_state,
        "profile": app.profile,
        "villages": len(app._village_ids),
        "uptime_seconds": round(time.time() - app._start_time) if app._start_time else 0,
    }


# ------------------------------------------------------------------
# Status
# ------------------------------------------------------------------


@router.get("/status")
async def get_status() -> dict[str, Any]:
    app = _get_app()
    return app.panel.state.to_json_dict()


# ------------------------------------------------------------------
# Control
# ------------------------------------------------------------------


class ControlAction(BaseModel):
    action: str  # start | pause | stop


@router.post("/control/{action}")
async def control(action: str) -> dict[str, str]:
    app = _get_app()
    if action == "start":
        await app._on_panel_start("")
    elif action == "pause":
        await app._on_panel_pause("")
    elif action == "stop":
        await app._on_panel_stop("")
    else:
        raise HTTPException(400, f"Unknown action: {action}")
    return {"status": "ok", "bot_state": app.panel.state.bot_state}


# ------------------------------------------------------------------
# Toggles
# ------------------------------------------------------------------


@router.get("/toggles")
async def get_toggles() -> dict[str, bool]:
    app = _get_app()
    return dict(app.panel.state.toggle_states)


@router.post("/toggles/{feature}")
async def toggle_feature(feature: str, enabled: bool = True) -> dict[str, Any]:
    app = _get_app()
    valid = ("building", "farming", "scavenging", "troops")
    if feature not in valid:
        raise HTTPException(400, f"Unknown feature: {feature}. Valid: {valid}")

    handler = app._action_handlers.get(f"toggle_{feature}")
    if handler:
        await handler(str(enabled).lower())
    return {"feature": feature, "enabled": enabled}


# ------------------------------------------------------------------
# Villages
# ------------------------------------------------------------------


@router.get("/villages")
async def get_villages() -> dict[str, Any]:
    app = _get_app()
    statuses = {}
    for vid, vs in app.panel.state.village_statuses.items():
        statuses[vid] = {
            "name": vs.name, "x": vs.x, "y": vs.y, "points": vs.points,
            "wood": vs.wood, "stone": vs.stone, "iron": vs.iron,
            "storage": vs.storage, "pop": vs.population, "pop_max": vs.max_population,
            "incoming": vs.incoming,
        }
    return {
        "village_ids": app._village_ids,
        "active_village_id": app.panel.state.active_village_id,
        "statuses": statuses,
    }


# ------------------------------------------------------------------
# Build queue
# ------------------------------------------------------------------


class BuildQueueItem(BaseModel):
    building: str
    level: int


@router.get("/build-queue/{vid}")
async def get_build_queue(vid: int) -> dict[str, Any]:
    app = _get_app()
    return {
        "village_id": vid,
        "steps": app.panel.state.build_queues.get(vid, []),
        "levels": app.panel.state.building_levels.get(vid, {}),
    }


@router.post("/build-queue/{vid}")
async def add_build_step(vid: int, item: BuildQueueItem) -> dict[str, Any]:
    app = _get_app()
    await app._on_bq_add(f"{vid}:{item.building}:{item.level}")
    return {
        "village_id": vid,
        "steps": app.panel.state.build_queues.get(vid, []),
    }


@router.delete("/build-queue/{vid}/{index}")
async def remove_build_step(vid: int, index: int) -> dict[str, Any]:
    app = _get_app()
    await app._on_bq_remove(f"{vid}:{index}")
    return {
        "village_id": vid,
        "steps": app.panel.state.build_queues.get(vid, []),
    }


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------


@router.get("/config")
async def get_config() -> dict[str, Any]:
    app = _get_app()
    return {
        "server": app.config.server.model_dump(),
        "bot": app.config.bot.model_dump(),
        "building": app.config.building.model_dump(),
        "farming": app.config.farming.model_dump(),
        "scavenging": app.config.scavenging.model_dump(),
        "troops": app.config.troops.model_dump(),
        "humanizer": app.config.humanizer.model_dump(),
    }


# ------------------------------------------------------------------
# Farm threshold
# ------------------------------------------------------------------


@router.post("/farm-threshold/{value}")
async def set_farm_threshold(value: int) -> dict[str, int]:
    app = _get_app()
    await app._on_farm_threshold(str(value))
    return {"lc_threshold": app.config.farming.lc_threshold}


# ------------------------------------------------------------------
# Bot protection
# ------------------------------------------------------------------


@router.post("/bot-protection/resolve")
async def resolve_bot_protection() -> dict[str, str]:
    app = _get_app()
    await app._on_bot_protection_resolved("")
    return {"status": "ok", "bot_state": app.panel.state.bot_state}


# ------------------------------------------------------------------
# Fill unit
# ------------------------------------------------------------------


@router.post("/fill-unit/{unit}")
async def set_fill_unit(unit: str) -> dict[str, str]:
    app = _get_app()
    valid = ("spear", "sword", "axe", "archer")
    if unit not in valid:
        raise HTTPException(400, f"Unknown unit: {unit}. Valid: {valid}")
    await app._on_fill_unit(unit)
    return {"unit": app.panel.state.fill_unit}
