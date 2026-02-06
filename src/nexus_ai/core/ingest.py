from __future__ import annotations

import re
import shutil
from collections import Counter
from typing import Any
from dataclasses import dataclass
from pathlib import Path

from nexus_ai.core.agent_actions import apply_actions, propose_actions
from nexus_ai.core.chunking import chunk_text
from nexus_ai.core.config import load_config
from nexus_ai.core.db import NexusDb
from nexus_ai.core.enrich import enrich_markdown, enrich_with_tools, merge_markdown
from nexus_ai.core.filing import build_filing_summary, simple_neighbors
from nexus_ai.core.extract import extract_text
from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.git_ops import commit_all
from nexus_ai.core.hashing import sha256_text
from nexus_ai.core.markdown import ensure_minimal_front_matter, split_front_matter
from nexus_ai.core.sync import index_markdown_file
from nexus_ai.core.workspace import Workspace
from nexus_ai.core.tool_audit import write_tool_audit

import yaml


@dataclass(frozen=True)
class IngestResult:
    files_ingested: int


@dataclass(frozen=True)
class IngestReviewItem:
    rel_inbox_path: str
    actions: list[dict[str, Any]]
    proposed: list
    filing_note: str | None
    filing_target: str | None


@dataclass(frozen=True)
class IngestReviewResult:
    files_ingested: int
    review_items: list[IngestReviewItem]


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


def _safe_rel_path(rel_path: str) -> str | None:
    rel_path = rel_path.strip().lstrip("/").replace("\\", "/")
    if not rel_path or rel_path.startswith("."):
        return None
    if ".." in Path(rel_path).parts:
        return None
    return rel_path


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _top_tokens(text: str, *, limit: int = 40) -> list[str]:
    tokens = [t for t in _tokenize(text) if len(t) > 2]
    if not tokens:
        return []
    counts = Counter(tokens)
    return [t for t, _ in counts.most_common(limit)]


def _folder_candidates(
    ws: Workspace,
    *,
    inbox_rel: Path,
    filename: str,
    extracted_text: str,
    filing_folders: list[str],
    max_candidates: int = 12,
) -> list[dict[str, Any]]:
    """
    Deterministic shortlist of likely folders before LLM filing.
    """

    suggested_dir = _suggest_knowledge_dir_for_inbox_path(ws, inbox_rel)
    suggested_rel = suggested_dir.relative_to(ws.paths.knowledge_dir).as_posix()
    suggested_rel = suggested_rel.strip().strip("/")

    tokens: set[str] = set()
    tokens.update(_tokenize(str(inbox_rel)))
    tokens.update(_tokenize(filename))
    tokens.update(_top_tokens(extracted_text))
    year_tokens = {t for t in tokens if len(t) == 4 and t.isdigit()}

    scored: list[tuple[int, str, str]] = []
    for folder in filing_folders:
        folder_norm = folder.strip().strip("/")
        if not folder_norm:
            continue
        folder_tokens = set(_tokenize(folder_norm))
        overlap = sorted(folder_tokens & tokens)
        score = len(overlap)
        reason = ""
        if folder_norm == suggested_rel or suggested_rel.startswith(folder_norm + "/"):
            score += 3
            reason = "inbox hint"
        if year_tokens and any(y in folder_tokens for y in year_tokens):
            score += 1
            if reason:
                reason += "; "
            reason += "year match"
        if overlap:
            if reason:
                reason += "; "
            reason += "overlap: " + ", ".join(overlap[:4])
        if score > 0:
            scored.append((score, folder_norm, reason or "token overlap"))

    scored.sort(key=lambda item: (-item[0], item[1]))

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, folder_norm, reason in scored:
        if folder_norm in seen:
            continue
        candidates.append(
            {
                "path": folder_norm,
                "score": score,
                "reason": reason,
                "exists": True,
            }
        )
        seen.add(folder_norm)
        if len(candidates) >= max_candidates:
            break

    def add_candidate(path: str, *, reason: str, exists: bool) -> None:
        if path and path not in seen:
            candidates.append({"path": path, "score": 0, "reason": reason, "exists": exists})
            seen.add(path)

    suggested_exists = (ws.paths.knowledge_dir / suggested_rel).exists()
    add_candidate(suggested_rel, reason="inbox hint", exists=suggested_exists)
    if "/" in suggested_rel:
        parent = suggested_rel.rsplit("/", 1)[0]
        add_candidate(parent, reason="parent of inbox hint", exists=(ws.paths.knowledge_dir / parent).exists())

    return candidates[:max_candidates]


