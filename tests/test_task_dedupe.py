from pathlib import Path

from nexus_ai.core.agent_actions import apply_actions
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.workspace import Workspace


def test_duplicate_task_is_noop(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    note_path = ws.paths.knowledge_dir / "2_Areas" / "Home" / "Maintenance.md"
    markdown = ensure_minimal_front_matter(
        "- [ ] Replace porch light due:2026-02-28 p:P2\n",
        doc_type="note",
        title="Maintenance",
    )
    atomic_write_text(note_path, markdown)

    result = apply_actions(
        ws,
        [
            {
                "type": "append_task",
                "path": "2_Areas/Home/Maintenance.md",
                "task": "- [ ] Replace porch light due:2026-02-28 p:P2",
                "create_if_missing": True,
            }
        ],
        require_approval=False,
    )
    assert "No changes" in result
