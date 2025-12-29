from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.core.workspace import Workspace

console = Console()


def init(
    ctx: typer.Context,
    root: Path = typer.Option(..., "--root", "-r", exists=False, file_okay=False, dir_okay=True),
) -> None:
    """
    Initialize a Nexus workspace folder with Inbox/Knowledge/Outbox and local indexes.
    """

    ws = Workspace(root)
    created = ws.init_workspace()
    console.print(f"[green]Initialized workspace[/green] at {ws.root}")
    if created:
        for item in created:
            console.print(f"  - {item}")
