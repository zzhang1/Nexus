from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from litellm import completion

from nexus_ai.core.agent_actions import ActionError, parse_agent_json
from nexus_ai.core.config import LlmConfig, resolve_llm_settings
from nexus_ai.core.llm_protocol import extract_tool_calls, tool_prompt_block
from nexus_ai.core.runtime import ensure_litellm_quiet
from nexus_ai.core.tooling import execute_tool_calls
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class EnrichResult:
    title: str | None
    doc_type: str | None
    tags: list[str] | None
    markdown_body: str | None
    action: str | None
    suggested_rel_path: str | None
    target_rel_path: str | None
    append_block: str | None
    move_from_rel_path: str | None
    move_to_rel_path: str | None
    filing_note: str | None


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    return text if len(text) <= max_chars else text[:max_chars]


def _enrich_system_prompt(tooling: bool = False) -> str:
    base = """
You are a careful assistant that prepares durable Markdown notes.

Return ONLY a single JSON object with this schema:
{
  "title": "string (short, human-friendly)",
  "type": "note|project|reference|log|contact|other",
  "tags": ["tag", "..."],
  "markdown_body": "markdown content without YAML front matter",
  "action": "create|append|merge|move",
  "suggested_rel_path": "relative path under Knowledge/ for CREATE (e.g., 2_Areas/Finances/Taxes/2025/Statement.md)",
  "target_rel_path": "relative path under Knowledge/ for APPEND or MERGE (must exist)",
  "append_block": "markdown block to append for APPEND (no front matter; keep it concise)",
  "move_from_rel_path": "relative path under Knowledge/ for MOVE (must exist)",
  "move_to_rel_path": "relative path under Knowledge/ for MOVE (destination path)",
  "filing_note": "short note explaining why this location was chosen"
}

Rules:
- Do NOT summarize away important details. Preserve information.
- Improve formatting: headings, bullets, spacing, remove obvious extraction noise.
- Keep markdown_body reasonably short if the extracted text is huge: keep the most relevant content and include a note that content was truncated.
- Tags should be few (0-6), lowercase, and reflect the content (e.g., taxes, home, contract).
- Use knowledge_summary.folder_candidates as a deterministic shortlist of likely destinations.
- Use knowledge_summary.folders and neighbors to keep file placement consistent with existing patterns.
- Prefer action="append" ONLY when the content clearly belongs in an existing file (use neighbors/recent_files).
- If action="merge", provide target_rel_path (the system will merge content).
- If action="move", provide move_from_rel_path and move_to_rel_path. The system will move the file and append new content.
- If action="append", provide target_rel_path and append_block. If action="create", provide suggested_rel_path.
"""
    if not tooling:
        return base
    return base + "\n" + tool_prompt_block()


def _parse_enrich_payload(payload: dict[str, Any]) -> EnrichResult:
    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    doc_type = payload.get("type") if isinstance(payload.get("type"), str) else None
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else None
    if tags is not None:
        tags = [str(t).lower() for t in tags][:6]
    md = payload.get("markdown_body") if isinstance(payload.get("markdown_body"), str) else None
    action = payload.get("action") if isinstance(payload.get("action"), str) else None
    if action:
        action = action.strip().lower()
        if action not in {"create", "append", "merge", "move"}:
            action = None
    suggested = payload.get("suggested_rel_path") if isinstance(payload.get("suggested_rel_path"), str) else None
    target_rel_path = payload.get("target_rel_path") if isinstance(payload.get("target_rel_path"), str) else None
    append_block = payload.get("append_block") if isinstance(payload.get("append_block"), str) else None
    move_from_rel_path = payload.get("move_from_rel_path") if isinstance(payload.get("move_from_rel_path"), str) else None
    move_to_rel_path = payload.get("move_to_rel_path") if isinstance(payload.get("move_to_rel_path"), str) else None
    note = payload.get("filing_note") if isinstance(payload.get("filing_note"), str) else None
    return EnrichResult(
        title=title,
        doc_type=doc_type,
        tags=tags,
        markdown_body=md,
        action=action,
        suggested_rel_path=suggested,
        target_rel_path=target_rel_path,
        append_block=append_block,
        move_from_rel_path=move_from_rel_path,
        move_to_rel_path=move_to_rel_path,
        filing_note=note,
    )