def _apply_append_action(ws: Workspace, *, rel_path: str, append_block: str) -> str:
    abs_path = (ws.paths.knowledge_dir / rel_path).resolve()
    if not abs_path.exists() or not abs_path.is_file():
        return "Target file missing."
    old = abs_path.read_text(encoding="utf-8", errors="replace")
    block = append_block.strip()
    if not block:
        return "Append block empty."
    new = old.rstrip() + "\n\n" + block + "\n"
    actions = [{"type": "replace_file", "path": rel_path, "content": new}]
    return apply_actions(
        ws, actions, require_approval=True, commit_message="Ingest inbox documents"
    )


def _render_markdown(fm: dict[str, Any], body: str) -> str:
    if not fm:
        return body.rstrip() + "\n"
    fm_text = yaml.safe_dump(fm, sort_keys=False).strip()
    return f"---\n{fm_text}\n---\n\n{body.rstrip()}\n"


def _finalize_inbox_file(ws: Workspace, rel: Path) -> None:
    src = ws.paths.inbox_dir / rel
    if not src.exists():
        return
    original_dst = ws.paths.source_dir / rel
    original_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(original_dst))


def apply_ingest_actions(
    ws: Workspace,
    *,
    actions: list[dict[str, Any]],
    inbox_paths: list[str],
) -> str:
    result = apply_actions(
        ws,
        actions,
        require_approval=False,
        commit_message="Ingest inbox documents",
    )
    for rel in inbox_paths:
        _finalize_inbox_file(ws, Path(rel))
    return result


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


def _write_filing_note(ws: Workspace, *, rel: Path, target_rel: str, filing_note: str) -> None:
    note_dir = ws.paths.knowledge_dir / "3_Resources" / "Filing_Notes"
    note_dir.mkdir(parents=True, exist_ok=True)
    note = "---\n"
    note += "type: filing_note\n"
    note += f"title: Filing note for {Path(target_rel).name}\n"
    note += "status: active\n"
    note += "---\n\n"
    note += f"- Source: {rel}\n"
    note += f"- Destination: {target_rel}\n"
    note += f"- Note: {filing_note.strip()}\n"
    note_path = _unique_path(note_dir / f"{_sanitize_name(Path(target_rel).stem)}_filing.md")
    atomic_write_text(note_path, note)


def _filing_note_action(
    ws: Workspace,
    *,
    rel: Path,
    target_rel: str,
    filing_note: str,
) -> dict[str, Any]:
    content = "---\n"
    content += "type: filing_note\n"
    content += f"title: Filing note for {Path(target_rel).name}\n"
    content += "status: active\n"
    content += "---\n\n"
    content += f"- Source: {rel}\n"
    content += f"- Destination: {target_rel}\n"
    content += f"- Note: {filing_note.strip()}\n"
    note_dir = ws.paths.knowledge_dir / "3_Resources" / "Filing_Notes"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = _unique_path(note_dir / f"{_sanitize_name(Path(target_rel).stem)}_filing.md")
    return {
        "type": "create_file",
        "path": str(note_path.relative_to(ws.paths.knowledge_dir)).replace("\\", "/"),
        "content": content,
    }


