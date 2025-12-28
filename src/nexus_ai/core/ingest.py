from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from nexus_ai.core.chunking import chunk_text
from nexus_ai.core.db import NexusDb
from nexus_ai.core.extract import extract_text
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.git_ops import commit_all
from nexus_ai.core.hashing import sha256_text
from nexus_ai.core.markdown import ensure_minimal_front_matter
from nexus_ai.core.sync import index_markdown_file
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class IngestResult:
    files_ingested: int


def _default_knowledge_target(ws: Workspace, source_file: Path) -> Path:
    safe_name = source_file.stem.replace(" ", "_")
    target_dir = ws.paths.knowledge_dir / "3_Resources" / "Inbox"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{safe_name}.md"
    i = 2
    while target.exists():
        target = target_dir / f"{safe_name}_{i}.md"
        i += 1
    return target


def ingest_inbox(ws: Workspace) -> IngestResult:
    ws.init_workspace()
    inbox = ws.paths.inbox_dir
    files = [p for p in inbox.iterdir() if p.is_file()]
    if not files:
        return IngestResult(files_ingested=0)

    for f in files:
        original_dst = ws.paths.source_dir / f.name
        if not original_dst.exists():
            shutil.copy2(f, original_dst)

        extracted = extract_text(f)
        body = extracted.text.strip()
        if extracted.kind in {"md", "markdown"}:
            markdown_body = body
        else:
            markdown_body = f"# {f.stem}\n\n{body}\n"

        markdown = ensure_minimal_front_matter(
            markdown_body,
            doc_type="note",
            title=f.stem,
            status="active",
            tags=[],
        )

        target = _default_knowledge_target(ws, f)
        atomic_write_text(target, markdown)

        archive_dst = ws.paths.archive_dir / f.name
        shutil.move(str(f), str(archive_dst))

        # Index just-written file.
        index_markdown_file(ws, target)

    commit_all(ws.paths.knowledge_dir, "Ingest inbox documents")
    return IngestResult(files_ingested=len(files))

