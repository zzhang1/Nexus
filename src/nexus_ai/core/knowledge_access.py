from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexus_ai.core.map_store import get_map_store
from nexus_ai.core.markdown import split_front_matter
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class SearchResult:
    path: str
    snippet: str
    score: float | None = None


@dataclass(frozen=True)
class FileRead:
    path: str
    front_matter: dict[str, Any]
    content: str
    truncated: bool


class KnowledgeAccess:
    def __init__(self, ws: Workspace):
        self.ws = ws

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        map_store = get_map_store(self.ws)
        hits = map_store.search(query, limit=limit)
        results: list[SearchResult] = []
        for h in hits:
            results.append(SearchResult(path=h.path, snippet=h.content, score=h.score))
        return results

    def find_files(self, query: str, limit: int = 25) -> list[str]:
        needle = query.strip().lower()
        if not needle:
            return []
        matches: list[str] = []
        for p in self.ws.iter_knowledge_markdown_files():
            rel = p.relative_to(self.ws.paths.knowledge_dir).as_posix()
            if needle in rel.lower():
                matches.append(rel)
            if len(matches) >= limit:
                break
        return matches

    def read_file(self, path: str, max_chars: int = 8000) -> FileRead:
        rel = self._safe_rel_path(path)
        if not rel:
            raise ValueError(f"Unsafe path: {path!r}")
        abs_path = (self.ws.paths.knowledge_dir / rel).resolve()
        if self.ws.paths.knowledge_dir not in abs_path.parents and abs_path != self.ws.paths.knowledge_dir:
            raise ValueError(f"Path escapes Knowledge/: {rel}")
        if not abs_path.exists() or not abs_path.is_file():
            raise FileNotFoundError(rel)
        text = abs_path.read_text(encoding="utf-8", errors="replace")
        doc = split_front_matter(text)
        body = doc.body
        truncated = False
        if max_chars and len(body) > max_chars:
            body = body[:max_chars] + "\n\n... (truncated)"
            truncated = True
        return FileRead(path=rel, front_matter=doc.front_matter, content=body, truncated=truncated)

    @staticmethod
    def _safe_rel_path(rel_path: str) -> str | None:
        rel_path = rel_path.strip().lstrip("/").replace("\\", "/")
        if not rel_path or rel_path.startswith("."):
            return None
        if ".." in Path(rel_path).parts:
            return None
        return rel_path
