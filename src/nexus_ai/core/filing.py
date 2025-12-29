from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from nexus_ai.core.markdown import split_front_matter


@dataclass(frozen=True)
class FilingSummary:
    folders: list[str]
    tag_counts: list[tuple[str, int]]
    recent_files: list[str]


def build_filing_summary(knowledge_root: Path, *, max_files: int = 200) -> FilingSummary:
    """
    Build a lightweight inventory of the Knowledge/ structure for LLM routing.
    """

    knowledge_root = knowledge_root.resolve()
    folders = sorted(
        {
            str(p.relative_to(knowledge_root))
            for p in knowledge_root.rglob("*")
            if p.is_dir() and not p.name.startswith(".")
        }
    )

    tag_counter: Counter[str] = Counter()
    recent_files: list[str] = []
    files = sorted(knowledge_root.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[:max_files]:
        rel = str(p.relative_to(knowledge_root))
        recent_files.append(rel)
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = split_front_matter(text).front_matter
        tags = fm.get("tags") if isinstance(fm.get("tags"), list) else []
        for t in tags:
            tag_counter[str(t).lower()] += 1

    return FilingSummary(
        folders=folders[:200],
        tag_counts=tag_counter.most_common(30),
        recent_files=recent_files[:50],
    )


def simple_neighbors(knowledge_root: Path, extracted_text: str, *, limit: int = 6) -> list[str]:
    """
    Simple string-based neighbor search for similar documents.
    Uses filename + token overlap as a lightweight heuristic (no embeddings).
    """

    knowledge_root = knowledge_root.resolve()
    tokens = set(_tokens(extracted_text))
    if not tokens:
        return []

    scored: list[tuple[int, str]] = []
    for p in knowledge_root.rglob("*.md"):
        rel = str(p.relative_to(knowledge_root))
        text = p.read_text(encoding="utf-8", errors="replace")
        ft = split_front_matter(text).front_matter
        title = ft.get("title") if isinstance(ft.get("title"), str) else p.stem
        hay = f"{title} {text[:800]}"
        score = _overlap_score(tokens, hay)
        if score > 0:
            scored.append((score, rel))

    scored.sort(reverse=True)
    return [rel for _, rel in scored[:limit]]


def _tokens(text: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _overlap_score(needles: set[str], hay: str) -> int:
    tokens = set(_tokens(hay))
    return len(needles & tokens)

