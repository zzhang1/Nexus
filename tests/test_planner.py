from datetime import date, timedelta
from pathlib import Path

from nexus_ai.core.workspace import Workspace
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.sync import sync_knowledge
from nexus_ai.core.planner import build_plan


def test_build_plan_includes_tasks(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    note_path = ws.paths.knowledge_dir / "1_Projects" / "Taxes" / "Taxes.md"
    due = (date.today() + timedelta(days=5)).isoformat()
    markdown = ensure_minimal_front_matter(
        f"- [ ] File taxes due:{due} p:P1\n",
        doc_type="note",
        title="Taxes",
    )
    atomic_write_text(note_path, markdown)

    sync_knowledge(ws)
    plan_month = build_plan(ws, mode="month")
    assert "File taxes" in plan_month.render().plain
    plan_week = build_plan(ws, mode="week")
    assert "File taxes" in plan_week.render().plain


def test_build_plan_prioritizes_overdue_and_priority(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    today = date.today()
    overdue = (today - timedelta(days=2)).isoformat()
    upcoming = (today + timedelta(days=1)).isoformat()

    note_path = ws.paths.knowledge_dir / "1_Projects" / "Plan" / "Plan.md"
    markdown = ensure_minimal_front_matter(
        (
            f"- [ ] Low urgency task due:{upcoming} p:P3\n"
            f"- [ ] Overdue important task due:{overdue} p:P2 effort:30m\n"
        ),
        doc_type="note",
        title="Plan",
    )
    atomic_write_text(note_path, markdown)

    sync_knowledge(ws)
    plan = build_plan(ws, mode="week")
    rendered = plan.render().plain
    assert rendered.index("Overdue important task") < rendered.index("Low urgency task")


def test_time_blocks_require_calendar_or_availability(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    note_path = ws.paths.knowledge_dir / "2_Areas" / "Home" / "Home.md"
    markdown = ensure_minimal_front_matter(
        "- [ ] Plan furnace tune-up p:P1 effort:45m\n",
        doc_type="note",
        title="Home",
    )
    atomic_write_text(note_path, markdown)

    sync_knowledge(ws)

    no_window = build_plan(ws, mode="today")
    assert "Draft Time Blocks:" not in no_window.render().plain

    with_window = build_plan(ws, mode="today", availability=(9 * 60, 12 * 60))
    text = with_window.render().plain
    assert "Draft Time Blocks:" in text
    assert "Plan furnace tune-up" in text