def enrich_markdown(
    *,
    llm: LlmConfig,
    filename: str,
    source_hint: str,
    extracted_text: str,
    extracted_kind: str,
    knowledge_summary: dict,
) -> EnrichResult:
    """
    Optional, best-effort enrichment:
    - clean up extracted text into nicer Markdown
    - infer title/type/tags

    Returns partial fields on failure; callers should fall back safely.
    """

    if not llm.enrich_enabled:
        return EnrichResult(
            title=None,
            doc_type=None,
            tags=None,
            markdown_body=None,
            action=None,
            suggested_rel_path=None,
            target_rel_path=None,
            append_block=None,
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note=None,
        )

    ensure_litellm_quiet()
    llm_settings = resolve_llm_settings(llm)
    api_key = os.getenv(llm_settings["api_key_env"]) if llm_settings.get("api_key_env") else None
    if not api_key and not llm_settings["model"].startswith("ollama/"):
        return EnrichResult(
            title=None,
            doc_type=None,
            tags=None,
            markdown_body=None,
            action=None,
            suggested_rel_path=None,
            target_rel_path=None,
            append_block=None,
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note=None,
        )

    # Prefer a cheaper enrichment model if configured; fall back to primary model.
    enrich_model = llm.weak_model or llm.model
    if "/" not in enrich_model:
        enrich_model = f"{llm.provider}/{enrich_model}"
    if not enrich_model.startswith(("openrouter/", "openai/", "ollama/")):
        enrich_model = f"{llm.provider}/{enrich_model}"

    max_chars = int(llm.enrich_max_chars)
    clipped = _clip(extracted_text, max_chars=max_chars)

    system = _enrich_system_prompt()

    user = {
        "filename": filename,
        "source_hint": source_hint,
        "extracted_kind": extracted_kind,
        "text": clipped,
        "max_chars": max_chars,
        "knowledge_summary": knowledge_summary,
    }

    kwargs = {
        "model": enrich_model,
        "messages": [
            {"role": "system", "content": system.strip()},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }
    if llm_settings.get("base_url"):
        kwargs["api_base"] = llm_settings["base_url"]
    if api_key:
        kwargs["api_key"] = api_key

    resp = completion(**kwargs)
    raw = resp["choices"][0]["message"]["content"]
    try:
        payload = parse_agent_json(raw)
    except ActionError:
        return EnrichResult(
            title=None,
            doc_type=None,
            tags=None,
            markdown_body=None,
            action=None,
            suggested_rel_path=None,
            target_rel_path=None,
            append_block=None,
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note=None,
        )

    return _parse_enrich_payload(payload)


def enrich_with_tools(
    ws: Workspace,
    *,
    llm: LlmConfig,
    filename: str,
    source_hint: str,
    extracted_text: str,
    extracted_kind: str,
    knowledge_summary: dict,
    audit_steps: list[dict[str, Any]] | None = None,
    max_steps: int = 6,
) -> EnrichResult:
    """
    Tool-enabled enrichment. The model can call read-only tools to inspect Knowledge/
    before deciding how to file/merge/append/move.
    """

    if not llm.enrich_enabled:
        return EnrichResult(
            title=None,
            doc_type=None,
            tags=None,
            markdown_body=None,
            action=None,
            suggested_rel_path=None,
            target_rel_path=None,
            append_block=None,
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note=None,
        )

    ensure_litellm_quiet()
    llm_settings = resolve_llm_settings(llm)
    api_key = os.getenv(llm_settings["api_key_env"]) if llm_settings.get("api_key_env") else None
    if not api_key and not llm_settings["model"].startswith("ollama/"):
        return EnrichResult(
            title=None,
            doc_type=None,
            tags=None,
            markdown_body=None,
            action=None,
            suggested_rel_path=None,
            target_rel_path=None,
            append_block=None,
            move_from_rel_path=None,
            move_to_rel_path=None,
            filing_note=None,
        )

    enrich_model = llm.weak_model or llm.model
    if "/" not in enrich_model:
        enrich_model = f"{llm.provider}/{enrich_model}"
    if not enrich_model.startswith(("openrouter/", "openai/", "ollama/")):
        enrich_model = f"{llm.provider}/{enrich_model}"

    max_chars = int(llm.enrich_max_chars)
    clipped = _clip(extracted_text, max_chars=max_chars)

    system = _enrich_system_prompt(tooling=True)
    user = {
        "filename": filename,
        "source_hint": source_hint,
        "extracted_kind": extracted_kind,
        "text": clipped,
        "max_chars": max_chars,
        "knowledge_summary": knowledge_summary,
    }

    completion_kwargs = {
        "model": enrich_model,
        "messages": [
            {"role": "system", "content": system.strip()},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }
    if llm_settings.get("base_url"):
        completion_kwargs["api_base"] = llm_settings["base_url"]
    if api_key:
        completion_kwargs["api_key"] = api_key

    messages = list(completion_kwargs["messages"])
    last_error: str | None = None

    for step_index in range(max_steps):
        try:
            resp = completion(
                **{k: v for k, v in completion_kwargs.items() if k != "messages"},
                messages=messages,
            )
            raw = resp["choices"][0]["message"]["content"]
        except Exception as exc:
            last_error = str(exc)
            break

        try:
            payload = parse_agent_json(raw)
        except ActionError as exc:
            last_error = str(exc)
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "error": "Your previous response did not follow the required protocol.",
                            "details": last_error,
                            "instruction": "Reply again with ONLY a single JSON object matching the schema. No markdown, no commentary.",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            continue

        tool_calls = extract_tool_calls(payload)
        if tool_calls:
            tool_results = execute_tool_calls(ws, tool_calls)
            if audit_steps is not None:
                audit_steps.append(
                    {
                        "step": step_index + 1,
                        "tool_calls": tool_calls,
                        "tool_results": tool_results,
                    }
                )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tool_results": tool_results,
                            "instruction": "Use these tool results. Reply with ONLY a single JSON object and do not include tool calls unless you still need more data.",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            continue

        return _parse_enrich_payload(payload)

    # Fallback to standard enrichment on failure.
    return enrich_markdown(
        llm=llm,
        filename=filename,
        source_hint=source_hint,
        extracted_text=extracted_text,
        extracted_kind=extracted_kind,
        knowledge_summary=knowledge_summary,
    )


def merge_markdown(
    *,
    llm: LlmConfig,
    existing_body: str,
    new_body: str,
    filename: str,
    source_hint: str,
) -> str | None:
    """
    Best-effort merge of new_body into existing_body. Returns merged markdown body.
    """

    if not llm.enrich_enabled:
        return None

    ensure_litellm_quiet()
    llm_settings = resolve_llm_settings(llm)
    api_key = os.getenv(llm_settings["api_key_env"]) if llm_settings.get("api_key_env") else None
    if not api_key and not llm_settings["model"].startswith("ollama/"):
        return None

    merge_model = llm.weak_model or llm.model
    if "/" not in merge_model:
        merge_model = f"{llm.provider}/{merge_model}"
    if not merge_model.startswith(("openrouter/", "openai/", "ollama/")):
        merge_model = f"{llm.provider}/{merge_model}"

    system = """
You merge new content into an existing Markdown note.
Return ONLY JSON: {"merged_body": "markdown content without YAML front matter"}.
Rules:
- Preserve important structure from the existing note.
- Incorporate new_body content cleanly (dedupe obvious repetition).
- Keep the result concise and readable with headings/bullets when helpful.
"""

    user = {
        "filename": filename,
        "source_hint": source_hint,
        "existing_body": existing_body,
        "new_body": new_body,
    }

    kwargs = {
        "model": merge_model,
        "messages": [
            {"role": "system", "content": system.strip()},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }
    if llm_settings.get("base_url"):
        kwargs["api_base"] = llm_settings["base_url"]
    if api_key:
        kwargs["api_key"] = api_key

    try:
        resp = completion(**kwargs)
        raw = resp["choices"][0]["message"]["content"]
        payload = parse_agent_json(raw)
    except Exception:
        return None

    merged = payload.get("merged_body") if isinstance(payload.get("merged_body"), str) else None
    return merged.strip() if merged else None
