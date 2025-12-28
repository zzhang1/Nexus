from __future__ import annotations

import os
from pathlib import Path

import json

from litellm import completion

from nexus_ai.core.agent_actions import ActionError, apply_actions, parse_agent_json
from nexus_ai.core.config import load_config, resolve_llm_settings
from nexus_ai.core.db import NexusDb
from nexus_ai.core.planner import build_plan
from nexus_ai.core.workspace import Workspace


def _looks_like_planning(query: str) -> str | None:
    q = query.lower().strip()
    if "today" in q:
        return "today"
    if "this week" in q or "week" in q:
        return "week"
    if "this month" in q or "month" in q:
        return "month"
    if "what should i do" in q:
        return "today"
    return None


def run_chat(ws: Workspace, *, query: str) -> str:
    mode = _looks_like_planning(query)
    if mode:
        return build_plan(ws, mode=mode).render().plain

    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    hits = db.search_chunks(query, limit=8)
    context_lines: list[str] = []
    for h in hits:
        context_lines.append(f"FILE: {h['path']}\n{h['content']}".strip())
    context = "\n\n---\n\n".join(context_lines).strip()

    # If we have no indexed context, still allow "write intent" planning.
    if not context:
        context = "(No indexed context found.)"

    cfg = load_config(ws.paths.config_yaml)
    llm_settings = resolve_llm_settings(cfg.llm)
    api_key = os.getenv(llm_settings["api_key_env"]) if llm_settings.get("api_key_env") else None
    if not api_key and not llm_settings["model"].startswith("ollama/"):
        # Offline-ish fallback: show retrieved chunks.
        return (
            "LLM not configured (set OPENROUTER_API_KEY). Here are the most relevant excerpts:\n\n"
            + context
        )

    # Provide the model a small view of the territory.
    knowledge_subdirs = []
    for p in sorted(ws.paths.knowledge_dir.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            knowledge_subdirs.append(p.name + "/")
    candidate_files = [h["path"] for h in hits]

    system = """
You are Nexus AI, a personal assistant that can read AND propose safe edits to the user's Knowledge/ markdown library.

You MUST respond with a single JSON object (no extra text).

If the user request is informational, respond:
{
  "mode": "answer",
  "answer": "...",
  "sources": ["relative/path.md", "..."]
}

If the user request requires updating Knowledge/, respond:
{
  "mode": "actions",
  "note": "short explanation",
  "actions": [
    {"type": "append_task", "path": "2_Areas/Home/Home.md", "task": "- [ ] ... due:YYYY-MM-DD p:P2", "create_if_missing": true},
    {"type": "create_file", "path": "3_Resources/...", "content": "..."},
    {"type": "replace_file", "path": "2_Areas/...", "content": "..."},
    {"type": "move_file", "from": "3_Resources/Old.md", "to": "3_Resources/New.md"},
    {"type": "delete_file", "path": "4_Archive/Old.md"}
  ]
}

Rules:
- All paths must be relative to Knowledge/ and must not start with '.' or contain '..'.
- Prefer append_task for "add a task" requests. Put tasks under a '## Tasks' section (Nexus will create if missing).
- Keep changes minimal and do not invent facts. If you need clarification, ask as an answer instead of acting.
"""

    user = {
        "query": query,
        "knowledge_folders": knowledge_subdirs[:40],
        "candidate_files": candidate_files[:12],
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

    resp = completion(
        **completion_kwargs,
    )
    raw = resp["choices"][0]["message"]["content"]
    try:
        payload = parse_agent_json(raw)
    except ActionError:
        # If the model didn't follow protocol, fall back to raw.
        return raw

    if payload.get("mode") == "actions":
        actions = payload.get("actions", [])
        if not isinstance(actions, list):
            return "Model proposed invalid actions."
        try:
            result = apply_actions(ws, actions, require_approval=True)
        except Exception as e:
            return f"Failed to apply actions: {e}"
        return f"{payload.get('note','')}\n\n{result}".strip()

    return str(payload.get("answer", raw))
