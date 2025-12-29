from __future__ import annotations

import json
import os
from dataclasses import dataclass

from litellm import completion

from nexus_ai.core.agent_actions import ActionError, parse_agent_json
from nexus_ai.core.config import LlmConfig, resolve_llm_settings


@dataclass(frozen=True)
class EnrichResult:
    title: str | None
    doc_type: str | None
    tags: list[str] | None
    markdown_body: str | None


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    return text if len(text) <= max_chars else text[:max_chars]


def enrich_markdown(
    *,
    llm: LlmConfig,
    filename: str,
    source_hint: str,
    extracted_text: str,
    extracted_kind: str,
) -> EnrichResult:
    """
    Optional, best-effort enrichment:
    - clean up extracted text into nicer Markdown
    - infer title/type/tags

    Returns partial fields on failure; callers should fall back safely.
    """

    if not llm.enrich_enabled:
        return EnrichResult(title=None, doc_type=None, tags=None, markdown_body=None)

    llm_settings = resolve_llm_settings(llm)
    api_key = os.getenv(llm_settings["api_key_env"]) if llm_settings.get("api_key_env") else None
    if not api_key and not llm_settings["model"].startswith("ollama/"):
        return EnrichResult(title=None, doc_type=None, tags=None, markdown_body=None)

    # Prefer a cheaper enrichment model if configured; fall back to primary model.
    enrich_model = llm.enrich_model or llm.model
    if "/" not in enrich_model:
        enrich_model = f"{llm.provider}/{enrich_model}"
    if not enrich_model.startswith(("openrouter/", "openai/", "ollama/")):
        enrich_model = f"{llm.provider}/{enrich_model}"

    max_chars = int(llm.enrich_max_chars)
    clipped = _clip(extracted_text, max_chars=max_chars)

    system = """
You are a careful assistant that prepares durable Markdown notes.

Return ONLY a single JSON object with this schema:
{
  "title": "string (short, human-friendly)",
  "type": "note|project|reference|log|contact|other",
  "tags": ["tag", "..."],
  "markdown_body": "markdown content without YAML front matter"
}

Rules:
- Do NOT summarize away important details. Preserve information.
- Improve formatting: headings, bullets, spacing, remove obvious extraction noise.
- Keep markdown_body reasonably short if the extracted text is huge: keep the most relevant content and include a note that content was truncated.
- Tags should be few (0-6), lowercase, and reflect the content (e.g., taxes, home, contract).
"""

    user = {
        "filename": filename,
        "source_hint": source_hint,
        "extracted_kind": extracted_kind,
        "text": clipped,
        "max_chars": max_chars,
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
        return EnrichResult(title=None, doc_type=None, tags=None, markdown_body=None)

    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    doc_type = payload.get("type") if isinstance(payload.get("type"), str) else None
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else None
    if tags is not None:
        tags = [str(t).lower() for t in tags][:6]
    md = payload.get("markdown_body") if isinstance(payload.get("markdown_body"), str) else None
    return EnrichResult(title=title, doc_type=doc_type, tags=tags, markdown_body=md)
