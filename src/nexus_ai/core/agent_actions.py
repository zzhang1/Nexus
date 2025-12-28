from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rich.console import Console

from nexus_ai.core.filesystem import atomic_write_text
from nexus_ai.core.git_ops import commit_all
from nexus_ai.core.markdown import ensure_minimal_front_matter, split_front_matter
from nexus_ai.core.sync import sync_knowledge
from nexus_ai.core.workspace import Workspace

console = Console()


class ActionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProposedChange:
    rel_path: str
    diff: str


def _safe_rel_path(rel_path: str) -> str:
    rel_path = rel_path.strip().lstrip("/").replace("\\", "/")
    if not rel_path or rel_path.startswith("."):
        raise ActionError(f"Unsafe path: {rel_path!r}")
    if ".." in Path(rel_path).parts:
        raise ActionError(f"Unsafe path: {rel_path!r}")
    return rel_path


def _knowledge_abs(ws: Workspace, rel_path: str) -> Path:
    rel_path = _safe_rel_path(rel_path)
    p = (ws.paths.knowledge_dir / rel_path).resolve()
    if ws.paths.knowledge_dir not in p.parents and p != ws.paths.knowledge_dir:
        raise ActionError(f"Path escapes Knowledge/: {rel_path}")
    return p


def _read_text_or_empty(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _unified_diff(old: str, new: str, rel_path: str) -> str:
    import difflib

    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="",
    )
    return "\n".join(diff).strip()


def _append_task_to_markdown(existing: str, task_line: str) -> str:
    task_line = task_line.strip()
    if not task_line.startswith("- ["):
        # normalize: allow user/LLM to omit checkbox prefix
        task_line = f"- [ ] {task_line.lstrip('-').strip()}"

    if "## Tasks" in existing:
        parts = existing.splitlines()
        out: list[str] = []
        inserted = False
        for i, line in enumerate(parts):
            out.append(line)
            if not inserted and line.strip() == "## Tasks":
                # insert after heading, skipping any blank lines already present
                out.append("")
                out.append(task_line)
                inserted = True
        if inserted:
            return "\n".join(out).rstrip() + "\n"

    # Otherwise append a Tasks section at the end.
    body = existing.rstrip()
    if body:
        body += "\n\n"
    body += "## Tasks\n\n" + task_line + "\n"
    return body


def _ensure_markdown_with_front_matter(
    *,
    maybe_markdown: str,
    doc_type: str,
    title: str,
    tags: list[str] | None,
) -> str:
    fm = split_front_matter(maybe_markdown).front_matter
    if fm:
        return maybe_markdown if maybe_markdown.endswith("\n") else (maybe_markdown + "\n")
    return ensure_minimal_front_matter(
        maybe_markdown.strip() + "\n",
        doc_type=doc_type,
        title=title,
        tags=tags or [],
    )


def propose_actions(ws: Workspace, actions: list[dict[str, Any]]) -> list[ProposedChange]:
    changes: list[ProposedChange] = []
    for action in actions:
        t = str(action.get("type", "")).strip()
        if t == "create_file":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            new = str(action.get("content", ""))
            old = _read_text_or_empty(abs_path)
            if old:
                raise ActionError(f"Refusing create_file over existing file: {rel}")
            changes.append(ProposedChange(rel_path=rel, diff=_unified_diff("", new, rel)))
        elif t == "replace_file":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            old = _read_text_or_empty(abs_path)
            new = str(action.get("content", ""))
            changes.append(ProposedChange(rel_path=rel, diff=_unified_diff(old, new, rel)))
        elif t == "append_task":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            old = _read_text_or_empty(abs_path)
            task = str(action.get("task", "")).strip()
            if not old and not bool(action.get("create_if_missing", False)):
                raise ActionError(f"Target file missing and create_if_missing=false: {rel}")
            if not old:
                title = str(action.get("title") or Path(rel).stem)
                doc_type = str(action.get("doc_type") or "note")
                tags = action.get("tags") if isinstance(action.get("tags"), list) else []
                seeded = _ensure_markdown_with_front_matter(
                    maybe_markdown="",
                    doc_type=doc_type,
                    title=title,
                    tags=[str(t) for t in tags],
                )
                new = _append_task_to_markdown(seeded, task)
            else:
                new = _append_task_to_markdown(old, task)
            changes.append(ProposedChange(rel_path=rel, diff=_unified_diff(old, new, rel)))
        elif t == "move_file":
            src = _safe_rel_path(str(action["from"]))
            dst = _safe_rel_path(str(action["to"]))
            src_abs = _knowledge_abs(ws, src)
            dst_abs = _knowledge_abs(ws, dst)
            if not src_abs.exists():
                raise ActionError(f"Missing source file: {src}")
            if dst_abs.exists():
                raise ActionError(f"Refusing move over existing file: {dst}")
            old = _read_text_or_empty(src_abs)
            changes.append(ProposedChange(rel_path=src, diff=_unified_diff(old, "", src)))
            changes.append(ProposedChange(rel_path=dst, diff=_unified_diff("", old, dst)))
        elif t == "delete_file":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            old = _read_text_or_empty(abs_path)
            changes.append(ProposedChange(rel_path=rel, diff=_unified_diff(old, "", rel)))
        else:
            raise ActionError(f"Unknown action type: {t}")
    return changes


