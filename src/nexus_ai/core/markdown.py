from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import yaml


@dataclass(frozen=True)
class FrontMatterDoc:
    front_matter: dict[str, Any]
    body: str


def split_front_matter(markdown: str) -> FrontMatterDoc:
    text = markdown.lstrip("\ufeff")
    # Allow leading whitespace/newlines before front matter for robustness.
    if not text.lstrip().startswith("---\n"):
        return FrontMatterDoc(front_matter={}, body=markdown)

    text = text.lstrip()
    end = text.find("\n---\n", 4)
    if end == -1:
        return FrontMatterDoc(front_matter={}, body=markdown)

    fm_text = text[4:end]
    body = text[end + 5 :]
    try:
        fm = yaml.safe_load(fm_text) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    return FrontMatterDoc(front_matter=fm, body=body.lstrip("\n"))


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_minimal_front_matter(
    markdown_body: str,
    *,
    doc_type: str,
    title: str,
    status: str = "active",
    tags: list[str] | None = None,
    created: str | None = None,
    updated: str | None = None,
) -> str:
    created_ts = created or now_iso_utc()
    updated_ts = updated or created_ts
    fm: dict[str, Any] = {
        "type": doc_type,
        "title": title,
        "created": created_ts,
        "updated": updated_ts,
        "status": status,
    }
    if tags is not None:
        fm["tags"] = tags

    fm_text = yaml.safe_dump(fm, sort_keys=False).strip()
    return f"---\n{fm_text}\n---\n\n{markdown_body.rstrip()}\n"
