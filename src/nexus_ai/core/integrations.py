from __future__ import annotations

from dataclasses import dataclass

from nexus_ai.core.config import AppConfig, normalize_integration_mode


class IntegrationError(RuntimeError):
    pass


class IntegrationPermissionError(IntegrationError):
    pass


@dataclass(frozen=True)
class CapabilitySpec:
    integration: str
    capability: str
    description: str
    access: str  # read|write
    surface: str  # llm_tool|cli|future
    implemented: bool = True


@dataclass(frozen=True)
class CapabilityStatus:
    integration: str
    capability: str
    description: str
    access: str
    surface: str
    implemented: bool
    available: bool
    allowed: bool
    reason: str | None


CAPABILITY_SPECS: tuple[CapabilitySpec, ...] = (
    CapabilitySpec(
        integration="knowledge",
        capability="search",
        description="Search indexed Knowledge/ content.",
        access="read",
        surface="llm_tool",
    ),
    CapabilitySpec(
        integration="knowledge",
        capability="find_files",
        description="Find files by path substring in Knowledge/.",
        access="read",
        surface="llm_tool",
    ),
    CapabilitySpec(
        integration="knowledge",
        capability="list_files",
        description="List files under Knowledge/ recursively or scoped.",
        access="read",
        surface="llm_tool",
    ),
    CapabilitySpec(
        integration="knowledge",
        capability="read_file",
        description="Read a Knowledge/ file with optional character limit.",
        access="read",
        surface="llm_tool",
    ),
    CapabilitySpec(
        integration="calendar",
        capability="sync_events",
        description="Import events from configured calendars into Nexus.",
        access="read",
        surface="cli",
    ),
    CapabilitySpec(
        integration="calendar",
        capability="create_event",
        description="Create calendar events in provider APIs.",
        access="write",
        surface="cli",
    ),
    CapabilitySpec(
        integration="calendar",
        capability="update_event",
        description="Update calendar events in provider APIs.",
        access="write",
        surface="cli",
    ),
    CapabilitySpec(
        integration="calendar",
        capability="delete_event",
        description="Delete calendar events in provider APIs.",
        access="write",
        surface="cli",
    ),
    CapabilitySpec(
        integration="web",
        capability="search_web",
        description="Search the web and save sourced notes.",
        access="read",
        surface="future",
        implemented=False,
    ),
    CapabilitySpec(
        integration="email",
        capability="sync_threads",
        description="Read email threads into structured notes.",
        access="read",
        surface="future",
        implemented=False,
    ),
)


class IntegrationRegistry:
    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._mode = normalize_integration_mode(cfg.integrations.mode)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def writes_enabled(self) -> bool:
        return self._mode == "write_enabled"

    def list_capabilities(self) -> list[CapabilityStatus]:
        rows: list[CapabilityStatus] = []
        for spec in CAPABILITY_SPECS:
            available, reason = self._availability(spec)
            allowed = available and self._is_allowed(spec)
            if not available:
                allowed = False
            if available and not allowed and reason is None:
                reason = "Write operations are disabled (integrations.mode=read_only)."
            rows.append(
                CapabilityStatus(
                    integration=spec.integration,
                    capability=spec.capability,
                    description=spec.description,
                    access=spec.access,
                    surface=spec.surface,
                    implemented=spec.implemented,
                    available=available,
                    allowed=allowed,
                    reason=reason,
                )
            )
        return rows

    def allowed_llm_tools(self) -> set[str]:
        allowed: set[str] = set()
        for row in self.list_capabilities():
            if row.surface == "llm_tool" and row.allowed:
                allowed.add(row.capability)
        return allowed

    def require(self, integration: str, capability: str) -> None:
        for row in self.list_capabilities():
            if row.integration == integration and row.capability == capability:
                if row.allowed:
                    return
                if row.reason:
                    raise IntegrationPermissionError(row.reason)
                raise IntegrationPermissionError("Capability is not allowed.")
        raise IntegrationPermissionError(
            f"Unknown integration capability: {integration}.{capability}"
        )

    def _is_allowed(self, spec: CapabilitySpec) -> bool:
        if spec.access == "write" and not self.writes_enabled:
            return False
        return True

    def _availability(self, spec: CapabilitySpec) -> tuple[bool, str | None]:
        if not spec.implemented:
            return False, "Not implemented yet."
        if spec.integration == "calendar":
            if spec.capability == "sync_events":
                if self._cfg.calendar.google_enabled or self._cfg.calendar.ics_paths:
                    return True, None
                return False, "No calendar sources configured."
            if spec.capability in {"create_event", "update_event", "delete_event"}:
                if self._cfg.calendar.google_enabled:
                    return True, None
                return False, "Google Calendar is not enabled."
        return True, None

