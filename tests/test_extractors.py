"""Tests for game data extractors."""

from __future__ import annotations

import pytest

from staemme.core.extractors import (
    extract_csrf,
    extract_game_data,
    extract_h_param,
    extract_incoming_attacks,
    extract_resources,
    parse_map_village_txt,
    parse_world_config_xml,
    parse_unit_info_xml,
)
from staemme.core.exceptions import ExtractionError


class TestExtractGameData:
    def test_extract_from_update_call(self):
        html = """
        <script>
        TribalWars.updateGameData({"csrf":"abc123","village":{"id":12345,"name":"Test","x":400,"y":500}})
        </script>
        """
        data = extract_game_data(html)
        assert data["csrf"] == "abc123"
        assert data["village"]["id"] == 12345

    def test_extract_from_var_assignment(self):
        html = """
        <script>
        var game_data = {"csrf":"def456","village":{"id":99}};
        </script>
        """
        data = extract_game_data(html)
        assert data["csrf"] == "def456"

    def test_raises_on_missing_data(self):
        with pytest.raises(ExtractionError):
            extract_game_data("<html><body>No game data</body></html>")


class TestExtractCSRF:
    def test_extract_csrf_single_quotes(self):
        html = "var csrf = 'a1b2c3d4e5f6';"
        assert extract_csrf(html) == "a1b2c3d4e5f6"

    def test_extract_csrf_double_quotes(self):
        html = 'csrf: "deadbeef1234"'
        assert extract_csrf(html) == "deadbeef1234"

    def test_raises_on_missing(self):
        with pytest.raises(ExtractionError):
            extract_csrf("<html>nothing</html>")


class TestExtractHParam:
    def test_extract_from_url(self):
        html = '<a href="/game.php?village=123&screen=main&h=aabbccdd">'
        assert extract_h_param(html) == "aabbccdd"

    def test_raises_on_missing(self):
        with pytest.raises(ExtractionError):
            extract_h_param("<html>no links</html>")


class TestExtractResources:
    def test_extract_from_game_data(self):
        html = """
        <script>
        TribalWars.updateGameData({"village":{"wood":"1234","stone":"5678","iron":"9012"}})
        </script>
        <span id="wood">1.234</span>
        <span id="stone">5.678</span>
        <span id="iron">9.012</span>
        """
        res = extract_resources(html)
        assert res.wood == 1234
        assert res.stone == 5678
        assert res.iron == 9012


class TestExtractIncomingAttacks:
    def test_with_attacks(self):
        html = '<span id="incomings_amount">3</span>'
        assert extract_incoming_attacks(html) == 3

    def test_without_attacks(self):
        html = "<html><body>no attack info</body></html>"
        assert extract_incoming_attacks(html) == 0


class TestParseMapVillageTxt:
    def test_parse_villages(self):
        text = "123,Village1,400,500,0,100,1\n456,Village2,401,501,42,500,2\n"
        villages = parse_map_village_txt(text)
        assert len(villages) == 2
        assert villages[0]["id"] == 123
        assert villages[0]["player_id"] == 0  # barbarian
        assert villages[1]["player_id"] == 42  # owned

    def test_empty_input(self):
        assert parse_map_village_txt("") == []


class TestParseWorldConfigXml:
    def test_parse_config(self):
        xml = """<?xml version="1.0"?>
        <config>
            <speed>1.0</speed>
            <unit_speed>0.5</unit_speed>
            <archer>0</archer>
        </config>"""
        config = parse_world_config_xml(xml)
        assert config["speed"] == 1.0
        assert config["unit_speed"] == 0.5
        assert config["archer"] == 0


class TestParseUnitInfoXml:
    def test_parse_units(self):
        xml = """<?xml version="1.0"?>
        <config>
            <spear>
                <pop>1</pop>
                <speed>18.0</speed>
                <att>10</att>
                <def>15</def>
                <carry>25</carry>
            </spear>
            <light>
                <pop>4</pop>
                <speed>10.0</speed>
                <att>130</att>
                <carry>80</carry>
            </light>
        </config>"""
        units = parse_unit_info_xml(xml)
        assert "spear" in units
        assert units["spear"]["att"] == 10
        assert units["light"]["carry"] == 80
