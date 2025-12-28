from __future__ import annotations

from datetime import datetime, timezone
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
    - recurrence: `rrule:` or `recurrence_rule:`
    """

    title = front_matter.get("title") if isinstance(front_matter.get("title"), str) else None
    doc_title = title or source_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    deadlines: list[dict[str, Any]] = []
    for key in ("due", "deadline"):
        if key in front_matter and isinstance(front_matter.get(key), str):
            due_ts = _parse_iso_like(front_matter[key])
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
    if isinstance(front_matter.get("scheduled"), str):
        start_val = front_matter.get("scheduled")
    elif isinstance(front_matter.get("start"), str):
        start_val = front_matter.get("start")

    if start_val:
        start_ts = _parse_iso_like(start_val)
        if start_ts:
            end_ts = _parse_iso_like(front_matter.get("end")) if isinstance(front_matter.get("end"), str) else None
            rr = None
            if isinstance(front_matter.get("rrule"), str):
                rr = front_matter.get("rrule")
            elif isinstance(front_matter.get("recurrence_rule"), str):
                rr = front_matter.get("recurrence_rule")
            events.append(
                {
                    "id": stable_id("event", source_path, "scheduled"),
                    "title": doc_title,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "timezone": None,
                    "all_day": "T" not in start_val,
                    "recurrence_rule": rr,
                    "source_path": source_path,
                    "source": "markdown",
                    "source_id": f"{source_path}:scheduled",
                    "status": None,
                }
            )

    return events, deadlines

