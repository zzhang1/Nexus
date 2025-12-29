from __future__ import annotations

from pathlib import Path

import typer

from nexus_ai.core.workspace import Workspace


def workspace_from_ctx(ctx: typer.Context, root: Path | None) -> Workspace:
    """
    Resolve a Workspace from either an explicit --root on the command, or the global --root.
    """

    if root is not None:
        return Workspace.from_optional_root(root)
    ctx_root = None
    if ctx is not None and isinstance(ctx.obj, dict):
        ctx_root = ctx.obj.get("root")
    return Workspace.from_optional_root(ctx_root)

