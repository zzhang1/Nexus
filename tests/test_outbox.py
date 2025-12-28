from pathlib import Path

from nexus_ai.core.workspace import Workspace
from nexus_ai.core.outbox import list_outbox_items, mark_outbox_approved
from nexus_ai.core.filesystem import atomic_write_text


def test_outbox_list_and_approve(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    draft = ws.paths.outbox_dir / "drafts" / "email.md"
    atomic_write_text(draft, "Hello")

    items = list_outbox_items(ws)
    assert any(item.rel_path.endswith("drafts/email.md") for item in items)

    mark_outbox_approved(ws, Path("drafts/email.md"))
    items2 = list_outbox_items(ws)
    assert any(item.status == "approved" for item in items2)

