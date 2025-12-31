from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.tidy import run_tidy

console = Console()


def tidy(
    ctx: typer.Context,
    focus: str = typer.Option(None, "--focus", "-f", help="Optional focus area (e.g., 'home', 'work', 'finances')."),
    stale_days: int = typer.Option(
        None,
        "--stale-days",
        help="Suggest archiving notes not modified in N days.",
    ),
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    """
    Suggest and apply Knowledge/ cleanup actions (rename/move/archive), with approval.
    """

    ws = workspace_from_ctx(ctx, root)
    answer = run_tidy(ws, focus=focus, stale_days=stale_days)
    console.print(answer)
