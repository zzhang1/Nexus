from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from rich.text import Text

from nexus_ai.core.config import load_preferences
from nexus_ai.core.db import NexusDb, TaskRow
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class Plan:
    title: str
    lines: list[str]

    def render(self) -> Text:
        t = Text()
        t.append(self.title + "\n", style="bold")
        for line in self.lines:
            t.append(line + "\n")
        return t


def _date_range(mode: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    now = datetime.now(tz)
    start = datetime(now.year, now.month, now.day, tzinfo=tz)
    if mode == "today":
        end = start + timedelta(days=1)
    elif mode == "week":
        end = start + timedelta(days=7)
    elif mode == "month":
        end = start + timedelta(days=30)
    else:
        end = start + timedelta(days=7)
    return start, end


def list_tasks(ws: Workspace, *, include_completed: bool) -> list[TaskRow]:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    return db.list_tasks(include_completed=include_completed)


def build_plan(ws: Workspace, *, mode: str) -> Plan:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()

    prefs = load_preferences(ws.paths.preferences_yaml)
    tz = ZoneInfo(prefs.timezone) if prefs.timezone else ZoneInfo("UTC")
    start, end = _date_range(mode, tz)

    # Pull structured items.
    events = db.list_events_between(start_iso=start.isoformat(), end_iso=end.isoformat())
    deadlines = db.list_deadlines_between(start_iso=start.isoformat(), end_iso=end.isoformat())
    tasks = db.list_tasks(include_completed=False)

    # Filter tasks by due window if due_date exists; also include overdue and P1s.
    today_d = start.date()
    end_d = (end - timedelta(seconds=1)).date()
    filtered: list[TaskRow] = []
    for t in tasks:
        if t.due_date is None:
            if t.priority == "P1":
                filtered.append(t)
            continue
        if t.due_date < today_d or (today_d <= t.due_date <= end_d):
            filtered.append(t)

    lines: list[str] = []
    if events:
        lines.append("Events:")
        for e in events:
            lines.append(f"  - {e['start_ts']}: {e['title']}")
    if deadlines:
        lines.append("Deadlines:")
        for d in deadlines:
            lines.append(f"  - {d['due_ts']}: {d['title']}")
    if filtered:
        lines.append("Tasks:")
        for t in filtered:
            due = t.due_date.isoformat() if t.due_date else "-"
            p = t.priority or "-"
            lines.append(f"  - [{p}] {t.title} (due {due}) — {t.source_path}#{t.source_anchor}")
    if not lines:
        lines.append("No tasks/events/deadlines found for this window.")

    return Plan(title=f"Plan ({mode})", lines=lines)

