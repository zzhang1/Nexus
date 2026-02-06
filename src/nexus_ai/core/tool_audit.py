from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

from nexus_ai.core.workspace import Workspace


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_audit_file(
    ws: Workspace,
    *,
    prefix: str,
    payload: dict[str, Any],
) -> Path:
    logs_dir = ws.paths.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp_slug()
    suffix = uuid4().hex[:8]
    filename = f"{prefix}_{stamp}_{suffix}.json"
    path = logs_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_tool_audit(ws: Workspace, *, run_type: str, payload: dict[str, Any]) -> Path:
    """
    Write a JSON audit log for tool usage under .assistant/logs/.
    """
    data = dict(payload)
    data.setdefault("run_type", run_type)
    data.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    return _write_audit_file(ws, prefix=f"tool_audit_{run_type}", payload=data)


def write_action_audit(ws: Workspace, *, action_type: str, payload: dict[str, Any]) -> Path:
    """
    Write a JSON audit log for non-tool actions (for example integration writes).
    """

    data = dict(payload)
    data.setdefault("action_type", action_type)
    data.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    return _write_audit_file(ws, prefix=f"action_audit_{action_type}", payload=data)
