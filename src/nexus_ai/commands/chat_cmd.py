from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.core.chat import run_chat
from nexus_ai.core.workspace import Workspace

console = Console()


def chat(
    query: str = typer.Argument(...),
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    """
    Ask a question grounded in Knowledge/ and the local index.
    """

    ws = Workspace.from_optional_root(root)
    answer = run_chat(ws, query=query)
    console.print(answer)

