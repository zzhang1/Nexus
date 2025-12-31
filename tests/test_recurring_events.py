from datetime import datetime, timedelta
from pathlib import Path

from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.sync import sync_knowledge
from nexus_ai.core.workspace import Workspace
from nexus_ai.core.planner import build_plan


def test_recurring_event_expands_in_plan(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    start = datetime.now().replace(microsecond=0)
    front_matter = "\n".join(
        [
            "---",
            "type: event",
            "title: Gymnastics",
            f"start: {start.isoformat()}",
            'recurrence: "FREQ=DAILY;INTERVAL=1"',
            "duration: 1h",
            "---",
            "",
            "# Gymnastics",
        ]
    )
    note_path = ws.paths.knowledge_dir / "2_Areas" / "Personal" / "Gymnastics.md"
    atomic_write_text(note_path, front_matter + "\n")
    sync_knowledge(ws)

    plan = build_plan(ws, mode="week")
    rendered = plan.render().plain
    # Should include multiple occurrences within the week window.
    assert rendered.count("Gymnastics") >= 2
