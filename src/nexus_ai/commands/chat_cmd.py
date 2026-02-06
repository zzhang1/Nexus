from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.workspace import Workspace

console = Console()


def chat(
    ctx: typer.Context,
    query: str = typer.Argument(...),
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    """
    Ask a question grounded in Knowledge/ and the local index.
    """

    from nexus_ai.core.chat import run_chat

    ws = workspace_from_ctx(ctx, root)
    answer = run_chat(ws, query=query)
    console.print(answer)
