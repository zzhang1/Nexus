from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nexus_ai.core.hashing import stable_id
from nexus_ai.core.markdown import split_front_matter
from nexus_ai.core.folder_profiles import infer_folder_defaults

TASK_RE = re.compile(r"^\s*[-*]\s+\[(?P<check>[ xX])\]\s+(?P<body>.+?)\s*$")


def _extract_token(body: str, token: str) -> tuple[str | None, str]:
    # token like "due:" or "p:" or "effort:" or "ctx:"
    m = re.search(rf"(^|\s){re.escape(token)}(?P<val>[^\s]+)", body)
    if not m:
        return None, body
    val = m.group("val")
    body2 = (body[: m.start()] + body[m.end() :]).strip()
    return val, body2


def _normalize_title(body: str) -> str:
    return re.sub(r"\s+", " ", body).strip()


def parse_tasks_from_markdown(
    *,
    markdown_text: str,
    source_path: Path,
    knowledge_root: Path,
) -> list[dict]:
    fm = split_front_matter(markdown_text).front_matter
    file_tags = fm.get("tags", []) if isinstance(fm.get("tags", []), list) else []
    file_tags = [str(t) for t in file_tags]
    folder_defaults = infer_folder_defaults(source_path, knowledge_root)
    inherited_tags = [t for t in folder_defaults.tags if t not in file_tags]
    tags = file_tags + inherited_tags

    tasks: list[dict] = []
    for i, line in enumerate(markdown_text.splitlines(), start=1):
        m = TASK_RE.match(line)
        if not m:
            continue
        checked = m.group("check").strip().lower() == "x"
        body = m.group("body")

        due, body = _extract_token(body, "due:")
        priority, body = _extract_token(body, "p:")
        effort, body = _extract_token(body, "effort:")
        _ctx, body = _extract_token(body, "ctx:")  # optional; stored later if needed

        title = _normalize_title(body)
        anchor = f"L{i}"
        task_id = stable_id(str(source_path), anchor, title)
        if due and "T" in due:
            due = due.split("T", 1)[0]
        tasks.append(
            {
                "id": task_id,
                "title": title,
                "status": "done" if checked else "open",
                "due_date": due,
                "priority": priority if priority and priority.upper().startswith("P") else None,
                "effort": effort,
                "tags": tags,
                "source_anchor": anchor,
                "created_ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "completed_ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                if checked
                else None,
            }
        )
    return tasks
