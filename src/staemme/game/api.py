"""Central game API client - delegates to screen modules."""

from __future__ import annotations

from staemme.core.browser_client import BrowserClient
from staemme.core.extractors import (
    extract_game_data,
    parse_building_info_xml,
    parse_map_village_txt,
    parse_unit_info_xml,
    parse_world_config_xml,
)
from staemme.core.logging import get_logger
from staemme.models.world import BuildingInfo, UnitInfo, WorldConfig

log = get_logger("api")


class GameAPI:
    """Facade for all game interactions."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser

    async def fetch_world_config(self) -> WorldConfig:
        """Fetch and parse world configuration."""
        config_xml = await self.browser.get_interface_data("get_config")
        config_data = parse_world_config_xml(config_xml)

        unit_xml = await self.browser.get_interface_data("get_unit_info")
        unit_data = parse_unit_info_xml(unit_xml)

        building_xml = await self.browser.get_interface_data("get_building_info")
        building_data = parse_building_info_xml(building_xml)

        units = {}
        for name, info in unit_data.items():
            units[name] = UnitInfo(
                name=name,
                pop=info.get("pop", 1),
                speed=info.get("speed", 1.0),
                attack=info.get("att", 0),
                defense=info.get("def", 0),
                defense_cavalry=info.get("def_cavalry", 0),
                defense_archer=info.get("def_archer", 0),
                carry=info.get("carry", 0),
                build_time=info.get("build_time", 0),
            )

        buildings = {}
        for name, info in building_data.items():
            buildings[name] = BuildingInfo(
                name=name,
                max_level=info.get("max_level", 30),
                min_level=info.get("min_level", 0),
                wood_factor=info.get("wood_factor", 1.0),
                stone_factor=info.get("stone_factor", 1.0),
                iron_factor=info.get("iron_factor", 1.0),
                pop_factor=info.get("pop_factor", 1.0),
                build_time_factor=info.get("build_time_factor", 1.0),
            )

        return WorldConfig(
            speed=config_data.get("speed", 1.0),
            unit_speed=config_data.get("unit_speed", 1.0),
            archer=bool(config_data.get("archer", 0)),
            church=bool(config_data.get("church", 0)),
            units=units,
            buildings=buildings,
        )

    async def fetch_barbarian_villages(
        self, center_x: int, center_y: int, radius: int
    ) -> list[dict]:
        """Fetch barbarian villages near a point from map data."""
        text = await self.browser.get_public_data("/map/village.txt")
        all_villages = parse_map_village_txt(text)

        barbarians = []
        for v in all_villages:
            if v["player_id"] != 0:
                continue
            dx = v["x"] - center_x
            dy = v["y"] - center_y
            if (dx * dx + dy * dy) ** 0.5 <= radius:
                barbarians.append(v)

        log.info("barbarians_found", count=len(barbarians), radius=radius)
        return barbarians
