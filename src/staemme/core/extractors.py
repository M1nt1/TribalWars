"""HTML and JavaScript data extraction from game pages."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from xml.etree import ElementTree

from selectolax.parser import HTMLParser

from staemme.core.exceptions import ExtractionError
from staemme.core.logging import get_logger
from staemme.models.buildings import BuildQueue
from staemme.models.troops import TroopCounts
from staemme.models.village import Resources, Village

log = get_logger("extractor")

# JS variable patterns
GAME_DATA_PATTERN = re.compile(
    r"TribalWars\.updateGameData\((\{.*?\})\)", re.DOTALL
)
VILLAGE_DATA_PATTERN = re.compile(
    r"var\s+game_data\s*=\s*(\{.*?\});", re.DOTALL
)
PREMIUM_PATTERN = re.compile(r'"premium"\s*:\s*(true|false)')


def extract_game_data(html: str) -> dict[str, Any]:
    """Extract the game_data JS object from a page."""
    # Try TribalWars.updateGameData() first
    match = GAME_DATA_PATTERN.search(html)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try var game_data = {...}
    match = VILLAGE_DATA_PATTERN.search(html)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ExtractionError("Could not extract game_data from page")


def extract_csrf(html: str) -> str:
    """Extract CSRF token from page."""
    match = re.search(r"csrf['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]", html, re.IGNORECASE)
    if match:
        return match.group(1)
    raise ExtractionError("CSRF token not found")


def extract_h_param(html: str) -> str:
    """Extract action h parameter from page links."""
    match = re.search(r"[?&]h=([a-f0-9]+)", html)
    if match:
        return match.group(1)
    raise ExtractionError("h parameter not found")


def extract_village_list(html: str) -> list[dict[str, Any]]:
    """Extract list of owned villages from the overview page."""
    try:
        game_data = extract_game_data(html)
        # game_data.village contains current village info
        village = game_data.get("village", {})
        if village:
            return [village]
    except ExtractionError:
        pass

    # Fallback: parse the village list from the quick-switch dropdown
    parser = HTMLParser(html)
    villages: list[dict[str, Any]] = []
    for node in parser.css("#header_menu_bottom_relevant_villages a, #combined_table tr"):
        vid = node.attributes.get("data-village-id") or ""
        if vid.isdigit():
            villages.append({
                "id": int(vid),
                "name": node.text(strip=True),
            })
    return villages


def extract_resources(html: str) -> Resources:
    """Extract current resource amounts from page."""
    parser = HTMLParser(html)
    try:
        wood = _get_int(parser, "#wood")
        stone = _get_int(parser, "#stone")
        iron = _get_int(parser, "#iron")
        return Resources(wood=wood, stone=stone, iron=iron)
    except (ValueError, AttributeError):
        # Try from game_data
        game_data = extract_game_data(html)
        village = game_data.get("village", {})
        return Resources(
            wood=int(village.get("wood", 0)),
            stone=int(village.get("stone", 0)),
            iron=int(village.get("iron", 0)),
        )


def extract_building_levels(html: str) -> dict[str, int]:
    """Extract building levels from the HQ page."""
    parser = HTMLParser(html)
    buildings: dict[str, int] = {}
    # Rows have IDs like "main_buildrow_main", "main_buildrow_barracks"
    for row in parser.css("tr[id*='main_buildrow_']"):
        row_id = row.attributes.get("id", "")
        building_name = row_id.replace("main_buildrow_", "")
        # First td contains "GebäudenameStufe X"
        first_td = row.css_first("td")
        if first_td:
            td_text = first_td.text(strip=True)
            level_match = re.search(r"Stufe\s+(\d+)", td_text)
            if level_match:
                buildings[building_name] = int(level_match.group(1))
            elif "nicht vorhanden" in td_text:
                buildings[building_name] = 0
    return buildings


def extract_build_queue(html: str) -> list[BuildQueue]:
    """Extract current building queue entries with level and finish time."""
    parser = HTMLParser(html)
    queue: list[BuildQueue] = []
    for row in parser.css("#buildqueue tr"):
        tds = row.css("td")
        if len(tds) < 2:
            continue

        # Try to get building internal ID from the cancel link href (?id=main)
        building_id = ""
        cancel_link = row.css_first("a[href*='id=']")
        if cancel_link:
            href = cancel_link.attributes.get("href", "")
            id_match = re.search(r"[?&]id=(\w+)", href)
            if id_match:
                building_id = id_match.group(1)

        # Fallback: map German display name to internal ID
        if not building_id:
            name_text = tds[0].text(strip=True)
            building_id = _german_name_to_id(name_text)

        if not building_id:
            continue

        # Parse target level from second td (text like "Stufe 4")
        target_level = 0
        if len(tds) >= 2:
            level_text = tds[1].text(strip=True)
            level_match = re.search(r"(\d+)", level_text)
            if level_match:
                target_level = int(level_match.group(1))

        # Parse finish time from span with data-endtime attribute
        finish_time = None
        timer_span = row.css_first("span[data-endtime]")
        if timer_span:
            endtime_str = timer_span.attributes.get("data-endtime", "")
            if endtime_str.isdigit():
                finish_time = datetime.fromtimestamp(int(endtime_str))

        queue.append(BuildQueue(
            building=building_id,
            target_level=target_level,
            finish_time=finish_time,
        ))
    return queue


# German display name -> internal building ID mapping
_GERMAN_TO_ID: dict[str, str] = {
    "Hauptgebäude": "main",
    "Kaserne": "barracks",
    "Stall": "stable",
    "Werkstatt": "garage",
    "Wachturm": "watchtower",
    "Adelshof": "snob",
    "Schmiede": "smith",
    "Versammlungsplatz": "place",
    "Standbild": "statue",
    "Marktplatz": "market",
    "Holzfäller": "wood",
    "Lehmgrube": "stone",
    "Eisenmine": "iron",
    "Bauernhof": "farm",
    "Speicher": "storage",
    "Versteck": "hide",
    "Wall": "wall",
}


def _german_name_to_id(display_name: str) -> str:
    """Map a German building display name to its internal ID."""
    # Exact match first
    if display_name in _GERMAN_TO_ID:
        return _GERMAN_TO_ID[display_name]
    # Try partial match (display name may include level info)
    for german, internal in _GERMAN_TO_ID.items():
        if german in display_name:
            return internal
    return ""


def extract_troop_counts(html: str) -> TroopCounts:
    """Extract troop counts from a page (rally point, barracks, etc.)."""
    parser = HTMLParser(html)
    counts: dict[str, int] = {}

    # Try units_entry_all_X elements (rally point) - text is like "(5)" or "(0)"
    for unit_type in [
        "spear", "sword", "axe", "archer", "spy",
        "light", "marcher", "heavy", "ram", "catapult",
        "knight", "snob",
    ]:
        node = parser.css_first(f"#units_entry_all_{unit_type}")
        if node:
            text = node.text(strip=True).strip("()")
            text = text.replace(".", "").replace(",", "")
            try:
                counts[unit_type] = int(text)
            except ValueError:
                continue

    # Fallback: try unit-item cells with data-unit-count attribute
    if not counts:
        for cell in parser.css("td.unit-item[data-unit-count]"):
            cls = cell.attributes.get("class", "")
            unit_match = re.search(r"unit-item-(\w+)", cls)
            if unit_match:
                unit = unit_match.group(1)
                try:
                    counts[unit] = int(cell.attributes.get("data-unit-count", "0"))
                except ValueError:
                    continue

    # Fallback: scavenge page uses a.units-entry-all[data-unit] with text "(N)"
    if not counts:
        for a_tag in parser.css("a.units-entry-all[data-unit]"):
            unit = a_tag.attributes.get("data-unit", "")
            if not unit:
                continue
            text = a_tag.text(strip=True).strip("()")
            text = text.replace(".", "").replace(",", "")
            try:
                counts[unit] = int(text)
            except ValueError:
                continue

    return TroopCounts(counts=counts)


def extract_scavenge_options(html: str) -> list[dict[str, Any]]:
    """Extract scavenge tier information from the scavenge page."""
    parser = HTMLParser(html)
    options: list[dict[str, Any]] = []

    for idx, option in enumerate(parser.css(".scavenge-option"), start=1):
        # Tier from data-option-id if present, otherwise positional (1-based)
        tier_id = option.attributes.get("data-option-id", "")
        tier = int(tier_id) if tier_id.isdigit() else idx

        has_locked_view = option.css_first(".locked-view") is not None
        running = option.css_first(".return-countdown") is not None
        has_send_button = option.css_first("a.free_send_button") is not None

        # An option is locked if it has .locked-view OR if it has no Start
        # button and isn't currently running (i.e. it's still unlocking)
        locked = has_locked_view or (not has_send_button and not running)

        options.append({
            "tier": tier,
            "locked": locked,
            "running": running,
        })
    return options


def extract_farm_targets(html: str) -> list[dict[str, Any]]:
    """Extract farm assistant target list."""
    parser = HTMLParser(html)
    targets: list[dict[str, Any]] = []

    for row in parser.css("#am_widget_Farm .farm_icon_wrap, #plunder_list tr"):
        target_id = row.attributes.get("data-id", "")
        if target_id.isdigit():
            targets.append({
                "id": int(target_id),
                "distance": row.attributes.get("data-distance", "0"),
            })
    return targets


def extract_incoming_attacks(html: str) -> int:
    """Extract count of incoming attacks from the page."""
    parser = HTMLParser(html)
    attack_node = parser.css_first("#incomings_amount, .icon-menu-attacks .menuCount")
    if attack_node:
        text = attack_node.text(strip=True)
        try:
            return int(text)
        except ValueError:
            return 0
    return 0


def parse_map_village_txt(text: str) -> list[dict[str, Any]]:
    """Parse /map/village.txt CSV data.
    Format: village_id, name, x, y, player_id, points, rank
    """
    villages: list[dict[str, Any]] = []
    for line in text.strip().split("\n"):
        parts = line.split(",")
        if len(parts) >= 6:
            villages.append({
                "id": int(parts[0]),
                "name": parts[1],
                "x": int(parts[2]),
                "y": int(parts[3]),
                "player_id": int(parts[4]),
                "points": int(parts[5]),
            })
    return villages


def parse_world_config_xml(xml_text: str) -> dict[str, Any]:
    """Parse /interface.php?func=get_config XML response."""
    root = ElementTree.fromstring(xml_text)
    config: dict[str, Any] = {}
    for child in root:
        if child.text is not None:
            try:
                config[child.tag] = float(child.text) if "." in child.text else int(child.text)
            except ValueError:
                config[child.tag] = child.text
    return config


def parse_unit_info_xml(xml_text: str) -> dict[str, dict[str, Any]]:
    """Parse /interface.php?func=get_unit_info XML response."""
    root = ElementTree.fromstring(xml_text)
    units: dict[str, dict[str, Any]] = {}
    for unit in root:
        unit_data: dict[str, Any] = {}
        for prop in unit:
            if prop.text is not None:
                try:
                    unit_data[prop.tag] = (
                        float(prop.text) if "." in prop.text else int(prop.text)
                    )
                except ValueError:
                    unit_data[prop.tag] = prop.text
        units[unit.tag] = unit_data
    return units


def parse_building_info_xml(xml_text: str) -> dict[str, dict[str, Any]]:
    """Parse /interface.php?func=get_building_info XML response."""
    root = ElementTree.fromstring(xml_text)
    buildings: dict[str, dict[str, Any]] = {}
    for building in root:
        data: dict[str, Any] = {}
        for prop in building:
            if prop.text is not None:
                try:
                    data[prop.tag] = (
                        float(prop.text) if "." in prop.text else int(prop.text)
                    )
                except ValueError:
                    data[prop.tag] = prop.text
        buildings[building.tag] = data
    return buildings


def _get_int(parser: HTMLParser, selector: str) -> int:
    """Extract an integer from a CSS selector's text content."""
    node = parser.css_first(selector)
    if node is None:
        raise ValueError(f"Selector {selector} not found")
    text = node.text(strip=True).replace(".", "").replace(",", "")
    return int(text)
