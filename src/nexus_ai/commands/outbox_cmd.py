from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.core.outbox import delete_outbox_item, list_outbox_items, mark_outbox_approved
from nexus_ai.core.workspace import Workspace

console = Console()
outbox_app = typer.Typer(no_args_is_help=True)


@outbox_app.command("list")
def outbox_list(root: Path = typer.Option(None, "--root", "-r")) -> None:
    ws = Workspace.from_optional_root(root)
    items = list_outbox_items(ws)
    if not items:
        console.print("[yellow]Outbox is empty.[/yellow]")
        return
    for item in items:
        status = item.status
        console.print(f"- {item.rel_path} ({status})")


@outbox_app.command("approve")
def outbox_approve(path: str = typer.Argument(...), root: Path = typer.Option(None, "--root", "-r")) -> None:
    ws = Workspace.from_optional_root(root)
    mark_outbox_approved(ws, Path(path))
    console.print("[green]Approved.[/green]")


@outbox_app.command("open")
def outbox_open(path: str = typer.Argument(...), root: Path = typer.Option(None, "--root", "-r")) -> None:
    ws = Workspace.from_optional_root(root)
    rel = Path(path)
    file_path = (ws.paths.outbox_dir / rel).resolve() if not rel.is_absolute() else rel.resolve()
    if not file_path.exists():
        raise typer.Exit(code=1)
    console.print(file_path.read_text(encoding="utf-8", errors="replace"))


@outbox_app.command("delete")
def outbox_delete(path: str = typer.Argument(...), root: Path = typer.Option(None, "--root", "-r")) -> None:
    ws = Workspace.from_optional_root(root)
    delete_outbox_item(ws, Path(path))
    console.print("[green]Deleted.[/green]")
