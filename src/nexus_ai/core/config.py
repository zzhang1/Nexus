from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class LlmConfig:
    model: str = "openrouter/anthropic/claude-3.5-sonnet"


@dataclass(frozen=True)
class CalendarConfig:
    ics_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppConfig:
    llm: LlmConfig = LlmConfig()
    calendar: CalendarConfig = CalendarConfig()


@dataclass(frozen=True)
class Preferences:
    timezone: str = "UTC"
    defaults_tags: tuple[str, ...] = ()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def load_config(config_path: Path) -> AppConfig:
    load_dotenv(override=False)
    data = load_yaml(config_path)
    llm = LlmConfig(model=(data.get("llm", {}) or {}).get("model", LlmConfig().model))
    calendar = CalendarConfig(ics_paths=tuple((data.get("calendar", {}) or {}).get("ics_paths", ()) or ()))
    return AppConfig(llm=llm, calendar=calendar)


def load_preferences(preferences_path: Path) -> Preferences:
    data = load_yaml(preferences_path)
    timezone = data.get("timezone", "UTC")
    defaults = data.get("defaults", {}) or {}
    tags = defaults.get("tags", []) or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags]
    return Preferences(timezone=str(timezone), defaults_tags=tuple(tags))


def default_config_dict() -> dict[str, Any]:
    return {
        "llm": {"model": LlmConfig().model},
        "calendar": {"ics_paths": []},
        "integrations": {"mode": "read_only"},
    }


def default_preferences_dict() -> dict[str, Any]:
    return {
        "timezone": "UTC",
        "defaults": {"tags": []},
    }

