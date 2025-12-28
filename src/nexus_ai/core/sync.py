from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexus_ai.core.chunking import chunk_text
from nexus_ai.core.db import NexusDb
from nexus_ai.core.hashing import sha256_text
from nexus_ai.core.markdown import split_front_matter
from nexus_ai.core.tasks_parse import parse_tasks_from_markdown
from nexus_ai.core.time_parse import parse_time_items_from_front_matter
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class SyncStats:
    indexed: int
    deleted: int
    unchanged: int


def index_markdown_file(ws: Workspace, file_path: Path) -> None:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()

    rel = str(file_path.relative_to(ws.paths.knowledge_dir))
    text = file_path.read_text(encoding="utf-8", errors="replace")
    sha = sha256_text(text)
    mtime = file_path.stat().st_mtime

    fm_doc = split_front_matter(text)
    fm = fm_doc.front_matter
    title = fm.get("title") if isinstance(fm.get("title"), str) else file_path.stem
    doc_type = fm.get("type") if isinstance(fm.get("type"), str) else None
    status = fm.get("status") if isinstance(fm.get("status"), str) else None
    tags_val = fm.get("tags") if isinstance(fm.get("tags"), list) else []
    tags = [str(t) for t in tags_val]
    created_ts = fm.get("created") if isinstance(fm.get("created"), str) else None
    updated_ts = fm.get("updated") if isinstance(fm.get("updated"), str) else None

    db.upsert_document(
        path=rel,
        sha256=sha,
        mtime=mtime,
        title=title,
        doc_type=doc_type,
        status=status,
        tags=tags,
        created_ts=created_ts,
        updated_ts=updated_ts,
    )

    chunks = chunk_text(fm_doc.body)
    db.replace_chunks(path=rel, chunks=chunks)

    tasks = parse_tasks_from_markdown(markdown_text=text, source_path=file_path, knowledge_root=ws.paths.knowledge_dir)
    db.replace_tasks_for_document(rel, tasks)

    db.delete_time_items_for_source_path(rel)
    events, deadlines = parse_time_items_from_front_matter(fm, source_path=rel)
    db.upsert_events(events)
    db.upsert_deadlines(deadlines)


def sync_knowledge(ws: Workspace) -> SyncStats:
    ws.init_workspace()
    db = NexusDb(ws.paths.db_path)
    db.init_schema()

    existing = db.list_document_paths()
    seen: set[str] = set()

    indexed = 0
    unchanged = 0
    for path in ws.iter_knowledge_markdown_files():
        rel = str(path.relative_to(ws.paths.knowledge_dir))
        seen.add(rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        sha = sha256_text(text)
        row = db.get_document(rel)
        if row and row.get("sha256") == sha:
            unchanged += 1
            continue
        index_markdown_file(ws, path)
        indexed += 1

    deleted = 0
    for rel in sorted(existing - seen):
        db.delete_document(rel)
        deleted += 1

    return SyncStats(indexed=indexed, deleted=deleted, unchanged=unchanged)
