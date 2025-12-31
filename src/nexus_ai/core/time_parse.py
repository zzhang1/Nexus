from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from nexus_ai.core.hashing import stable_id


def _parse_iso_like(value: str) -> str | None:
    v = value.strip()
    if not v:
        return None
    try:
        if "T" in v:
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.replace(microsecond=0).isoformat()
        # Date only
        dt = datetime.fromisoformat(v + "T00:00:00")
        dt = dt.replace(tzinfo=timezone.utc, microsecond=0)
        return dt.isoformat()
    except Exception:
        return None


def _parse_time_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.replace(microsecond=0).isoformat()
    if isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time()).replace(tzinfo=timezone.utc, microsecond=0)
        return dt.isoformat()
    if isinstance(value, str):
        return _parse_iso_like(value)
    return None


def _parse_duration(value: str) -> timedelta | None:
    v = value.strip().lower()
    if not v:
        return None
    total = timedelta()
    import re

    for num, unit in re.findall(r"(\d+)\s*([dhm])", v):
        n = int(num)
        if unit == "d":
            total += timedelta(days=n)
        elif unit == "h":
            total += timedelta(hours=n)
        elif unit == "m":
            total += timedelta(minutes=n)
    return total if total != timedelta() else None


def parse_time_items_from_front_matter(
    front_matter: dict[str, Any],
    *,
    source_path: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Return (events, deadlines) extracted from front matter.

    Supported patterns:
    - deadlines: `due: YYYY-MM-DD` (or ISO datetime)
    - events: `scheduled:` or `start:` + optional `end:` (or ISO datetimes)
    - recurrence: `rrule:` or `recurrence_rule:` or `recurrence:`
    - duration: `duration:` (e.g., "1h", "90m", "2h30m")
    """

    title = front_matter.get("title") if isinstance(front_matter.get("title"), str) else None
    doc_title = title or source_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    deadlines: list[dict[str, Any]] = []
    for key in ("due", "deadline"):
        if key in front_matter:
            due_ts = _parse_time_value(front_matter.get(key))
            if due_ts:
                deadlines.append(
                    {
                        "id": stable_id("deadline", source_path, key),
                        "title": f"{doc_title} ({key})",
                        "due_ts": due_ts,
                        "timezone": None,
                        "source_path": source_path,
                        "source": "markdown",
                        "source_id": f"{source_path}:{key}",
                        "status": None,
                    }
                )

    events: list[dict[str, Any]] = []
    start_val = None
    if "scheduled" in front_matter:
        start_val = front_matter.get("scheduled")
    elif "start" in front_matter:
        start_val = front_matter.get("start")

    if start_val:
        start_ts = _parse_time_value(start_val)
        if start_ts:
            end_ts = _parse_time_value(front_matter.get("end"))
            if end_ts is None and isinstance(front_matter.get("duration"), str):
                dur = _parse_duration(front_matter.get("duration"))
                if dur:
                    start_dt = datetime.fromisoformat(start_ts)
                    end_ts = (start_dt + dur).replace(microsecond=0).isoformat()
            rr = None
            if isinstance(front_matter.get("rrule"), str):
                rr = front_matter.get("rrule")
            elif isinstance(front_matter.get("recurrence_rule"), str):
                rr = front_matter.get("recurrence_rule")
            elif isinstance(front_matter.get("recurrence"), str):
                rr = front_matter.get("recurrence")
            all_day = False
            if isinstance(start_val, str):
                all_day = "T" not in start_val
            elif isinstance(start_val, date) and not isinstance(start_val, datetime):
                all_day = True

            events.append(
                {
                    "id": stable_id("event", source_path, "scheduled"),
                    "title": doc_title,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "timezone": None,
                    "all_day": all_day,
                    "recurrence_rule": rr,
                    "source_path": source_path,
                    "source": "markdown",
                    "source_id": f"{source_path}:scheduled",
                    "status": None,
                }
            )

    return events, deadlines
