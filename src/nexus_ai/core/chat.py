from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from litellm import completion

from nexus_ai.core.agent_actions import ActionError, apply_actions, parse_agent_json
from nexus_ai.core.config import load_config, resolve_llm_settings
from nexus_ai.core.db import NexusDb
from nexus_ai.core.knowledge_access import KnowledgeAccess
from nexus_ai.core.map_store import get_map_store
from nexus_ai.core.planner import build_plan
from nexus_ai.core.runtime import ensure_litellm_quiet
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class ChatPrepared:
    hits: list[Any]
    context: str
    llm_ready: bool
    completion_kwargs: dict[str, Any] | None
    messages: list[dict[str, str]] | None


TOOL_ACTIONS = {"search", "read_file", "find_files"}


def _json_fallback(obj: Any) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


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

    system = """
You are Nexus AI, a personal assistant that can read AND propose safe edits to the user's Knowledge/ markdown library.

You MUST respond with a single JSON object (no extra text).

If the user request is informational, respond:
{
  "mode": "answer",
  "answer": "...",
  "sources": ["relative/path.md", "..."]
}

If the user asks what to do today/this week/this month or asks for a plan, respond:
{
  "mode": "plan",
  "scope": "today|week|month",
  "note": "short rationale"
}

If the user request requires updating Knowledge/, respond:
{
  "mode": "actions",
  "note": "short explanation",
  "actions": [
    {"type": "append_task", "path": "2_Areas/Home/Home.md", "task": "- [ ] ... due:YYYY-MM-DD p:P1", "create_if_missing": true},
    {"type": "create_file", "path": "3_Resources/...", "content": "..."},
    {"type": "replace_file", "path": "2_Areas/...", "content": "..."},
    {"type": "edit_block", "path": "2_Areas/...", "old": "exact block", "new": "replacement block"},
    {"type": "move_file", "from": "3_Resources/Old.md", "to": "3_Resources/New.md"},
    {"type": "delete_file", "path": "4_Archive/Old.md"}
  ]
}

To fetch information before editing, use tool actions (return ONLY tool actions in that step):
{"type": "search", "query": "...", "limit": 8}
{"type": "find_files", "query": "keyword", "limit": 20}
{"type": "read_file", "path": "2_Areas/Home/Home.md", "max_chars": 4000}

Rules:
- All paths must be relative to Knowledge/ and must not start with '.' or contain '..'.
- Prefer append_task for "add a task" requests. Put tasks under a '## Tasks' section (Nexus will create if missing).
- If a relevant file already exists, choose it from knowledge_files or candidate_files instead of creating a new one.
- If you need to edit a specific section, first read the file, then use edit_block with the exact text to replace.
- If you need to discover files or context, return only tool actions first. After tool results, return final actions (no tool actions) or a plan/answer.
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
    }
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
    for _attempt in range(3):
        resp = completion(
            **{k: v for k, v in completion_kwargs.items() if k != "messages"},
            messages=working_messages,
        )
        raw = resp["choices"][0]["message"]["content"]
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


def _execute_tool_actions(ws: Workspace, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    access = KnowledgeAccess(ws)
    results: list[dict[str, Any]] = []
    for action in actions:
        t = str(action.get("type", "")).strip()
        if t == "search":
            query = str(action.get("query", "")).strip()
            limit = int(action.get("limit", 8) or 8)
            try:
                hits = access.search(query, limit=limit)
                results.append(
                    {
                        "type": "search",
                        "query": query,
                        "results": [
                            {"path": h.path, "snippet": h.snippet, "score": h.score} for h in hits
                        ],
                    }
                )
            except Exception as exc:
                results.append({"type": "search", "query": query, "error": str(exc)})
        elif t == "find_files":
            query = str(action.get("query", "")).strip()
            limit = int(action.get("limit", 25) or 25)
            try:
                matches = access.find_files(query, limit=limit)
                results.append({"type": "find_files", "query": query, "results": matches})
            except Exception as exc:
                results.append({"type": "find_files", "query": query, "error": str(exc)})
        elif t == "read_file":
            path = str(action.get("path", "")).strip()
            max_chars = int(action.get("max_chars", 8000) or 8000)
            try:
                read = access.read_file(path, max_chars=max_chars)
                results.append(
                    {
                        "type": "read_file",
                        "path": read.path,
                        "front_matter": read.front_matter,
                        "content": read.content,
                        "truncated": read.truncated,
                    }
                )
            except Exception as exc:
                results.append({"type": "read_file", "path": path, "error": str(exc)})
    return results


def _resolve_payload_with_tools(
    ws: Workspace, prepared: ChatPrepared, *, max_steps: int = 10
) -> tuple[dict | None, str, list[dict[str, str]], str | None]:
    if not prepared.llm_ready or not prepared.completion_kwargs or not prepared.messages:
        return None, "", [], "LLM not configured."

    messages = list(prepared.messages)
    raw = ""
    last_error: str | None = None
    for _step in range(max_steps):
        payload, raw, messages, last_error = _run_llm_with_messages(
            prepared.completion_kwargs, messages
        )
        if payload is None:
            return None, raw, messages, last_error
        mode = payload.get("mode")
        tool_actions: list[dict[str, Any]] = []

        if isinstance(payload, dict) and str(payload.get("type", "")).strip() in TOOL_ACTIONS:
            tool_actions = [payload]
        elif isinstance(payload, dict) and isinstance(payload.get("actions"), list):
            actions = payload.get("actions", [])
            tool_actions = [
                a for a in actions if str(a.get("type", "")).strip() in TOOL_ACTIONS
            ]
            if mode != "actions" and not tool_actions:
                return payload, raw, messages, None
        elif mode != "actions":
            return payload, raw, messages, None

        if mode == "actions" and not tool_actions:
            return payload, raw, messages, None

        if not tool_actions:
            return payload, raw, messages, None

        tool_results = _execute_tool_actions(ws, tool_actions)
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "tool_results": tool_results,
                        "instruction": "Use these tool results. Reply with ONLY a single JSON object. Do not include tool actions unless you still need more data.",
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
        return {
            "mode": "answer",
            "answer": "LLM not configured (set OPENROUTER_API_KEY). Here are the most relevant excerpts:\n\n"
            + prepared.context,
            "sources": sources,
        }

    payload, raw, _messages, last_error = _resolve_payload_with_tools(ws, prepared)
    if payload is None:
        answer = raw if raw else (last_error or "Model response could not be parsed.")
        return {"mode": "answer", "answer": answer, "sources": [h.path for h in prepared.hits]}

    mode = payload.get("mode")
    if mode not in {"answer", "plan", "actions"}:
        return {
            "mode": "answer",
            "answer": str(payload.get("answer", raw)),
            "sources": [h.path for h in prepared.hits],
        }

    if mode == "answer" and not isinstance(payload.get("sources"), list):
        payload["sources"] = [h.path for h in prepared.hits]
    if mode == "actions":
        actions = payload.get("actions", [])
        if isinstance(actions, list):
            payload["actions"] = [a for a in actions if str(a.get("type", "")).strip() not in TOOL_ACTIONS]
    return payload


def run_chat(ws: Workspace, *, query: str) -> str:
    prepared = _prepare_chat_request(ws, query=query)
    if not prepared.llm_ready:
        return (
            "LLM not configured (set OPENROUTER_API_KEY). Here are the most relevant excerpts:\n\n"
            + prepared.context
        )

    payload, raw, messages, last_error = _resolve_payload_with_tools(ws, prepared)
    if payload is None:
        return raw if raw else (last_error or "Model response could not be parsed.")

    if payload.get("mode") == "plan":
        scope = payload.get("scope")
        if scope not in {"today", "week", "month"}:
            scope = "today"
        return build_plan(ws, mode=scope).render().plain

    if payload.get("mode") == "actions":
        actions = payload.get("actions", [])
        if not isinstance(actions, list):
            return "Model proposed invalid actions."
        actions = [a for a in actions if str(a.get("type", "")).strip() not in TOOL_ACTIONS]
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
