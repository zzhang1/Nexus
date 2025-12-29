from pathlib import Path

from nexus_ai.core.ingest import ingest_inbox
from nexus_ai.core.workspace import Workspace


def test_ingest_recurses_inbox_and_preserves_paths(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.init_workspace()
    # Disable enrichment to keep unit tests deterministic.
    cfg = ws.paths.config_yaml.read_text(encoding="utf-8")
    ws.paths.config_yaml.write_text(cfg.replace("enabled: true", "enabled: false"), encoding="utf-8")

    nested = ws.paths.inbox_dir / "Taxes" / "2025" / "w2.txt"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("W2 stuff", encoding="utf-8")

    result = ingest_inbox(ws)
    assert result.files_ingested == 1

    assert (ws.paths.source_dir / "Taxes" / "2025" / "w2.txt").exists()
    assert (ws.paths.archive_dir / "Taxes" / "2025" / "w2.txt").exists()
    assert not nested.exists()

    # Loose suggestion: taxes should land under 2_Areas/Finances/Taxes/(year)/...
    candidates = list((ws.paths.knowledge_dir / "2_Areas" / "Finances" / "Taxes").rglob("w2.md"))
    assert candidates, "Expected a w2.md note under suggested taxes folder"
