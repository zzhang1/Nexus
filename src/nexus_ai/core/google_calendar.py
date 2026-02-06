from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nexus_ai.core.config import AppConfig
from nexus_ai.core.db import NexusDb
from nexus_ai.core.hashing import stable_id
from nexus_ai.core.integrations import IntegrationPermissionError, IntegrationRegistry
from nexus_ai.core.tool_audit import write_action_audit
from nexus_ai.core.workspace import Workspace


SCOPES_READONLY = [
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
]

SCOPES_WRITE = [
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleCalendarError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleCalendarSyncResult:
    events_upserted: int


@dataclass(frozen=True)
class GoogleCalendarWriteResult:
    calendar_id: str
    event_id: str
    source_id: str
    status: str


def _require_google_deps() -> None:
    try:
        import google  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional dependency
        raise GoogleCalendarError(
            "Google Calendar dependencies missing. Install with: pip install .[gcal]"
        ) from exc


def _resolve_secrets_path(ws: Workspace, cfg: AppConfig) -> Path:
    raw = cfg.calendar.google_client_secrets_path
    if raw:
        return Path(raw).expanduser()
    return ws.paths.assistant_dir / "google_client_secrets.json"


def _resolve_token_path(ws: Workspace, cfg: AppConfig) -> Path:
    raw = cfg.calendar.google_token_path
    if raw:
        return Path(raw).expanduser()
    return ws.paths.assistant_dir / "google_calendar_token.json"


def _load_sync_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"calendars": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"calendars": {}}
    if not isinstance(data, dict):
        return {"calendars": {}}
    data.setdefault("calendars", {})
    return data


def _write_sync_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def authorize_google_calendar(
    ws: Workspace,
    cfg: AppConfig,
    *,
    write_access: bool = False,
) -> Path:
    _require_google_deps()
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets_path = _resolve_secrets_path(ws, cfg)
    if not secrets_path.exists():
        raise GoogleCalendarError(
            f"Client secrets file not found: {secrets_path}. "
            "Set calendar.google.client_secrets_path in config.yaml."
        )

    scopes = SCOPES_WRITE if write_access else SCOPES_READONLY
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes=scopes)
    try:
        creds = flow.run_local_server(port=0)
    except Exception:  # pragma: no cover - interactive
        creds = flow.run_console()

    token_path = _resolve_token_path(ws, cfg)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return token_path


def _load_credentials(ws: Workspace, cfg: AppConfig, *, write_access: bool = False):
    _require_google_deps()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = _resolve_token_path(ws, cfg)
    if not token_path.exists():
        raise GoogleCalendarError(
            "Google Calendar token not found. Run `nexus calendar auth` first."
        )

    scopes = SCOPES_WRITE if write_access else SCOPES_READONLY
    creds = Credentials.from_authorized_user_file(str(token_path), scopes=scopes)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        raise GoogleCalendarError("Google Calendar credentials are invalid or expired.")
    return creds


def _build_service(credentials):
    _require_google_deps()
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _event_row(calendar_id: str, event: dict[str, Any]) -> dict[str, Any]:
    start = event.get("start", {}) or {}
    end = event.get("end", {}) or {}
    start_dt = start.get("dateTime") or start.get("date")
    end_dt = end.get("dateTime") or end.get("date")
    all_day = bool(start.get("date")) and not start.get("dateTime")
    tz = start.get("timeZone") or event.get("timeZone")
    recurrence = event.get("recurrence") or []
    rule = None
    for r in recurrence:
        if isinstance(r, str) and r.startswith("RRULE:"):
            rule = r.replace("RRULE:", "", 1)
            break

    event_id = str(event.get("id") or "")
    return {
        "id": stable_id("google", calendar_id, event_id),
        "title": str(event.get("summary") or "Event"),
        "start_ts": _to_iso(start_dt),
        "end_ts": _to_iso(end_dt) if end_dt else None,
        "timezone": tz,
        "all_day": bool(all_day),
        "recurrence_rule": rule,
        "source_path": None,
        "source": "google",
        "source_id": f"{calendar_id}:{event_id}",
        "status": event.get("status"),
    }


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat()
    return str(value)