def apply_actions(ws: Workspace, actions: list[dict[str, Any]], *, require_approval: bool = True) -> str:
    """
    Apply actions to Knowledge/ with optional user approval. Always re-index and Git-commit after changes.
    """

    if not actions:
        return "No actions proposed."

    proposed = propose_actions(ws, actions)
    console.print("[bold]Proposed changes to Knowledge/[/bold]")
    for change in proposed:
        console.print(change.diff if change.diff else f"(no diff) {change.rel_path}")
        console.print()

    if require_approval:
        import typer

        if not typer.confirm("Apply these changes to Knowledge/?", default=False):
            return "No changes applied."

    # Apply
    for action in actions:
        t = str(action.get("type", "")).strip()
        if t == "create_file":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            content = str(action.get("content", ""))
            atomic_write_text(abs_path, content)
        elif t == "replace_file":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            content = str(action.get("content", ""))
            atomic_write_text(abs_path, content)
        elif t == "append_task":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            old = _read_text_or_empty(abs_path)
            task = str(action.get("task", "")).strip()
            if not old:
                title = str(action.get("title") or Path(rel).stem)
                doc_type = str(action.get("doc_type") or "note")
                tags = action.get("tags") if isinstance(action.get("tags"), list) else []
                seeded = _ensure_markdown_with_front_matter(
                    maybe_markdown="",
                    doc_type=doc_type,
                    title=title,
                    tags=[str(t) for t in tags],
                )
                new = _append_task_to_markdown(seeded, task)
            else:
                new = _append_task_to_markdown(old, task)
            atomic_write_text(abs_path, new)
        elif t == "move_file":
            src = _safe_rel_path(str(action["from"]))
            dst = _safe_rel_path(str(action["to"]))
            src_abs = _knowledge_abs(ws, src)
            dst_abs = _knowledge_abs(ws, dst)
            dst_abs.parent.mkdir(parents=True, exist_ok=True)
            src_abs.replace(dst_abs)
        elif t == "delete_file":
            rel = _safe_rel_path(str(action["path"]))
            abs_path = _knowledge_abs(ws, rel)
            if abs_path.exists():
                abs_path.unlink()
        else:
            raise ActionError(f"Unknown action type: {t}")

    # Re-index and commit.
    sync_knowledge(ws)
    commit_all(ws.paths.knowledge_dir, "Update Knowledge from chat")
    return "Changes applied and reindexed."


def parse_agent_json(text: str) -> dict[str, Any]:
    """
    Extract and parse a JSON object from an LLM response.
    """

    # Try direct parse first.
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass

    # Otherwise extract the first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ActionError("Model response did not contain JSON.")
    snippet = text[start : end + 1]
    try:
        obj = json.loads(snippet)
    except Exception as e:
        raise ActionError(f"Failed to parse JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ActionError("Top-level JSON must be an object.")
    return obj

