from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.sync import sync_knowledge
from nexus_ai.core.workspace import Workspace

console = Console()


def sync(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r", help="Workspace root (defaults to current directory)."),
) -> None:
    """
    Re-scan Knowledge/ for changes and update the local index idempotently.
    """

    ws = workspace_from_ctx(ctx, root)
    stats = sync_knowledge(ws)
    console.print(
        f"[green]Sync complete[/green] (indexed={stats.indexed}, deleted={stats.deleted}, unchanged={stats.unchanged})."
    )
