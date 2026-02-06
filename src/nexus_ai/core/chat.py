from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from litellm import completion

from nexus_ai.core.agent_actions import ActionError, apply_actions, parse_agent_json
from nexus_ai.core.config import load_config, resolve_llm_settings
from nexus_ai.core.db import NexusDb
from nexus_ai.core.integrations import IntegrationRegistry
from nexus_ai.core.llm_protocol import (
    TOOL_TYPES,
    VALID_MODES,
    VALID_PLAN_SCOPES,
    extract_tool_calls,
    tool_prompt_block,
)
from nexus_ai.core.map_store import get_map_store
from nexus_ai.core.planner import build_plan
from nexus_ai.core.runtime import ensure_litellm_quiet
from nexus_ai.core.tooling import execute_tool_calls
from nexus_ai.core.tool_audit import write_tool_audit
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class ChatPrepared:
    hits: list[Any]
    context: str
    llm_ready: bool
    completion_kwargs: dict[str, Any] | None
    messages: list[dict[str, str]] | None


READ_ONLY_TOOLS = set(TOOL_TYPES)


def _json_fallback(obj: Any) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def _allowed_llm_tools(ws: Workspace) -> set[str]:
    try:
        cfg = load_config(ws.paths.config_yaml)
        return IntegrationRegistry(cfg).allowed_llm_tools()
    except Exception:
        return set(READ_ONLY_TOOLS)


def _infer_plan_scope(query: str) -> str | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    if "today" in q:
        return "today"
    if "this week" in q or "week" in q or "weekly" in q:
        return "week"
    if "this month" in q or "month" in q or "monthly" in q:
        return "month"
    if "plan" in q:
        return "week"
    return None


def _query_mentions_due(query: str) -> bool:
    q = (query or "").lower()
    if any(token in q for token in ("due", "deadline", "by ", "before ", "on ", "tomorrow", "today")):
        return True
    if "next week" in q or "next month" in q:
        return True
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", q):
        return True
    return False


def _query_mentions_priority(query: str) -> bool:
    q = (query or "").lower()
    if "priority" in q:
        return True
    return bool(re.search(r"\bp[123]\b", q))


def _query_mentions_effort(query: str) -> bool:
    q = (query or "").lower()
    if "effort" in q or "estimate" in q:
        return True
    return bool(re.search(r"\b\d+\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)\b", q))


def _query_mentions_context(query: str) -> bool:
    q = (query or "").lower()
    return "ctx:" in q or "context" in q


def _sanitize_task_line(task_line: str, query: str) -> str:
    line = task_line.rstrip()
    if not line:
        return line

    allow_due = _query_mentions_due(query)
    allow_priority = _query_mentions_priority(query)
    allow_effort = _query_mentions_effort(query)
    allow_ctx = _query_mentions_context(query)

    def strip_token(text: str, token: str) -> str:
        return re.sub(rf"(^|\s){re.escape(token)}[^\s]+", " ", text)

    if not allow_due:
        line = strip_token(line, "due:")
    if not allow_priority:
        line = strip_token(line, "p:")
    if not allow_effort:
        line = strip_token(line, "effort:")
    if not allow_ctx:
        line = strip_token(line, "ctx:")

    # Normalize spacing (keep checkbox prefix intact).
    if line.startswith("- ["):
        prefix, rest = line.split("]", 1)
        rest = re.sub(r"\s+", " ", rest).strip()
        return f"{prefix}] {rest}".rstrip()

    return re.sub(r"\s+", " ", line).strip()