def ingest_inbox(ws: Workspace, *, review: bool = False) -> IngestResult | IngestReviewResult:
    ws.init_workspace()
    cfg = load_config(ws.paths.config_yaml)
    filing_summary = build_filing_summary(ws.paths.knowledge_dir)
    inbox = ws.paths.inbox_dir
    # Recurse so users can drop whole folders.
    files = [p for p in inbox.rglob("*") if p.is_file()]
    if not files:
        return IngestResult(files_ingested=0)

    ingested = 0
    review_items: list[IngestReviewItem] = []
    audit_events: list[dict[str, Any]] = []
    for f in files:
        rel = f.relative_to(inbox)

        extracted = extract_text(f)
        body = extracted.text.strip()
        if extracted.kind in {"md", "markdown"}:
            markdown_body = body
        else:
            markdown_body = f"# {f.stem}\n\n{body}\n"

        # Optional enrichment: tags + better formatting (enabled by default).
        neighbors = simple_neighbors(ws.paths.knowledge_dir, markdown_body)
        folder_candidates = _folder_candidates(
            ws,
            inbox_rel=rel,
            filename=f.name,
            extracted_text=markdown_body,
            filing_folders=filing_summary.folders,
        )
        audit_steps: list[dict[str, Any]] = []
        enrich = enrich_with_tools(
            ws,
            llm=cfg.llm,
            filename=f.name,
            source_hint=str(rel.parent),
            extracted_text=markdown_body,
            extracted_kind=extracted.kind,
            knowledge_summary={
                "folders": filing_summary.folders,
                "folder_candidates": folder_candidates,
                "tag_counts": filing_summary.tag_counts,
                "recent_files": filing_summary.recent_files,
                "neighbors": neighbors,
            },
            audit_steps=audit_steps,
        )
        if audit_steps:
            audit_events.append(
                {
                    "inbox_path": str(rel.as_posix()),
                    "filename": f.name,
                    "source_hint": str(rel.parent),
                    "tool_steps": audit_steps,
                }
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

        target = None
        applied_action = False
        action = (enrich.action or "create").strip().lower()
        filing_note = enrich.filing_note.strip() if enrich.filing_note else None

        def record_review(actions: list[dict[str, Any]], target_rel: str | None) -> None:
            proposed = propose_actions(ws, actions)
            review_items.append(
                IngestReviewItem(
                    rel_inbox_path=str(rel.as_posix()),
                    actions=actions,
                    proposed=proposed,
                    filing_note=filing_note,
                    filing_target=target_rel,
                )
            )

        if action in {"append", "merge", "move"}:
            if action == "append" and enrich.target_rel_path:
                safe_target = _safe_rel_path(enrich.target_rel_path)
                if safe_target:
                    append_block = enrich.append_block or markdown_body
                    actions = [{"type": "replace_file", "path": safe_target, "content": ""}]
                    # Build final content with append.
                    abs_path = ws.paths.knowledge_dir / safe_target
                    if abs_path.exists():
                        old = abs_path.read_text(encoding="utf-8", errors="replace")
                        new = old.rstrip() + "\n\n" + append_block.strip() + "\n"
                        actions = [{"type": "replace_file", "path": safe_target, "content": new}]
                        if review:
                            if filing_note:
                                actions = actions + [
                                    _filing_note_action(
                                        ws,
                                        rel=rel,
                                        target_rel=safe_target,
                                        filing_note=filing_note,
                                    )
                                ]
                            record_review(actions, safe_target)
                            continue
                        result = apply_actions(
                            ws,
                            actions,
                            require_approval=True,
                            commit_message="Ingest inbox documents",
                        )
                        applied_action = result.startswith("Changes applied")
                        if applied_action:
                            target = ws.paths.knowledge_dir / safe_target
                        else:
                            continue
            elif action == "merge" and enrich.target_rel_path:
                safe_target = _safe_rel_path(enrich.target_rel_path)
                if safe_target:
                    abs_path = ws.paths.knowledge_dir / safe_target
                    if abs_path.exists():
                        existing = abs_path.read_text(encoding="utf-8", errors="replace")
                        doc = split_front_matter(existing)
                        merged_body = merge_markdown(
                            llm=cfg.llm,
                            existing_body=doc.body,
                            new_body=markdown_body,
                            filename=f.name,
                            source_hint=str(rel.parent),
                        )
                        if not merged_body:
                            merged_body = doc.body.rstrip() + "\n\n" + markdown_body
                        new_content = _render_markdown(doc.front_matter, merged_body)
                        actions = [{"type": "replace_file", "path": safe_target, "content": new_content}]
                        if review:
                            if filing_note:
                                actions = actions + [
                                    _filing_note_action(
                                        ws,
                                        rel=rel,
                                        target_rel=safe_target,
                                        filing_note=filing_note,
                                    )
                                ]
                            record_review(actions, safe_target)
                            continue
                        result = apply_actions(
                            ws,
                            actions,
                            require_approval=True,
                            commit_message="Ingest inbox documents",
                        )
                        applied_action = result.startswith("Changes applied")
                        if applied_action:
                            target = ws.paths.knowledge_dir / safe_target
                        else:
                            continue
            elif action == "move" and enrich.move_from_rel_path and enrich.move_to_rel_path:
                safe_from = _safe_rel_path(enrich.move_from_rel_path)
                safe_to = _safe_rel_path(enrich.move_to_rel_path)
                if safe_from and safe_to:
                    if not safe_to.lower().endswith(".md"):
                        safe_to = f"{safe_to}.md"
                    from_path = ws.paths.knowledge_dir / safe_from
                    if from_path.exists():
                        old = from_path.read_text(encoding="utf-8", errors="replace")
                        append_block = enrich.append_block or markdown_body
                        new = old.rstrip() + "\n\n" + append_block.strip() + "\n"
                        actions = [
                            {"type": "move_file", "from": safe_from, "to": safe_to},
                            {"type": "replace_file", "path": safe_to, "content": new},
                        ]
                        if review:
                            if filing_note:
                                actions = actions + [
                                    _filing_note_action(
                                        ws,
                                        rel=rel,
                                        target_rel=safe_to,
                                        filing_note=filing_note,
                                    )
                                ]
                            record_review(actions, safe_to)
                            continue
                        result = apply_actions(
                            ws,
                            actions,
                            require_approval=True,
                            commit_message="Ingest inbox documents",
                        )
                        applied_action = result.startswith("Changes applied")
                        if applied_action:
                            target = ws.paths.knowledge_dir / safe_to
                        else:
                            continue

        if not applied_action:
            target = _suggest_knowledge_target(ws, rel)
            if enrich.suggested_rel_path:
                safe_suggested = _safe_rel_path(enrich.suggested_rel_path)
                if safe_suggested:
                    target = ws.paths.knowledge_dir / safe_suggested
                    if target.suffix.lower() != ".md":
                        target = target.with_suffix(".md")
                    target = _unique_path(target)
            if review:
                rel_target = target.relative_to(ws.paths.knowledge_dir).as_posix()
                actions = [
                    {
                        "type": "create_file",
                        "path": rel_target,
                        "content": markdown,
                        "doc_type": doc_type,
                        "title": title,
                        "tags": tags,
                    }
                ]
                if filing_note:
                    actions = actions + [
                        _filing_note_action(
                            ws,
                            rel=rel,
                            target_rel=rel_target,
                            filing_note=filing_note,
                        )
                    ]
                record_review(actions, rel_target)
                continue
            atomic_write_text(target, markdown)

        # Record a brief filing note (keeps auto-filing auditable).
        if filing_note and target is not None:
            _write_filing_note(
                ws,
                rel=rel,
                target_rel=str(target.relative_to(ws.paths.knowledge_dir)),
                filing_note=filing_note,
            )

        _finalize_inbox_file(ws, rel)

        # Index just-written file.
        if target and not applied_action:
            index_markdown_file(ws, target)
        if not review:
            ingested += 1

    # Clean up empty directories under inbox.
    for p in sorted([d for d in inbox.rglob("*") if d.is_dir()], reverse=True):
        try:
            p.rmdir()
        except OSError:
            pass

    if audit_events:
        write_tool_audit(
            ws,
            run_type="ingest",
            payload={
                "review": review,
                "files_total": len(files),
                "files_ingested": ingested,
                "events": audit_events,
            },
        )
    if not review:
        commit_all(ws.paths.knowledge_dir, "Ingest inbox documents")
        return IngestResult(files_ingested=ingested)
    return IngestReviewResult(files_ingested=ingested, review_items=review_items)
