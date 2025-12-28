from __future__ import annotations

import os
from pathlib import Path

from litellm import completion

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
    if not hits:
        return "No relevant context found in Knowledge/. Try `nexus ingest` or `nexus sync`."

    context_lines: list[str] = []
    for h in hits:
        context_lines.append(f"FILE: {h['path']}\n{h['content']}".strip())
    context = "\n\n---\n\n".join(context_lines)

    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        # Offline-ish fallback: show retrieved chunks.
        return (
            "LLM not configured (set OPENROUTER_API_KEY). Here are the most relevant excerpts:\n\n"
            + context
        )

    # Let litellm pick up provider auth from env vars.
    from nexus_ai.core.config import load_config

    cfg = load_config(ws.paths.config_yaml)
    resp = completion(
        model=cfg.llm.model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Nexus AI. Answer using only the provided context when possible. "
                    "If you infer, say so. When referencing facts, cite the FILE paths."
                ),
            },
            {"role": "user", "content": f"Question: {query}\n\nContext:\n{context}"},
        ],
    )
    return resp["choices"][0]["message"]["content"]