def _sanitize_actions(actions: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if str(action.get("type", "")).strip() == "append_task":
            task = str(action.get("task", "")).strip()
            if task:
                action = dict(action)
                action["task"] = _sanitize_task_line(task, query)
        sanitized.append(action)
    return sanitized


def _prepare_chat_request(ws: Workspace, *, query: str) -> ChatPrepared:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    map_store = get_map_store(ws)
    hits = map_store.search(query, limit=8)
    context_lines: list[str] = []
    for h in hits:
        context_lines.append(f"FILE: {h.path}\n{h.content}".strip())
    context = "\n\n---\n\n".join(context_lines).strip()

    # If we have no indexed context, still allow "write intent" planning.
    if not context:
        context = "(No indexed context found.)"

    cfg = load_config(ws.paths.config_yaml)
    ensure_litellm_quiet()
    llm_settings = resolve_llm_settings(cfg.llm)
    api_key = os.getenv(llm_settings["api_key_env"]) if llm_settings.get("api_key_env") else None
    llm_ready = bool(api_key) or llm_settings["model"].startswith("ollama/")
    if not llm_ready:
        return ChatPrepared(
            hits=hits,
            context=context,
            llm_ready=False,
            completion_kwargs=None,
            messages=None,
        )

    # Provide the model a small view of the territory.
    knowledge_subdirs = []
    for p in sorted(ws.paths.knowledge_dir.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            knowledge_subdirs.append(p.name + "/")
    candidate_files = [h.path for h in hits]

    knowledge_files: list[str] = []
    for p in ws.paths.knowledge_dir.rglob("*.md"):
        if ".git" in p.parts:
            continue
        rel = p.relative_to(ws.paths.knowledge_dir).as_posix()
        if rel.startswith("."):
            continue
        knowledge_files.append(rel)
        if len(knowledge_files) >= 200:
            break

    system = f"""
You are Nexus AI, a personal assistant that can read AND propose safe edits to the user's Knowledge/ markdown library.

You MUST respond with a single JSON object (no extra text).

Protocol (choose exactly one mode):
1) Answer (informational):
{{
  "mode": "answer",
  "answer": "...",
  "sources": ["relative/path.md", "..."]
}}

2) Plan (time window):
{{
  "mode": "plan",
  "scope": "today|week|month",
  "note": "short rationale"
}}

3) Actions (propose edits to Knowledge/):
{{
  "mode": "actions",
  "note": "short explanation",
  "actions": [
    {{"type": "append_task", "path": "2_Areas/Home/Home.md", "task": "- [ ] ... due:YYYY-MM-DD p:P1", "create_if_missing": true}},
    {{"type": "create_file", "path": "3_Resources/...", "content": "..."}},
    {{"type": "replace_file", "path": "2_Areas/...", "content": "..."}},
    {{"type": "edit_block", "path": "2_Areas/...", "old": "exact block", "new": "replacement block"}},
    {{"type": "move_file", "from": "3_Resources/Old.md", "to": "3_Resources/New.md"}},
    {{"type": "delete_file", "path": "4_Archive/Old.md"}}
  ]
}}

4) Tool (read-only lookup; use when you need more context):
{{
  "mode": "tool",
  "tool_calls": [
    {{"id": "t1", "type": "search", "args": {{"query": "...", "limit": 8}}}}
  ]
}}

{tool_prompt_block()}

Tool results will be provided as JSON:
{{
  "tool_results": [
    {{"id": "t1", "type": "search", "ok": true, "result": {{...}}}}
  ]
}}
Use tool results, then respond with answer/plan/actions (no tool calls).

Rules:
- All paths must be relative to Knowledge/ and must not start with '.' or contain '..'.
- Prefer append_task for "add a task" requests. Put tasks under a '## Tasks' section (Nexus will create if missing).
- If a relevant file already exists, choose it from knowledge_files or candidate_files instead of creating a new one.
- If you need to edit a specific section, first read the file, then use edit_block with the exact text to replace.
- If you need to discover files or context, use mode=tool first. After tool results, return final actions or a plan/answer.
- If you are unsure which file to edit, ask a clarification question (answer mode) rather than creating a new file.
- Keep changes minimal and do not invent facts. If you need clarification, ask as an answer instead of acting.
"""

    user = {
        "query": query,
        "knowledge_folders": knowledge_subdirs[:40],
        "candidate_files": candidate_files[:12],
        "knowledge_files": knowledge_files,
        "context": context,
    }

    completion_kwargs = {
        "model": llm_settings["model"],
        "messages": [
            {"role": "system", "content": system.strip()},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0,
    }
    if llm_settings["model"].startswith("openai/"):
        completion_kwargs["response_format"] = {"type": "json_object"}
    if llm_settings.get("base_url"):
        completion_kwargs["api_base"] = llm_settings["base_url"]
    if api_key:
        completion_kwargs["api_key"] = api_key

    messages = list(completion_kwargs["messages"])
    return ChatPrepared(
        hits=hits,
        context=context,
        llm_ready=True,
        completion_kwargs=completion_kwargs,
        messages=messages,
    )


def _run_llm_with_messages(
    completion_kwargs: dict[str, Any], messages: list[dict[str, str]]
) -> tuple[dict | None, str, list[dict[str, str]], str | None]:
    raw = ""
    payload: dict | None = None
    last_error: str | None = None
    working_messages = list(messages)
    response_format_fallback = True
    for _attempt in range(3):
        try:
            resp = completion(
                **{k: v for k, v in completion_kwargs.items() if k != "messages"},
                messages=working_messages,
            )
            raw = resp["choices"][0]["message"]["content"]
        except Exception as exc:
            last_error = str(exc)
            if response_format_fallback and "response_format" in completion_kwargs:
                completion_kwargs = dict(completion_kwargs)
                completion_kwargs.pop("response_format", None)
                response_format_fallback = False
                continue
            break
        try:
            payload = parse_agent_json(raw)
            break
        except ActionError as e:
            last_error = str(e)
            # Ask the model to try again with strict JSON only.
            working_messages.append({"role": "assistant", "content": raw})
            working_messages.append(
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
    return payload, raw, working_messages, last_error


def _run_llm(prepared: ChatPrepared) -> tuple[dict | None, str, list[dict[str, str]], str | None]:
    if not prepared.llm_ready or not prepared.completion_kwargs or not prepared.messages:
        return None, "", [], "LLM not configured."

    return _run_llm_with_messages(prepared.completion_kwargs, list(prepared.messages))


def _resolve_payload_with_tools(
    ws: Workspace,
    prepared: ChatPrepared,
    *,
    max_steps: int = 10,
    audit_steps: list[dict[str, Any]] | None = None,
) -> tuple[dict | None, str, list[dict[str, str]], str | None]:
    if not prepared.llm_ready or not prepared.completion_kwargs or not prepared.messages:
        return None, "", [], "LLM not configured."

    messages = list(prepared.messages)
    allowed_tools = _allowed_llm_tools(ws)
    raw = ""
    last_error: str | None = None
    for step_index in range(max_steps):
        payload, raw, messages, last_error = _run_llm_with_messages(
            prepared.completion_kwargs, messages
        )
        if payload is None:
            return None, raw, messages, last_error
        mode = str(payload.get("mode", "")).strip().lower()
        tool_calls = extract_tool_calls(payload)
        tool_calls = [c for c in tool_calls if str(c.get("type", "")).strip() in allowed_tools]

        if mode == "tool" and not tool_calls:
            return payload, raw, messages, "Tool mode requires tool_calls."

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
        else:
            if mode in VALID_MODES and mode != "tool":
                return payload, raw, messages, None
            if mode != "tool" and not tool_calls:
                return payload, raw, messages, None
            tool_results = []

        if not tool_results:
            return payload, raw, messages, None
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "tool_results": tool_results,
                        "instruction": "Use these tool results. Reply with ONLY a single JSON object. Do not include tool calls unless you still need more data.",
                    },
                    ensure_ascii=False,
                    default=_json_fallback,
                ),
            }
        )

    return None, raw, messages, last_error or "Tool resolution exceeded."


