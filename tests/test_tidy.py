from pathlib import Path

import nexus_ai.core.tidy as tidy_mod
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.workspace import Workspace


def test_tidy_returns_prompt_when_llm_missing(tmp_path: Path, monkeypatch):
    ws = Workspace(tmp_path)
    ws.init_workspace()

    note_path = ws.paths.knowledge_dir / "2_Areas" / "Home" / "Note.md"
    atomic_write_text(
        note_path,
        ensure_minimal_front_matter("Test", doc_type="note", title="Note"),
    )

    # Force LLM to be unavailable (empty key).
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    result = tidy_mod.run_tidy(ws, focus="home")
    assert "LLM not configured" in result
