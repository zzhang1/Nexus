from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from litellm import completion

from nexus_ai.core.agent_actions import ActionError, apply_actions, parse_agent_json
from nexus_ai.core.config import load_config, resolve_llm_settings
from nexus_ai.core.runtime import ensure_litellm_quiet
from nexus_ai.core.workspace import Workspace


@dataclass(frozen=True)
class FileMeta:
    path: str
    mtime: float
    size: int


def _collect_file_meta(ws: Workspace, limit: int = 120) -> list[FileMeta]:
    items: list[FileMeta] = []
    for p in ws.paths.knowledge_dir.rglob("*.md"):
        if ".git" in p.parts or p.name.startswith("."):
            continue
        rel = p.relative_to(ws.paths.knowledge_dir).as_posix()
        stat = p.stat()
        items.append(FileMeta(path=rel, mtime=stat.st_mtime, size=stat.st_size))
        if len(items) >= limit:
            break
    return items


def _collect_stale_files(ws: Workspace, *, days: int, limit: int = 120) -> list[FileMeta]:
    cutoff = (datetime.now().timestamp() - days * 86400)
    items: list[FileMeta] = []
    for p in ws.paths.knowledge_dir.rglob("*.md"):
        if ".git" in p.parts or p.name.startswith("."):
            continue
        stat = p.stat()
        if stat.st_mtime > cutoff:
            continue
        rel = p.relative_to(ws.paths.knowledge_dir).as_posix()
        items.append(FileMeta(path=rel, mtime=stat.st_mtime, size=stat.st_size))
        if len(items) >= limit:
            break
    return items


def run_tidy(ws: Workspace, *, focus: str | None = None, stale_days: int | None = None) -> str:
    cfg = load_config(ws.paths.config_yaml)
    ensure_litellm_quiet()
    llm_settings = resolve_llm_settings(cfg.llm)
    api_key = os.getenv(llm_settings["api_key_env"]) if llm_settings.get("api_key_env") else None
    if not api_key and not llm_settings["model"].startswith("ollama/"):
        return "LLM not configured (set OPENROUTER_API_KEY)."

    knowledge_folders = []
    for p in sorted(ws.paths.knowledge_dir.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            knowledge_folders.append(p.name + "/")

    files = _collect_file_meta(ws)
    stale_files = _collect_stale_files(ws, days=stale_days, limit=60) if stale_days else []

    system = """
You are Nexus AI's cleanup assistant. Your job is to keep Knowledge/ organized and tidy.

You MUST respond with a single JSON object (no extra text).

If you only have suggestions, respond:
{
  "mode": "answer",
  "answer": "short advice / questions",
  "sources": ["relative/path.md", "..."]
}

If you propose edits, respond:
{
  "mode": "actions",
  "note": "short explanation",
  "actions": [
    {"type": "move_file", "from": "...", "to": "..."}
  ]
}

Rules:
- Keep changes minimal; do not invent facts.
- Prefer reorganizing existing files over creating new ones.
- When stale_files are provided, ONLY propose move_file actions to 4_Archive/.
- If unsure, ask a clarification question in answer mode.
- Limit to at most 5 actions.
"""

    user = {
        "focus": focus or "",
        "knowledge_folders": knowledge_folders[:40],
        "files": [f.__dict__ for f in files],
        "stale_files": [f.__dict__ for f in stale_files],
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
    raw = ""
    payload: dict | None = None
    last_error: str | None = None
    for attempt in range(3):
        resp = completion(
            **{k: v for k, v in completion_kwargs.items() if k != "messages"},
            messages=messages,
        )
        raw = resp["choices"][0]["message"]["content"]
        try:
            payload = parse_agent_json(raw)
            break
        except ActionError as e:
            last_error = str(e)
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

    if payload is None:
        return raw if raw else (last_error or "Model response could not be parsed.")

    if payload.get("mode") == "actions":
        actions = payload.get("actions", [])
        if not isinstance(actions, list):
            return "Model proposed invalid actions."
        if stale_days:
            for action in actions:
                if action.get("type") != "move_file":
                    return "Tidy for stale notes only supports move_file actions to 4_Archive/."
                dest = str(action.get("to", ""))
                if not dest.startswith("4_Archive/"):
                    return "Stale-note tidy must move files under 4_Archive/."
        try:
            result = apply_actions(ws, actions, require_approval=True)
        except Exception as e:
            return f"Failed to apply actions: {e}"
        return f"{payload.get('note','')}\n\n{result}".strip()

    return str(payload.get("answer", raw))
