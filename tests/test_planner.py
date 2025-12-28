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
    markdown = ensure_minimal_front_matter(
        "- [ ] File taxes due:2026-04-15 p:P1\n",
        doc_type="note",
        title="Taxes",
    )
    atomic_write_text(note_path, markdown)

    sync_knowledge(ws)
    plan = build_plan(ws, mode="month")
    rendered = plan.render().plain
    assert "File taxes" in rendered

