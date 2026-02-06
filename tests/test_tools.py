from pathlib import Path

from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.knowledge_access import KnowledgeAccess
from nexus_ai.core.llm_protocol import extract_tool_calls, normalize_tool_calls
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.tooling import execute_tool_calls
from nexus_ai.core.workspace import Workspace


def _write_md(path: Path, title: str) -> None:
    atomic_write_text(
        path,
        ensure_minimal_front_matter("Body\n", doc_type="note", title=title),
    )


def test_list_files_filters(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()

    home_dir = ws.paths.knowledge_dir / "2_Areas" / "Home"
    home_dir.mkdir(parents=True, exist_ok=True)
    home_md = home_dir / "Home.md"
    _write_md(home_md, "Home")

    txt_dir = ws.paths.knowledge_dir / "3_Resources"
    txt_dir.mkdir(parents=True, exist_ok=True)
    txt_path = txt_dir / "Notes.txt"
    txt_path.write_text("notes", encoding="utf-8")

    hidden_path = ws.paths.knowledge_dir / ".hidden.md"
    _write_md(hidden_path, "Hidden")

    access = KnowledgeAccess(ws)

    default_paths = [item["path"] for item in access.list_files()]
    assert "2_Areas/Home/Home.md" in default_paths
    assert "3_Resources/Notes.txt" not in default_paths
    assert ".hidden.md" not in default_paths

    txt_paths = [item["path"] for item in access.list_files(extensions=[".txt"])]
    assert "3_Resources/Notes.txt" in txt_paths

    hidden_paths = [item["path"] for item in access.list_files(include_hidden=True)]
    assert ".hidden.md" in hidden_paths

    non_recursive = [item["path"] for item in access.list_files(root="2_Areas", recursive=False)]
    assert "2_Areas/Home/Home.md" not in non_recursive


def test_tool_call_normalization() -> None:
    payload = {
        "mode": "tool",
        "tool_calls": [{"type": "read_file", "path": "2_Areas/Home/Home.md"}],
    }
    calls = extract_tool_calls(payload)
    normalized = normalize_tool_calls(calls)
    assert normalized
    assert normalized[0]["type"] == "read_file"
    assert normalized[0]["args"]["path"] == "2_Areas/Home/Home.md"
    assert normalized[0]["id"]

    legacy = {"type": "search", "query": "taxes", "limit": 5}
    normalized_legacy = normalize_tool_calls(extract_tool_calls(legacy))
    assert normalized_legacy[0]["args"]["query"] == "taxes"
    assert normalized_legacy[0]["args"]["limit"] == 5


def test_execute_tool_calls_list_files(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()

    home_dir = ws.paths.knowledge_dir / "2_Areas" / "Home"
    home_dir.mkdir(parents=True, exist_ok=True)
    _write_md(home_dir / "Home.md", "Home")

    results = execute_tool_calls(
        ws,
        [{"id": "t1", "type": "list_files", "args": {"root": "Knowledge/", "limit": 50}}],
    )
    assert results
    result = results[0]
    assert result["ok"] is True
    paths = [item["path"] for item in result["result"]["results"]]
    assert "2_Areas/Home/Home.md" in paths