def generate_chat_payload(ws: Workspace, *, query: str) -> dict[str, Any]:
    prepared = _prepare_chat_request(ws, query=query)
    if not prepared.llm_ready:
        sources = [h.path for h in prepared.hits]
        scope = _infer_plan_scope(query)
        if scope:
            return {"mode": "plan", "scope": scope, "note": "Plan requested without LLM."}
        return {
            "mode": "answer",
            "answer": "LLM not configured (set OPENROUTER_API_KEY). Here are the most relevant excerpts:\n\n"
            + prepared.context,
            "sources": sources,
        }

    audit_steps: list[dict[str, Any]] = []
    payload, raw, _messages, last_error = _resolve_payload_with_tools(
        ws, prepared, audit_steps=audit_steps
    )
    if audit_steps:
        write_tool_audit(
            ws,
            run_type="chat",
            payload={
                "query": query,
                "model": prepared.completion_kwargs.get("model") if prepared.completion_kwargs else None,
                "resolved_mode": payload.get("mode") if isinstance(payload, dict) else None,
                "error": last_error,
                "steps": audit_steps,
            },
        )
    if payload is None:
        scope = _infer_plan_scope(query)
        if scope:
            return {"mode": "plan", "scope": scope, "note": "Plan inferred after invalid LLM response."}
        if raw:
            answer = raw
        else:
            answer = (last_error or "Model response could not be parsed.") + "\n\n" + prepared.context
        return {"mode": "answer", "answer": answer, "sources": [h.path for h in prepared.hits]}

    mode = payload.get("mode")
    plan_scope = _infer_plan_scope(query)
    if plan_scope and mode == "answer":
        return {"mode": "plan", "scope": plan_scope, "note": "Plan inferred from user request."}
    if mode not in {"answer", "plan", "actions"}:
        return {
            "mode": "answer",
            "answer": str(payload.get("answer", raw)),
            "sources": [h.path for h in prepared.hits],
        }

    if mode == "answer" and not isinstance(payload.get("sources"), list):
        payload["sources"] = [h.path for h in prepared.hits]
    if mode == "plan" and payload.get("scope") not in VALID_PLAN_SCOPES:
        payload["scope"] = "today"
    if mode == "actions":
        actions = payload.get("actions", [])
        if isinstance(actions, list):
            actions = [a for a in actions if str(a.get("type", "")).strip() not in READ_ONLY_TOOLS]
            payload["actions"] = _sanitize_actions(actions, query)
    return payload


