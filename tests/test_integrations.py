from pathlib import Path

import pytest

from nexus_ai.core.config import (
    AppConfig,
    CalendarConfig,
    IntegrationsConfig,
    load_config,
    parse_integration_mode,
    set_integrations_mode,
)
from nexus_ai.core.integrations import CapabilityStatus, IntegrationRegistry
from nexus_ai.core.workspace import Workspace


def _capability(
    rows: list[CapabilityStatus], *, integration: str, capability: str
) -> CapabilityStatus:
    for row in rows:
        if row.integration == integration and row.capability == capability:
            return row
    raise AssertionError(f"Missing capability: {integration}.{capability}")


def test_registry_defaults_to_read_only(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()
    cfg = load_config(ws.paths.config_yaml)
    registry = IntegrationRegistry(cfg)
    assert registry.mode == "read_only"
    assert "search" in registry.allowed_llm_tools()
    assert "read_file" in registry.allowed_llm_tools()


def test_calendar_write_gated_by_mode() -> None:
    cfg = AppConfig(
        calendar=CalendarConfig(google_enabled=True),
        integrations=IntegrationsConfig(mode="read_only"),
    )
    read_only_registry = IntegrationRegistry(cfg)
    create_status = _capability(
        read_only_registry.list_capabilities(),
        integration="calendar",
        capability="create_event",
    )
    assert create_status.available is True
    assert create_status.allowed is False
    assert "read_only" in str(create_status.reason)

    cfg_write = AppConfig(
        calendar=CalendarConfig(google_enabled=True),
        integrations=IntegrationsConfig(mode="write_enabled"),
    )
    write_registry = IntegrationRegistry(cfg_write)
    create_status_write = _capability(
        write_registry.list_capabilities(),
        integration="calendar",
        capability="create_event",
    )
    assert create_status_write.available is True
    assert create_status_write.allowed is True


def test_set_integrations_mode_round_trip(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()

    saved = set_integrations_mode(ws.paths.config_yaml, mode="write_enabled")
    assert saved == "write_enabled"
    cfg = load_config(ws.paths.config_yaml)
    assert cfg.integrations.mode == "write_enabled"

    saved = set_integrations_mode(ws.paths.config_yaml, mode="read_only")
    assert saved == "read_only"
    cfg = load_config(ws.paths.config_yaml)
    assert cfg.integrations.mode == "read_only"


def test_parse_integration_mode_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        parse_integration_mode("write_all")

