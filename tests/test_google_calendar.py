import pytest

from nexus_ai.core.config import AppConfig, CalendarConfig, IntegrationsConfig
from nexus_ai.core.google_calendar import (
    GoogleCalendarError,
    _build_event_payload,
    _normalize_rrule,
    create_google_event,
    parse_event_ref,
)
from nexus_ai.core.workspace import Workspace


def test_parse_event_ref_from_source_id() -> None:
    calendar_id, event_id = parse_event_ref(
        source_id="primary:abc123",
        calendar_id=None,
        event_id=None,
    )
    assert calendar_id == "primary"
    assert event_id == "abc123"


def test_parse_event_ref_requires_inputs() -> None:
    with pytest.raises(GoogleCalendarError):
        parse_event_ref(source_id=None, calendar_id="primary", event_id=None)


def test_rrule_normalization() -> None:
    assert _normalize_rrule("FREQ=WEEKLY;BYDAY=MO") == "RRULE:FREQ=WEEKLY;BYDAY=MO"
    assert _normalize_rrule("RRULE:FREQ=DAILY") == "RRULE:FREQ=DAILY"
    assert _normalize_rrule("") is None


def test_build_event_payload_all_day_default_end() -> None:
    payload = _build_event_payload(
        title="Tax Day",
        start="2026-04-15",
        end=None,
        all_day=True,
        timezone_name=None,
        recurrence_rrule=None,
    )
    assert payload["summary"] == "Tax Day"
    assert payload["start"]["date"] == "2026-04-15"
    assert payload["end"]["date"] == "2026-04-16"


def test_build_event_payload_timed_with_timezone() -> None:
    payload = _build_event_payload(
        title="Call",
        start="2026-02-10T09:00:00-05:00",
        end="2026-02-10T09:30:00-05:00",
        all_day=False,
        timezone_name="America/New_York",
        recurrence_rrule="FREQ=WEEKLY;BYDAY=TU",
    )
    assert payload["start"]["dateTime"] == "2026-02-10T09:00:00-05:00"
    assert payload["start"]["timeZone"] == "America/New_York"
    assert payload["end"]["dateTime"] == "2026-02-10T09:30:00-05:00"
    assert payload["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]


def test_create_google_event_requires_write_mode(tmp_path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()
    cfg = AppConfig(
        calendar=CalendarConfig(google_enabled=True),
        integrations=IntegrationsConfig(mode="read_only"),
    )

    with pytest.raises(GoogleCalendarError, match="integrations.mode=read_only"):
        create_google_event(
            ws,
            cfg,
            calendar_id="primary",
            title="Focus",
            start="2026-02-10T09:00:00-05:00",
            end="2026-02-10T10:00:00-05:00",
            all_day=False,
            timezone_name=None,
            description=None,
            location=None,
            recurrence_rrule=None,
        )
