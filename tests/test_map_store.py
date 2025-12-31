from datetime import datetime
from pathlib import Path

from nexus_ai.core.map_store import get_map_store
from nexus_ai.core.workspace import Workspace
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.sync import sync_knowledge


def test_map_store_search_returns_hits(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    note_path = ws.paths.knowledge_dir / "2_Areas" / "Home" / "Maintenance.md"
    markdown = ensure_minimal_front_matter(
        "Replace porch light and fix gutter leak.\n",
        doc_type="note",
        title="Home Maintenance",
    )
    atomic_write_text(note_path, markdown)
    sync_knowledge(ws)

    store = get_map_store(ws)
    hits = store.search("porch light", limit=5)
    assert hits
    assert any("Maintenance.md" in h.path for h in hits)
