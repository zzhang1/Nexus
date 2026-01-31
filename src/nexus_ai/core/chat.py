from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from litellm import completion

from nexus_ai.core.agent_actions import ActionError, apply_actions, parse_agent_json
from nexus_ai.core.config import load_config, resolve_llm_settings
from nexus_ai.core.db import NexusDb
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
    {"type": "move_file", "from": "3_Resources/Old.md", "to": "3_Resources/New.md"},
    {"type": "delete_file", "path": "4_Archive/Old.md"}
  ]
}

Rules:
- All paths must be relative to Knowledge/ and must not start with '.' or contain '..'.
- Prefer append_task for "add a task" requests. Put tasks under a '## Tasks' section (Nexus will create if missing).
- If a relevant file already exists, choose it from knowledge_files or candidate_files instead of creating a new one.
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


def _run_llm(prepared: ChatPrepared) -> tuple[dict | None, str, list[dict[str, str]], str | None]:
    if not prepared.llm_ready or not prepared.completion_kwargs or not prepared.messages:
        return None, "", [], "LLM not configured."

    messages = list(prepared.messages)
    raw = ""
    payload: dict | None = None
    last_error: str | None = None
    for _attempt in range(3):
        resp = completion(
            **{k: v for k, v in prepared.completion_kwargs.items() if k != "messages"},
            messages=messages,
        )
        raw = resp["choices"][0]["message"]["content"]
        try:
            payload = parse_agent_json(raw)
            break
        except ActionError as e:
            last_error = str(e)
            # Ask the model to try again with strict JSON only.
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
    return payload, raw, messages, last_error


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

    payload, raw, _messages, last_error = _run_llm(prepared)
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
    return payload


def run_chat(ws: Workspace, *, query: str) -> str:
    prepared = _prepare_chat_request(ws, query=query)
    if not prepared.llm_ready:
        return (
            "LLM not configured (set OPENROUTER_API_KEY). Here are the most relevant excerpts:\n\n"
            + prepared.context
        )

    payload, raw, messages, last_error = _run_llm(prepared)
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
