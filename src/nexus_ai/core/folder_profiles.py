from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FolderDefaults:
    tags: tuple[str, ...] = ()


def _load_profile(path: Path) -> FolderDefaults:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return FolderDefaults()
    if not isinstance(raw, dict):
        return FolderDefaults()
    defaults = raw.get("defaults", {}) or {}
    if not isinstance(defaults, dict):
        return FolderDefaults()
    tags = defaults.get("tags", []) or []
    if not isinstance(tags, list):
        tags = []
    tags = tuple(str(t) for t in tags)
    return FolderDefaults(tags=tags)


def infer_folder_defaults(file_path: Path, knowledge_root: Path) -> FolderDefaults:
    """
    Walk upward from file_path.parent to knowledge_root and merge any .nexus.yaml defaults.
    Nearest profile wins (tags are unioned, but nearer comes first).
    """

    merged: list[str] = []
    current = file_path.parent
    knowledge_root = knowledge_root.resolve()
    for parent in [current, *current.parents]:
        if parent == knowledge_root.parent:
            break
        profile = parent / ".nexus.yaml"
        if profile.exists() and profile.is_file():
            defaults = _load_profile(profile)
            for tag in defaults.tags:
                if tag not in merged:
                    merged.append(tag)
        if parent == knowledge_root:
            break
    return FolderDefaults(tags=tuple(merged))

