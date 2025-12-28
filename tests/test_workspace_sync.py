from pathlib import Path

from nexus_ai.core.workspace import Workspace
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.sync import sync_knowledge
from nexus_ai.core.db import NexusDb


def test_workspace_init_and_sync(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    note_path = ws.paths.knowledge_dir / "2_Areas" / "Home" / "Home.md"
    markdown = ensure_minimal_front_matter(
        "- [ ] File taxes due:2026-04-15 p:P1\n",
        doc_type="note",
        title="Home",
    )
    atomic_write_text(note_path, markdown)

    stats = sync_knowledge(ws)
    assert stats.indexed >= 1

    db = NexusDb(ws.paths.db_path)
    tasks = db.list_tasks(include_completed=True)
    assert len(tasks) == 1
    assert tasks[0].title.lower().startswith("file taxes")