def parse_event_ref(
    *,
    source_id: str | None,
    calendar_id: str | None,
    event_id: str | None,
) -> tuple[str, str]:
    if source_id:
        parts = source_id.split(":", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
        raise GoogleCalendarError(
            f"Invalid source_id {source_id!r}. Expected format: <calendar_id>:<event_id>."
        )

    cal = (calendar_id or "").strip()
    ev = (event_id or "").strip()
    if not cal or not ev:
        raise GoogleCalendarError("Provide either --source-id or both --calendar-id and --event-id.")
    return cal, ev


def _normalize_rrule(rrule: str | None) -> str | None:
    if not rrule:
        return None
    value = rrule.strip()
    if not value:
        return None
    if value.startswith("RRULE:"):
        return value
    return f"RRULE:{value}"


def _next_day(yyyy_mm_dd: str) -> str:
    parsed = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").date()
    return (parsed + timedelta(days=1)).isoformat()


def _build_event_payload(
    *,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    all_day: bool | None = None,
    timezone_name: str | None = None,
    description: str | None = None,
    location: str | None = None,
    recurrence_rrule: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if title is not None:
        body["summary"] = title
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if status is not None:
        body["status"] = status

    if start is not None:
        is_all_day = bool(all_day)
        if is_all_day:
            body["start"] = {"date": start}
            if end is not None:
                body["end"] = {"date": end}
            else:
                body["end"] = {"date": _next_day(start)}
        else:
            body["start"] = {"dateTime": start}
            if timezone_name:
                body["start"]["timeZone"] = timezone_name
            if end is not None:
                body["end"] = {"dateTime": end}
                if timezone_name:
                    body["end"]["timeZone"] = timezone_name

    normalized_rrule = _normalize_rrule(recurrence_rrule)
    if normalized_rrule:
        body["recurrence"] = [normalized_rrule]
    return body


def _require_calendar_write_capability(cfg: AppConfig, capability: str) -> None:
    registry = IntegrationRegistry(cfg)
    try:
        registry.require("calendar", capability)
    except IntegrationPermissionError as exc:
        raise GoogleCalendarError(str(exc)) from exc


def sync_google_calendars(ws: Workspace, cfg: AppConfig) -> GoogleCalendarSyncResult:
    if not cfg.calendar.google_enabled:
        return GoogleCalendarSyncResult(events_upserted=0)

    creds = _load_credentials(ws, cfg)
    service = _build_service(creds)

    calendar_ids = list(cfg.calendar.google_calendar_ids or ())
    if not calendar_ids:
        calendar_ids = ["primary"]

    now = datetime.now(timezone.utc)
    time_min = now - timedelta(days=cfg.calendar.google_sync_past_days)
    time_max = now + timedelta(days=cfg.calendar.google_sync_future_days)

    sync_state_path = ws.paths.assistant_dir / "google_calendar_sync.json"
    sync_state = _load_sync_state(sync_state_path)
    cal_state = sync_state.setdefault("calendars", {})

    all_events: list[dict[str, Any]] = []
    for cal_id in calendar_ids:
        state = cal_state.get(cal_id, {}) if isinstance(cal_state.get(cal_id), dict) else {}
        sync_token = state.get("sync_token")
        time_min_iso = state.get("time_min") or time_min.isoformat()
        time_max_iso = state.get("time_max") or time_max.isoformat()

        params = {
            "calendarId": cal_id,
            "singleEvents": True,
            "showDeleted": True,
            "maxResults": 2500,
        }
        if sync_token:
            params["syncToken"] = sync_token
            params["timeMin"] = time_min_iso
            params["timeMax"] = time_max_iso
        else:
            params["timeMin"] = time_min_iso
            params["timeMax"] = time_max_iso

        events: list[dict[str, Any]] = []
        next_page = None
        try:
            while True:
                if next_page:
                    params["pageToken"] = next_page
                feed = service.events().list(**params).execute()
                items = feed.get("items", [])
                for item in items:
                    if item.get("status") == "cancelled":
                        events.append(_event_row(cal_id, item))
                        continue
                    events.append(_event_row(cal_id, item))
                next_page = feed.get("nextPageToken")
                if not next_page:
                    next_sync = feed.get("nextSyncToken")
                    if next_sync:
                        cal_state[cal_id] = {
                            "sync_token": next_sync,
                            "time_min": time_min_iso,
                            "time_max": time_max_iso,
                            "last_sync": now.isoformat(),
                        }
                    break
        except Exception as exc:
            message = str(exc)
            if "Sync token is no longer valid" in message or "410" in message:
                cal_state.pop(cal_id, None)
                return sync_google_calendars(ws, cfg)
            raise GoogleCalendarError(f"Google Calendar sync failed: {exc}") from exc

        all_events.extend(events)

    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    count = db.upsert_events(all_events)
    _write_sync_state(sync_state_path, sync_state)
    return GoogleCalendarSyncResult(events_upserted=count)


def create_google_event(
    ws: Workspace,
    cfg: AppConfig,
    *,
    calendar_id: str,
    title: str,
    start: str,
    end: str | None,
    all_day: bool,
    timezone_name: str | None,
    description: str | None,
    location: str | None,
    recurrence_rrule: str | None,
) -> GoogleCalendarWriteResult:
    if not cfg.calendar.google_enabled:
        raise GoogleCalendarError("Google Calendar is disabled in config (calendar.google.enabled=false).")
    _require_calendar_write_capability(cfg, "create_event")

    creds = _load_credentials(ws, cfg, write_access=True)
    service = _build_service(creds)
    payload = _build_event_payload(
        title=title,
        start=start,
        end=end,
        all_day=all_day,
        timezone_name=timezone_name,
        description=description,
        location=location,
        recurrence_rrule=recurrence_rrule,
    )
    created = service.events().insert(calendarId=calendar_id, body=payload).execute()
    row = _event_row(calendar_id, created)
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    db.upsert_events([row])
    write_action_audit(
        ws,
        action_type="calendar_write",
        payload={
            "operation": "create_event",
            "calendar_id": calendar_id,
            "source_id": row["source_id"],
            "request": payload,
            "response_status": created.get("status"),
        },
    )
    return GoogleCalendarWriteResult(
        calendar_id=calendar_id,
        event_id=str(created.get("id") or ""),
        source_id=row["source_id"],
        status=str(created.get("status") or "confirmed"),
    )


def update_google_event(
    ws: Workspace,
    cfg: AppConfig,
    *,
    calendar_id: str,
    event_id: str,
    title: str | None,
    start: str | None,
    end: str | None,
    clear_end: bool,
    all_day: bool | None,
    timezone_name: str | None,
    description: str | None,
    clear_description: bool,
    location: str | None,
    clear_location: bool,
    recurrence_rrule: str | None,
    clear_recurrence: bool,
    status: str | None,
) -> GoogleCalendarWriteResult:
    if not cfg.calendar.google_enabled:
        raise GoogleCalendarError("Google Calendar is disabled in config (calendar.google.enabled=false).")
    _require_calendar_write_capability(cfg, "update_event")

    creds = _load_credentials(ws, cfg, write_access=True)
    service = _build_service(creds)
    payload = _build_event_payload(
        title=title,
        start=start,
        end=end,
        all_day=all_day,
        timezone_name=timezone_name,
        description=description,
        location=location,
        recurrence_rrule=recurrence_rrule,
        status=status,
    )
    if clear_end:
        start_payload = payload.get("start")
        if not isinstance(start_payload, dict):
            raise GoogleCalendarError("`--clear-end` requires `--start`.")
        if "date" in start_payload:
            payload["end"] = {"date": _next_day(str(start_payload["date"]))}
        else:
            raise GoogleCalendarError("Cannot clear end for timed events. Provide `--end`.")
    if clear_description:
        payload["description"] = ""
    if clear_location:
        payload["location"] = ""
    if clear_recurrence:
        payload["recurrence"] = []
    if not payload:
        raise GoogleCalendarError("No updates specified.")

    updated = service.events().patch(
        calendarId=calendar_id,
        eventId=event_id,
        body=payload,
    ).execute()
    row = _event_row(calendar_id, updated)
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    db.upsert_events([row])
    write_action_audit(
        ws,
        action_type="calendar_write",
        payload={
            "operation": "update_event",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "source_id": row["source_id"],
            "request": payload,
            "response_status": updated.get("status"),
        },
    )
    return GoogleCalendarWriteResult(
        calendar_id=calendar_id,
        event_id=event_id,
        source_id=row["source_id"],
        status=str(updated.get("status") or "confirmed"),
    )


def delete_google_event(
    ws: Workspace,
    cfg: AppConfig,
    *,
    calendar_id: str,
    event_id: str,
) -> GoogleCalendarWriteResult:
    if not cfg.calendar.google_enabled:
        raise GoogleCalendarError("Google Calendar is disabled in config (calendar.google.enabled=false).")
    _require_calendar_write_capability(cfg, "delete_event")

    creds = _load_credentials(ws, cfg, write_access=True)
    service = _build_service(creds)
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    source_id = f"{calendar_id}:{event_id}"
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    db.mark_event_cancelled(source="google", source_id=source_id)
    write_action_audit(
        ws,
        action_type="calendar_write",
        payload={
            "operation": "delete_event",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "source_id": source_id,
        },
    )
    return GoogleCalendarWriteResult(
        calendar_id=calendar_id,
        event_id=event_id,
        source_id=source_id,
        status="cancelled",
    )
