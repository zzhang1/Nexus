from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from nexus_ai.core.integrations import CAPABILITY_SPECS


class ProtocolError(RuntimeError):
    pass


VALID_MODES = {"answer", "plan", "actions", "tool"}
VALID_PLAN_SCOPES = {"today", "week", "month"}

ACTION_TYPES = {
    "append_task",
    "create_file",
    "replace_file",
    "edit_block",
    "move_file",
    "delete_file",
}

TOOL_TYPES = {
    spec.capability for spec in CAPABILITY_SPECS if spec.surface == "llm_tool" and spec.implemented
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]
    example_args: dict[str, Any]


TOOL_SPECS: dict[str, ToolSpec] = {
    "search": ToolSpec(
        name="search",
        description="Search indexed Knowledge/ content (local search, not the web).",
        args={"query": "string (required)", "limit": "int (optional, default 8)"},
        example_args={"query": "tax filing", "limit": 8},
    ),
    "find_files": ToolSpec(
        name="find_files",
        description="Find files by path substring within Knowledge/.",
        args={"query": "string (required)", "limit": "int (optional, default 25)"},
        example_args={"query": "Taxes", "limit": 20},
    ),
    "list_files": ToolSpec(
        name="list_files",
        description="List files under Knowledge/ (optionally scoped).",
        args={
            "root": 'string (optional, default "Knowledge/")',
            "recursive": "bool (optional, default true)",
            "limit": "int (optional, default 1000)",
            "extensions": 'list of strings (optional, default [".md"])',
            "include_hidden": "bool (optional, default false)",
        },
        example_args={
            "root": "Knowledge/",
            "recursive": True,
            "limit": 200,
            "extensions": [".md"],
            "include_hidden": False,
        },
    ),
    "read_file": ToolSpec(
        name="read_file",
        description="Read a file from Knowledge/.",
        args={"path": "string (required)", "max_chars": "int (optional, default 4000)"},
        example_args={"path": "2_Areas/Home/Home.md", "max_chars": 4000},
    ),
}


def tool_prompt_block() -> str:
    lines: list[str] = []
    lines.append("Read-only tools (use mode='tool'):")
    for spec in TOOL_SPECS.values():
        example = json.dumps(spec.example_args, ensure_ascii=False)
        lines.append(f"- {spec.name}: {spec.description}")
        lines.append(f"  args example: {example}")
    return "\n".join(lines)


def parse_json_object(text: str) -> dict[str, Any]:
    """
    Extract and parse a JSON object from an LLM response.
    """

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        raise ProtocolError("Top-level JSON must be an object.")
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ProtocolError("Model response did not contain JSON.")
    snippet = text[start : end + 1]
    try:
        obj = json.loads(snippet)
    except Exception as exc:
        raise ProtocolError(f"Failed to parse JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("Top-level JSON must be an object.")
    return obj


def extract_tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize tool calls from either the new schema or legacy shapes.
    """

    if not isinstance(payload, dict):
        return []

    mode = str(payload.get("mode", "")).strip().lower()
    raw_calls: list[dict[str, Any]] = []

    if mode == "tool":
        calls = payload.get("tool_calls")
        if isinstance(calls, list):
            raw_calls = [c for c in calls if isinstance(c, dict)]
    elif isinstance(payload.get("tool_calls"), list):
        raw_calls = [c for c in payload.get("tool_calls") if isinstance(c, dict)]
    elif str(payload.get("type", "")).strip() in TOOL_TYPES:
        raw_calls = [payload]
    elif isinstance(payload.get("actions"), list):
        raw_calls = [
            a
            for a in payload.get("actions")
            if isinstance(a, dict) and str(a.get("type", "")).strip() in TOOL_TYPES
        ]

    return raw_calls


def normalize_tool_calls(
    raw_calls: Iterable[dict[str, Any]],
    *,
    allowed_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = allowed_types or TOOL_TYPES
    calls: list[dict[str, Any]] = []
    for idx, call in enumerate(raw_calls):
        if not isinstance(call, dict):
            continue
        tool_type = str(call.get("type", "")).strip()
        if tool_type not in allowed:
            continue
        call_id = str(call.get("id") or f"tool_{idx + 1}")
        args = call.get("args")
        if not isinstance(args, dict):
            args = {k: v for k, v in call.items() if k not in {"id", "type", "args"}}
        calls.append({"id": call_id, "type": tool_type, "args": args})
    return calls
