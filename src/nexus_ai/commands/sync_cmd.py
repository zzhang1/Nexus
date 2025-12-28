from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.core.sync import sync_knowledge
from nexus_ai.core.workspace import Workspace

console = Console()


def sync(
    root: Path = typer.Option(None, "--root", "-r", help="Workspace root (defaults to current directory)."),
) -> None:
    """
    Re-scan Knowledge/ for changes and update the local index idempotently.
    """

    ws = Workspace.from_optional_root(root)
    stats = sync_knowledge(ws)
    console.print(
        f"[green]Sync complete[/green] (indexed={stats.indexed}, deleted={stats.deleted}, unchanged={stats.unchanged})."
    )

