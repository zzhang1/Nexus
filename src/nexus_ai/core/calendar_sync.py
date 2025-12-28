from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from icalendar import Calendar

from nexus_ai.core.config import load_config
from nexus_ai.core.db import NexusDb
from nexus_ai.core.hashing import stable_id
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class CalendarSyncResult:
    events_upserted: int


def _to_iso(dt) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    # date
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).isoformat()


def sync_calendars(ws: Workspace) -> CalendarSyncResult:
    ws.init_workspace()
    cfg = load_config(ws.paths.config_yaml)
    ics_paths = [Path(p).expanduser() for p in cfg.calendar.ics_paths]
    if not ics_paths:
        return CalendarSyncResult(events_upserted=0)

    events: list[dict] = []
    for p in ics_paths:
        if not p.exists():
            continue
        cal = Calendar.from_ical(p.read_bytes())
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("summary", "")).strip() or "Event"
            dtstart = component.get("dtstart").dt
            dtend = component.get("dtend").dt if component.get("dtend") else None
            uid = str(component.get("uid", "")) or stable_id(str(p), summary, _to_iso(dtstart))
            event_id = stable_id("ics", uid)
            events.append(
                {
                    "id": event_id,
                    "title": summary,
                    "start_ts": _to_iso(dtstart),
                    "end_ts": _to_iso(dtend) if dtend else None,
                    "timezone": None,
                    "all_day": not isinstance(dtstart, datetime),
                    "recurrence_rule": str(component.get("rrule")) if component.get("rrule") else None,
                    "source": "ics",
                    "source_id": uid,
                    "status": None,
                }
            )

    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    count = db.upsert_events(events)
    return CalendarSyncResult(events_upserted=count)

