from __future__ import annotations

import re
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


def _parse_effort_minutes(effort: str | None) -> int | None:
    if not effort:
        return None
    raw = effort.strip().lower()
    if not raw:
        return None
    m = re.match(r"^(\d+)\s*([a-z]+)?$", raw)
    if not m:
        return None
    val = int(m.group(1))
    unit = (m.group(2) or "m").strip()
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return max(5, val)
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return max(15, val * 60)
    return None


def _task_priority_weight(priority: str | None) -> int:
    p = (priority or "").strip().upper()
    if p == "P1":
        return 100
    if p == "P2":
        return 60
    if p == "P3":
        return 25
    return 0


def _task_score(
    task: TaskRow,
    *,
    today_d: date,
    end_d: date,
) -> int:
    score = _task_priority_weight(task.priority)
    due = task.due_date
    if due:
        days = (due - today_d).days
        if days < 0:
            score += 220 + min(60, abs(days) * 6)
        elif days == 0:
            score += 190
        elif days <= 2:
            score += 140
        elif days <= 7:
            score += 90
        elif due <= end_d:
            score += 45
    effort_minutes = _parse_effort_minutes(task.effort)
    # Prefer quick wins slightly when urgency is similar.
    if effort_minutes is not None:
        if effort_minutes <= 30:
            score += 12
        elif effort_minutes <= 90:
            score += 6
    return score


def _select_tasks_for_window(
    tasks: list[TaskRow],
    *,
    today_d: date,
    end_d: date,
) -> list[TaskRow]:
    filtered: list[TaskRow] = []
    for task in tasks:
        due = task.due_date
        if due is None:
            if _task_priority_weight(task.priority) >= 60:
                filtered.append(task)
            continue
        if due < today_d or (today_d <= due <= end_d):
            filtered.append(task)

    filtered.sort(
        key=lambda t: (
            -_task_score(t, today_d=today_d, end_d=end_d),
            t.due_date or date.max,
            (t.title or "").lower(),
        )
    )
    return filtered


def _parse_iso_datetime(value: str, *, tz: ZoneInfo) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _propose_time_blocks(
    *,
    tasks: list[TaskRow],
    events: list[dict],
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    availability: tuple[int, int] | None,
) -> list[str]:
    # Only propose when either availability is explicit or calendar data exists.
    if availability is None and not events:
        return []

    start_minutes, end_minutes = availability if availability else (9 * 60, 17 * 60)
    if end_minutes <= start_minutes:
        return []

    busy: list[tuple[datetime, datetime]] = []
    for event in events:
        if event.get("all_day"):
            dt = _parse_iso_datetime(str(event.get("start_ts") or ""), tz=tz)
            if not dt:
                continue
            day_start = datetime(dt.year, dt.month, dt.day, tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            busy.append((day_start, day_end))
            continue
        s = _parse_iso_datetime(str(event.get("start_ts") or ""), tz=tz)
        if not s:
            continue
        e = _parse_iso_datetime(str(event.get("end_ts") or ""), tz=tz) if event.get("end_ts") else None
        if not e or e <= s:
            e = s + timedelta(minutes=30)
        busy.append((s, e))

    slots: list[tuple[datetime, datetime, str]] = []
    day_cursor = datetime(start.year, start.month, start.day, tzinfo=tz)
    max_blocks = 8
    for task in tasks[:max_blocks]:
        effort_minutes = _parse_effort_minutes(task.effort) or 60
        effort_minutes = min(max(effort_minutes, 30), 180)
        placed = False
        day_try = day_cursor
        while day_try < end and not placed:
            day_start = day_try.replace(
                hour=start_minutes // 60, minute=start_minutes % 60, second=0, microsecond=0
            )
            day_end = day_try.replace(
                hour=end_minutes // 60, minute=end_minutes % 60, second=0, microsecond=0
            )
            candidate = day_start
            while candidate + timedelta(minutes=effort_minutes) <= day_end:
                c_end = candidate + timedelta(minutes=effort_minutes)
                clash = False
                for b_start, b_end in [*busy, *[(s, e) for s, e, _ in slots]]:
                    if _overlaps(candidate, c_end, b_start, b_end):
                        clash = True
                        break
                if not clash:
                    slots.append((candidate, c_end, task.title))
                    placed = True
                    break
                candidate += timedelta(minutes=15)
            day_try += timedelta(days=1)

    slots.sort(key=lambda item: item[0])
    lines: list[str] = []
    for s, e, title in slots:
        duration = int((e - s).total_seconds() // 60)
        lines.append(f"  - {s.strftime('%Y-%m-%d %H:%M')}-{e.strftime('%H:%M')}: {title} ({duration}m)")
    return lines


def build_plan(
    ws: Workspace,
    *,
    mode: str,
    availability: tuple[int, int] | None = None,
) -> Plan:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()

    prefs = load_preferences(ws.paths.preferences_yaml)
    tz = ZoneInfo(prefs.timezone) if prefs.timezone else ZoneInfo("UTC")
    start, end = _date_range(mode, tz)

    # Pull structured items.
    events = db.list_events_between(start_iso=start.isoformat(), end_iso=end.isoformat())
    deadlines = db.list_deadlines_between(start_iso=start.isoformat(), end_iso=end.isoformat())
    tasks = db.list_tasks(include_completed=False)

    # Expand recurring events within window.
    events = _expand_recurring_events(events=events, start=start, end=end, tz=tz)

    today_d = start.date()
    end_d = (end - timedelta(seconds=1)).date()
    filtered = _select_tasks_for_window(tasks, today_d=today_d, end_d=end_d)

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
            effort = t.effort or "-"
            lines.append(
                f"  - [{p}] {t.title} (due {due}, effort {effort}) — {t.source_path}#{t.source_anchor}"
            )

    block_lines = _propose_time_blocks(
        tasks=filtered,
        events=events,
        start=start,
        end=end,
        tz=tz,
        availability=availability,
    )
    if block_lines:
        lines.append("Draft Time Blocks:")
        lines.extend(block_lines)
    if not lines:
        lines.append("No tasks/events/deadlines found for this window.")

    return Plan(title=f"Plan ({mode})", lines=lines)


def _expand_recurring_events(*, start: datetime, end: datetime, tz: ZoneInfo, events):
    from dateutil import rrule

    expanded = []
    for e in events:
        row = dict(e) if hasattr(e, "keys") else dict(e)
        rule = row.get("recurrence_rule")
        if not rule:
            expanded.append(row)
            continue
        try:
            start_dt = datetime.fromisoformat(row["start_ts"])
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=tz)
            r = rrule.rrulestr(rule, dtstart=start_dt)
            for occ in r.between(start, end, inc=True):
                expanded.append(
                    {
                        **row,
                        "start_ts": occ.replace(microsecond=0).isoformat(),
                    }
                )
        except Exception:
            expanded.append(row)
    expanded.sort(key=lambda x: x.get("start_ts") or "")
    return expanded