def run_chat(ws: Workspace, *, query: str) -> str:
    prepared = _prepare_chat_request(ws, query=query)
    if not prepared.llm_ready:
        scope = _infer_plan_scope(query)
        if scope:
            return build_plan(ws, mode=scope).render().plain
        return (
            "LLM not configured (set OPENROUTER_API_KEY). Here are the most relevant excerpts:\n\n"
            + prepared.context
        )

    audit_steps: list[dict[str, Any]] = []
    payload, raw, messages, last_error = _resolve_payload_with_tools(
        ws, prepared, audit_steps=audit_steps
    )
    if audit_steps:
        write_tool_audit(
            ws,
            run_type="chat",
            payload={
                "query": query,
                "model": prepared.completion_kwargs.get("model") if prepared.completion_kwargs else None,
                "resolved_mode": payload.get("mode") if isinstance(payload, dict) else None,
                "error": last_error,
                "steps": audit_steps,
            },
        )
    if payload is None:
        scope = _infer_plan_scope(query)
        if scope:
            return build_plan(ws, mode=scope).render().plain
        if raw:
            return raw
        return (last_error or "Model response could not be parsed.") + "\n\n" + prepared.context

    plan_scope = _infer_plan_scope(query)
    if plan_scope and payload.get("mode") == "answer":
        return build_plan(ws, mode=plan_scope).render().plain

    if payload.get("mode") == "plan":
        scope = payload.get("scope")
        if scope not in VALID_PLAN_SCOPES:
            scope = "today"
        return build_plan(ws, mode=scope).render().plain

    if payload.get("mode") == "actions":
        actions = payload.get("actions", [])
        if not isinstance(actions, list):
            return "Model proposed invalid actions."
        actions = [a for a in actions if str(a.get("type", "")).strip() not in READ_ONLY_TOOLS]
        actions = _sanitize_actions(actions, query)
        try:
            result = apply_actions(ws, actions, require_approval=True)
        except Exception as e:
            if not prepared.completion_kwargs:
                return f"Failed to apply actions: {e}"
            # Give the model one chance to correct invalid actions.
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "error": "The proposed actions failed validation or could not be applied.",
                            "details": str(e),
                            "instruction": "Propose a corrected set of actions. Reply with ONLY the JSON object.",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            try:
                resp2 = completion(
                    **{k: v for k, v in prepared.completion_kwargs.items() if k != "messages"},
                    messages=messages,
                )
                raw2 = resp2["choices"][0]["message"]["content"]
                payload2 = parse_agent_json(raw2)
                if payload2.get("mode") == "actions" and isinstance(payload2.get("actions"), list):
                    result2 = apply_actions(ws, payload2["actions"], require_approval=True)
                    return f"{payload2.get('note','')}\n\n{result2}".strip()
                if payload2.get("mode") == "answer":
                    return str(payload2.get("answer", raw2))
                return raw2
            except Exception as e2:
                return f"Failed to apply actions: {e}\nRetry failed: {e2}"
        return f"{payload.get('note','')}\n\n{result}".strip()

    return str(payload.get("answer", raw))
