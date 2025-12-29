from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from nexus_ai.core.chunking import chunk_text
from nexus_ai.core.config import load_config
from nexus_ai.core.db import NexusDb
from nexus_ai.core.enrich import enrich_markdown
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


def _sanitize_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in {"_", "-", "."} else "_" for c in name.strip()).strip("_")


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _looks_like_year(s: str) -> bool:
    return len(s) == 4 and s.isdigit() and (1900 <= int(s) <= 2100)


def _suggest_knowledge_dir_for_inbox_path(ws: Workspace, inbox_rel: Path) -> Path:
    """
    Use the user's dropped folder structure as a hint, not a rule.

    - If the user already dropped PARA-like folders (1_Projects/...), mirror them.
    - Otherwise, infer a reasonable PARA placement from top-level folder names/keywords.
    - Default: 3_Resources/Inbox/<TopFolder>/...
    """

    parts = [p for p in inbox_rel.parts if p not in {".", ""}]
    if not parts:
        return ws.paths.knowledge_dir / "3_Resources" / "Inbox"

    top = parts[0].lower()

    # Respect explicit PARA-ish roots if the user supplied them.
    para_roots = {"1_projects", "2_areas", "3_resources", "4_archive"}
    if top in para_roots:
        return ws.paths.knowledge_dir / parts[0] / Path(*parts[1:-1])

    # Keyword-based, loose suggestions (small on purpose; extend later).
    taxes_keys = {"tax", "taxes", "irs", "w2", "1099"}
    real_estate_keys = {"real_estate", "real-estate", "realestate", "mortgage", "hoa", "rental", "property"}
    finance_keys = {"finance", "finances", "wealth", "invest", "investing", "brokerage", "bank", "insurance"}
    home_keys = {"home", "house", "repairs", "maintenance"}

    suggested_base: Path
    if any(k in top for k in taxes_keys) or top in taxes_keys:
        # Put taxes under Finances.
        suggested_base = ws.paths.knowledge_dir / "2_Areas" / "Finances" / "Taxes"
        # If the user included a year anywhere in the path, keep it.
        years = [p for p in parts if _looks_like_year(p)]
        if years:
            suggested_base = suggested_base / years[-1]
        return suggested_base / Path(*parts[1:-1])

    if any(k in top for k in real_estate_keys) or top in real_estate_keys:
        suggested_base = ws.paths.knowledge_dir / "2_Areas" / "Home" / "Real_Estate"
        return suggested_base / Path(*parts[1:-1])

    if any(k in top for k in finance_keys) or top in finance_keys:
        suggested_base = ws.paths.knowledge_dir / "2_Areas" / "Finances"
        return suggested_base / _sanitize_name(parts[0].title()) / Path(*parts[1:-1])

    if any(k in top for k in home_keys) or top in home_keys:
        suggested_base = ws.paths.knowledge_dir / "2_Areas" / "Home"
        return suggested_base / Path(*parts[1:-1])

    # Default: keep a hint of the original folder name under Resources/Inbox.
    return ws.paths.knowledge_dir / "3_Resources" / "Inbox" / _sanitize_name(parts[0].title()) / Path(*parts[1:-1])


def _suggest_knowledge_target(ws: Workspace, inbox_rel: Path) -> Path:
    target_dir = _suggest_knowledge_dir_for_inbox_path(ws, inbox_rel)
    safe_stem = _sanitize_name(inbox_rel.stem) or "Document"
    target = target_dir / f"{safe_stem}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    return _unique_path(target)


def ingest_inbox(ws: Workspace) -> IngestResult:
    ws.init_workspace()
    cfg = load_config(ws.paths.config_yaml)
    inbox = ws.paths.inbox_dir
    # Recurse so users can drop whole folders.
    files = [p for p in inbox.rglob("*") if p.is_file()]
    if not files:
        return IngestResult(files_ingested=0)

    for f in files:
        rel = f.relative_to(inbox)
        original_dst = ws.paths.source_dir / rel
        if not original_dst.exists():
            original_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, original_dst)

        extracted = extract_text(f)
        body = extracted.text.strip()
        if extracted.kind in {"md", "markdown"}:
            markdown_body = body
        else:
            markdown_body = f"# {f.stem}\n\n{body}\n"

        # Optional enrichment: tags + better formatting (enabled by default).
        enrich = enrich_markdown(
            llm=cfg.llm,
            filename=f.name,
            source_hint=str(rel.parent),
            extracted_text=markdown_body,
            extracted_kind=extracted.kind,
        )
        title = enrich.title or f.stem
        doc_type = enrich.doc_type or "note"
        tags = enrich.tags or []
        markdown_body = enrich.markdown_body or markdown_body

        markdown = ensure_minimal_front_matter(
            markdown_body,
            doc_type=doc_type,
            title=title,
            status="active",
            tags=tags,
        )

        target = _suggest_knowledge_target(ws, rel)
        atomic_write_text(target, markdown)

        archive_dst = ws.paths.archive_dir / rel
        archive_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(archive_dst))

        # Index just-written file.
        index_markdown_file(ws, target)

    # Clean up empty directories under inbox.
    for p in sorted([d for d in inbox.rglob("*") if d.is_dir()], reverse=True):
        try:
            p.rmdir()
        except OSError:
            pass

    commit_all(ws.paths.knowledge_dir, "Ingest inbox documents")
    return IngestResult(files_ingested=len(files))
