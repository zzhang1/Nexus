from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.core.ingest import ingest_inbox
from nexus_ai.core.workspace import Workspace

console = Console()


def ingest(
    root: Path = typer.Option(None, "--root", "-r", help="Workspace root (defaults to current directory)."),
) -> None:
    """
    Ingest files from 0_Inbox/ into Knowledge/ and update the local index.
    """

    ws = Workspace.from_optional_root(root)
    result = ingest_inbox(ws)
    console.print(f"[green]Ingested[/green] {result.files_ingested} file(s).")

