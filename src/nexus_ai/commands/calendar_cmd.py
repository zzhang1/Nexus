from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.core.calendar_sync import sync_calendars
from nexus_ai.core.workspace import Workspace

console = Console()
calendar_app = typer.Typer(no_args_is_help=True)


@calendar_app.command("sync")
def calendar_sync(root: Path = typer.Option(None, "--root", "-r")) -> None:
    """
    Import events from configured calendar sources (read-only by default).
    """

    ws = Workspace.from_optional_root(root)
    result = sync_calendars(ws)
    console.print(f"[green]Calendar sync complete[/green] (events_upserted={result.events_upserted}).")

