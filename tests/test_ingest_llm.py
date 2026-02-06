from pathlib import Path

from nexus_ai.core.enrich import EnrichResult
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.ingest import IngestReviewResult, apply_ingest_actions, ingest_inbox
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.workspace import Workspace


def test_ingest_create_with_llm(monkeypatch, tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()

    inbox_file = ws.paths.inbox_dir / "receipt.txt"
    inbox_file.write_text("Lunch receipt", encoding="utf-8")

    def fake_enrich(_ws=None, **_kwargs):
        return EnrichResult(
            title="Lunch Receipt",
            doc_type="note",
            tags=["finance"],
            markdown_body="# Lunch Receipt\n\nLunch receipt details.",
            action="create",
            suggested_rel_path="2_Areas/Finances/Receipts/Lunch.md",
            target_rel_path=None,
            append_block=None,
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note="Finance receipt.",
        )

    monkeypatch.setattr("nexus_ai.core.ingest.enrich_with_tools", fake_enrich)

    result = ingest_inbox(ws)
    assert result.files_ingested == 1

    target = ws.paths.knowledge_dir / "2_Areas" / "Finances" / "Receipts" / "Lunch.md"
    assert target.exists()
    assert (ws.paths.archive_dir / "receipt.txt").exists() is False
    assert (ws.paths.source_dir / "receipt.txt").exists()


def test_ingest_append_review(monkeypatch, tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()

    existing = ws.paths.knowledge_dir / "2_Areas" / "Home" / "Home.md"
    atomic_write_text(
        existing,
        ensure_minimal_front_matter("## Notes\n\nExisting.\n", doc_type="note", title="Home"),
    )

    inbox_file = ws.paths.inbox_dir / "home_note.txt"
    inbox_file.write_text("New home note", encoding="utf-8")

    def fake_enrich(_ws=None, **_kwargs):
        return EnrichResult(
            title="Home Note",
            doc_type="note",
            tags=["home"],
            markdown_body="# Home Note\n\nNew home note.",
            action="append",
            suggested_rel_path=None,
            target_rel_path="2_Areas/Home/Home.md",
            append_block="## Notes\n\nNew home note.",
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note="Append to Home notes.",
        )

    monkeypatch.setattr("nexus_ai.core.ingest.enrich_with_tools", fake_enrich)

    result = ingest_inbox(ws, review=True)
    assert isinstance(result, IngestReviewResult)
    assert len(result.review_items) == 1
    assert inbox_file.exists()

    item = result.review_items[0]
    actions = item.actions
    inbox_paths = [item.rel_inbox_path]
    apply_ingest_actions(ws, actions=actions, inbox_paths=inbox_paths)
    updated = existing.read_text(encoding="utf-8", errors="replace")
    assert "New home note." in updated
    assert not inbox_file.exists()
    assert (ws.paths.archive_dir / "home_note.txt").exists() is False
    assert (ws.paths.source_dir / "home_note.txt").exists()


def test_ingest_create_review(monkeypatch, tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.init_workspace()

    inbox_file = ws.paths.inbox_dir / "statement.txt"
    inbox_file.write_text("Bank statement", encoding="utf-8")

    def fake_enrich(_ws=None, **_kwargs):
        return EnrichResult(
            title="Bank Statement",
            doc_type="reference",
            tags=["finance"],
            markdown_body="# Bank Statement\n\nStatement details.",
            action="create",
            suggested_rel_path="2_Areas/Finances/Statements/Statement.md",
            target_rel_path=None,
            append_block=None,
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note="Finance statement.",
        )

    monkeypatch.setattr("nexus_ai.core.ingest.enrich_with_tools", fake_enrich)

    result = ingest_inbox(ws, review=True)
    assert isinstance(result, IngestReviewResult)
    assert len(result.review_items) == 1
    assert inbox_file.exists()

    target = ws.paths.knowledge_dir / "2_Areas" / "Finances" / "Statements" / "Statement.md"
    assert not target.exists()

    item = result.review_items[0]
    assert any(a.get("type") == "create_file" for a in item.actions)
