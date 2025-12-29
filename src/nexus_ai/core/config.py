from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class LlmConfig:
    provider: str = "openrouter"
    model: str = "xiaomi/mimo-v2-flash:free"
    weak_model: str | None = "xiaomi/mimo-v2-flash:free"
    base_url: str | None = None
    api_key_env: str | None = None

    # Optional ingestion enrichment (enabled by default).
    enrich_enabled: bool = True
    enrich_max_chars: int = 12000


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
    llm_raw = data.get("llm", {}) or {}
    enrich_raw = llm_raw.get("enrich", {}) or {}
    llm = LlmConfig(
        provider=str(llm_raw.get("provider", LlmConfig().provider)),
        model=str(llm_raw.get("model", LlmConfig().model)),
        weak_model=llm_raw.get("weak_model"),
        base_url=llm_raw.get("base_url"),
        api_key_env=llm_raw.get("api_key_env"),
        enrich_enabled=bool(enrich_raw.get("enabled", LlmConfig().enrich_enabled)),
        enrich_max_chars=int(enrich_raw.get("max_chars", LlmConfig().enrich_max_chars)),
    )
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
        "llm": {
            "provider": LlmConfig().provider,
            "model": LlmConfig().model,
            "weak_model": LlmConfig().weak_model,
            "base_url": LlmConfig().base_url,
            "api_key_env": LlmConfig().api_key_env,
            "enrich": {
                "enabled": LlmConfig().enrich_enabled,
                "max_chars": LlmConfig().enrich_max_chars,
            },
        },
        "calendar": {"ics_paths": []},
        "integrations": {"mode": "read_only"},
    }


def resolve_llm_settings(llm: LlmConfig) -> dict[str, str | None]:
    provider = llm.provider.lower()
    model = llm.model

    if "/" not in model:
        if provider == "openrouter":
            model = f"openrouter/{model}"
        elif provider == "openai":
            model = f"openai/{model}"
        elif provider == "ollama":
            model = f"ollama/{model}"
    elif provider == "openrouter" and not model.startswith("openrouter/"):
        model = f"openrouter/{model}"

    api_key_env = llm.api_key_env
    if not api_key_env:
        if provider == "openrouter":
            api_key_env = "OPENROUTER_API_KEY"
        elif provider == "openai":
            api_key_env = "OPENAI_API_KEY"
        elif provider == "ollama":
            api_key_env = None

    base_url = llm.base_url
    if provider == "ollama" and not base_url:
        base_url = "http://localhost:11434"

    return {"model": model, "api_key_env": api_key_env, "base_url": base_url}


def default_preferences_dict() -> dict[str, Any]:
    return {
        "timezone": "UTC",
        "defaults": {"tags": []},
    }
