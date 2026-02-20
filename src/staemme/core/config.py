"""Configuration management with Pydantic models and TOML loading."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    world: str = "de220"


class BrowserConfig(BaseModel):
    headless_mode: Literal["headed", "headless", "xvfb"] = "headed"
    viewport_width: int = 1280
    viewport_height: int = 720


class BotConfig(BaseModel):
    active_hours: str = "06:00-23:00"
    active_delay: tuple[int, int] = (120, 300)
    inactive_delay: tuple[int, int] = (600, 1200)


class BuildingConfig(BaseModel):
    enabled: bool = True
    template: str = "templates/offensive.toml"


class FarmTemplate(BaseModel):
    spear: int = 0
    sword: int = 0
    axe: int = 0
    archer: int = 0
    light: int = 0
    heavy: int = 0
    ram: int = 0
    catapult: int = 0
    knight: int = 0
    snob: int = 0


class FarmingConfig(BaseModel):
    enabled: bool = True
    radius: int = 15
    template_a: FarmTemplate = Field(default_factory=lambda: FarmTemplate(spear=10, light=5))
    template_b: FarmTemplate = Field(
        default_factory=lambda: FarmTemplate(spear=25, sword=15, light=10, ram=2)
    )
    stop_on_attack: bool = True
    min_reserve: dict[str, int] = Field(default_factory=lambda: {"spear": 50})
    lc_threshold: int = 20  # max LC per attack before falling back to Template A


class ScavengingConfig(BaseModel):
    enabled: bool = True
    mode: str = "time_based"  # time_based | max_efficiency | send_all | ratio
    target_minutes: int = 120
    option_ratios: dict[int, float] = Field(
        default_factory=lambda: {1: 2.5, 2: 1.0}
    )
    dry_run: bool = False
    scavenge_exclude: list[str] = Field(
        default_factory=lambda: ["spear", "sword", "axe", "archer", "light", "marcher", "heavy"]
    )  # ALL excluded by default — user enables from panel
    scavenge_reserve: dict[str, int] = Field(default_factory=dict)


class TroopsConfig(BaseModel):
    enabled: bool = True
    mode: str = "targets"  # targets | fill_scavenge
    fill_units: list[str] = Field(default_factory=lambda: ["spear"])
    targets: dict[str, int] = Field(
        default_factory=lambda: {"spear": 500, "sword": 300, "light": 200, "ram": 50}
    )


class HumanizerConfig(BaseModel):
    delay_range: tuple[float, float] = (3.0, 8.0)
    jitter_factor: float = 0.3
    long_pause_chance: float = 0.05
    long_pause_range: tuple[float, float] = (15.0, 45.0)


class TelegramConfig(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
    alert_cooldown: int = 300


class BotProtectionConfig(BaseModel):
    check_interval: int = 30
    extra_selectors: list[str] = Field(default_factory=list)


class VillageOverride(BaseModel):
    """Per-village feature overrides. None = inherit global setting."""

    building: bool | None = None
    farming: bool | None = None
    scavenging: bool | None = None
    troops: bool | None = None


class APIConfig(BaseModel):
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8000


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    building: BuildingConfig = Field(default_factory=BuildingConfig)
    farming: FarmingConfig = Field(default_factory=FarmingConfig)
    scavenging: ScavengingConfig = Field(default_factory=ScavengingConfig)
    troops: TroopsConfig = Field(default_factory=TroopsConfig)
    humanizer: HumanizerConfig = Field(default_factory=HumanizerConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    bot_protection: BotProtectionConfig = Field(default_factory=BotProtectionConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    village_overrides: dict[int, VillageOverride] = Field(default_factory=dict)


def is_feature_enabled(config: AppConfig, village_id: int, feature: str) -> bool:
    """Resolve whether a feature is enabled for a specific village.

    Checks per-village override first; falls back to global config.
    """
    override = config.village_overrides.get(village_id)
    if override:
        val = getattr(override, feature, None)
        if val is not None:
            return val
    # Fall back to global
    section = getattr(config, feature, None)
    if section and hasattr(section, "enabled"):
        return section.enabled
    return False


def load_config(path: Path) -> AppConfig:
    """Load configuration from a TOML file, falling back to defaults."""
    if not path.exists():
        return AppConfig()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return AppConfig(**data)


def load_building_template(path: Path) -> dict[str, int]:
    """Load a building order template. Returns {building_name: target_level}."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data.get("buildings", {})


def save_config(config: AppConfig, path: Path) -> None:
    """Save configuration to TOML format."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def _to_toml_section(key: str, obj: dict[str, Any]) -> str:
        lines = [f"[{key}]"]
        for k, v in obj.items():
            if isinstance(v, dict):
                continue  # handled separately
            elif isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, tuple):
                lines.append(f"{k} = [{', '.join(str(x) for x in v)}]")
            else:
                lines.append(f"{k} = {v}")
        return "\n".join(lines)

    sections: list[str] = []
    for section_name, section_model in config:
        if isinstance(section_model, BaseModel):
            data = section_model.model_dump()
            sections.append(_to_toml_section(section_name, data))
            # Handle nested dicts
            for k, v in data.items():
                if isinstance(v, dict):
                    inner = ", ".join(
                        f'{ik} = {iv}' if isinstance(iv, (int, float))
                        else f'{ik} = "{iv}"'
                        for ik, iv in v.items()
                    )
                    sections[-1] += f"\n{k} = {{{inner}}}"

    path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
