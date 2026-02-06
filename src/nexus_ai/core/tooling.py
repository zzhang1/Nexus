from __future__ import annotations

from typing import Any

from nexus_ai.core.config import load_config
from nexus_ai.core.integrations import IntegrationRegistry
from nexus_ai.core.knowledge_access import KnowledgeAccess
from nexus_ai.core.llm_protocol import TOOL_TYPES, normalize_tool_calls
from nexus_ai.core.workspace import Workspace


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return default


def _coerce_extensions(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return None


def execute_tool_calls(ws: Workspace, raw_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    access = KnowledgeAccess(ws)
    cfg = load_config(ws.paths.config_yaml)
    registry = IntegrationRegistry(cfg)
    allowed_types = registry.allowed_llm_tools()
    calls = normalize_tool_calls(raw_calls, allowed_types=TOOL_TYPES)
    results: list[dict[str, Any]] = []

    for call in calls:
        call_id = str(call.get("id"))
        tool_type = str(call.get("type"))
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        if tool_type not in allowed_types:
            results.append(
                {
                    "id": call_id,
                    "type": tool_type,
                    "ok": False,
                    "error": "Tool not available for current integration mode/config.",
                }
            )
            continue

        if tool_type == "search":
            query = str(args.get("query", "")).strip()
            limit = _coerce_int(args.get("limit", 8), 8)
            if not query:
                results.append(
                    {"id": call_id, "type": tool_type, "ok": False, "error": "Missing query."}
                )
                continue
            try:
                hits = access.search(query, limit=limit)
                results.append(
                    {
                        "id": call_id,
                        "type": tool_type,
                        "ok": True,
                        "result": {
                            "query": query,
                            "results": [
                                {"path": h.path, "snippet": h.snippet, "score": h.score} for h in hits
                            ],
                        },
                    }
                )
            except Exception as exc:
                results.append(
                    {"id": call_id, "type": tool_type, "ok": False, "error": str(exc)}
                )
        elif tool_type == "find_files":
            query = str(args.get("query", "")).strip()
            limit = _coerce_int(args.get("limit", 25), 25)
            if not query:
                results.append(
                    {"id": call_id, "type": tool_type, "ok": False, "error": "Missing query."}
                )
                continue
            try:
                matches = access.find_files(query, limit=limit)
                results.append(
                    {
                        "id": call_id,
                        "type": tool_type,
                        "ok": True,
                        "result": {"query": query, "results": matches},
                    }
                )
            except Exception as exc:
                results.append(
                    {"id": call_id, "type": tool_type, "ok": False, "error": str(exc)}
                )
        elif tool_type == "list_files":
            root = args.get("root")
            recursive = _coerce_bool(args.get("recursive", True), True)
            limit = _coerce_int(args.get("limit", 1000), 1000)
            extensions = _coerce_extensions(args.get("extensions"))
            include_hidden = _coerce_bool(args.get("include_hidden", False), False)
            try:
                files = access.list_files(
                    root=str(root) if root is not None else None,
                    recursive=recursive,
                    limit=limit,
                    extensions=extensions,
                    include_hidden=include_hidden,
                )
                results.append(
                    {
                        "id": call_id,
                        "type": tool_type,
                        "ok": True,
                        "result": {
                            "root": root or "Knowledge/",
                            "recursive": recursive,
                            "results": files,
                        },
                    }
                )
            except Exception as exc:
                results.append(
                    {"id": call_id, "type": tool_type, "ok": False, "error": str(exc)}
                )
        elif tool_type == "read_file":
            path = str(args.get("path", "")).strip()
            max_chars = _coerce_int(args.get("max_chars", 8000), 8000)
            if not path:
                results.append(
                    {"id": call_id, "type": tool_type, "ok": False, "error": "Missing path."}
                )
                continue
            try:
                read = access.read_file(path, max_chars=max_chars)
                results.append(
                    {
                        "id": call_id,
                        "type": tool_type,
                        "ok": True,
                        "result": {
                            "path": read.path,
                            "front_matter": read.front_matter,
                            "content": read.content,
                            "truncated": read.truncated,
                        },
                    }
                )
            except Exception as exc:
                results.append(
                    {"id": call_id, "type": tool_type, "ok": False, "error": str(exc)}
                )
        else:
            results.append(
                {"id": call_id, "type": tool_type, "ok": False, "error": "Unknown tool."}
            )

    return results
