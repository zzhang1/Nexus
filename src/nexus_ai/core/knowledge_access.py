from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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

    def list_files(
        self,
        *,
        root: str | None = None,
        recursive: bool = True,
        limit: int = 1000,
        extensions: list[str] | None = None,
        include_hidden: bool = False,
    ) -> list[dict[str, Any]]:
        rel_root = (root or "").strip().lstrip("/").replace("\\", "/")
        if rel_root.lower().startswith("knowledge/"):
            rel_root = rel_root[len("knowledge/") :]
        if rel_root.lower() == "knowledge":
            rel_root = ""
        if rel_root and rel_root.startswith("."):
            raise ValueError(f"Unsafe root: {root!r}")
        if ".." in Path(rel_root).parts:
            raise ValueError(f"Unsafe root: {root!r}")

        base = self.ws.paths.knowledge_dir
        abs_root = (base / rel_root).resolve() if rel_root else base
        if base not in abs_root.parents and abs_root != base:
            raise ValueError(f"Root escapes Knowledge/: {root!r}")
        if not abs_root.exists():
            return []

        if extensions is None:
            exts = {".md"}
        else:
            exts = {str(ext).lower() for ext in extensions if str(ext).strip()}

        def is_hidden(rel_path: Path) -> bool:
            return any(part.startswith(".") for part in rel_path.parts)

        items: list[dict[str, Any]] = []
        iterator = abs_root.rglob("*") if recursive else abs_root.iterdir()
        for p in iterator:
            if not p.is_file():
                continue
            rel = p.relative_to(base)
            if not include_hidden and is_hidden(rel):
                continue
            if exts and p.suffix.lower() not in exts:
                continue
            stat = p.stat()
            items.append(
                {
                    "path": rel.as_posix(),
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def _safe_rel_path(rel_path: str) -> str | None:
        rel_path = rel_path.strip().lstrip("/").replace("\\", "/")
        if not rel_path or rel_path.startswith("."):
            return None
        if ".." in Path(rel_path).parts:
            return None
        return rel_path
