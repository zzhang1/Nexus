from pathlib import Path

from nexus_ai.core.tasks_parse import parse_tasks_from_markdown


def test_parse_tasks_inline():
    md = """
---
type: note
title: Tasks
created: 2025-12-28T00:00:00+00:00
updated: 2025-12-28T00:00:00+00:00
status: active
tags: [home]
---

- [ ] Repaint door p:P2 effort:2h
- [x] File taxes due:2026-04-15 p:P1
"""
    tasks = parse_tasks_from_markdown(
        markdown_text=md,
        source_path=Path("/tmp/Knowledge/2_Areas/Home/Home.md"),
        knowledge_root=Path("/tmp/Knowledge"),
    )
    assert len(tasks) == 2
    open_task = next(t for t in tasks if t["status"] == "open")
    done_task = next(t for t in tasks if t["status"] == "done")
    assert open_task["priority"] == "P2"
    assert open_task["effort"] == "2h"
    assert done_task["due_date"] == "2026-04-15"
    assert "home" in done_task["tags"]

