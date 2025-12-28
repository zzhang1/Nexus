from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexus_ai.core.db import NexusDb, OutboxItemRow
from nexus_ai.core.workspace import Workspace


def _rel_outbox_path(ws: Workspace, path: Path) -> str:
    p = (ws.paths.outbox_dir / path).resolve() if not path.is_absolute() else path.resolve()
    return str(p.relative_to(ws.paths.outbox_dir))


def list_outbox_items(ws: Workspace) -> list[OutboxItemRow]:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()

    # Ensure DB knows about existing files even if they were created manually.
    for p in ws.paths.outbox_dir.rglob("*"):
        if p.is_file():
            db.upsert_outbox_item(str(p.relative_to(ws.paths.outbox_dir)), "draft")
    return db.list_outbox_items()


def mark_outbox_approved(ws: Workspace, rel_path: Path) -> None:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    rel = _rel_outbox_path(ws, rel_path)
    if not (ws.paths.outbox_dir / rel).exists():
        raise FileNotFoundError(rel)
    db.set_outbox_approved(rel)


def delete_outbox_item(ws: Workspace, rel_path: Path) -> None:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    rel = _rel_outbox_path(ws, rel_path)
    file_path = ws.paths.outbox_dir / rel
    if file_path.exists():
        file_path.unlink()
    db.delete_outbox_item(rel)

