from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from nexus_ai.core.db import NexusDb
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class SearchHit:
    path: str
    content: str
    score: float | None = None


class MapStore(Protocol):
    def replace_chunks(self, *, path: str, chunks: list[str]) -> None: ...

    def search(self, query: str, limit: int = 8) -> list[SearchHit]: ...


class SQLiteMapStore:
    def __init__(self, db: NexusDb):
        self.db = db

    def replace_chunks(self, *, path: str, chunks: list[str]) -> None:
        self.db.replace_chunks(path=path, chunks=chunks)

    def search(self, query: str, limit: int = 8) -> list[SearchHit]:
        rows = self.db.search_chunks(query, limit=limit)
        hits: list[SearchHit] = []
        for r in rows:
            hits.append(SearchHit(path=r["path"], content=r["content"], score=r["score"]))
        return hits


def get_map_store(ws: Workspace) -> MapStore:
    # Future: switch based on config to GraphRAG / vector store backends.
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    return SQLiteMapStore(db)
