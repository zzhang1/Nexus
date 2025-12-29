from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.planner import build_plan, list_tasks
from nexus_ai.core.workspace import Workspace

console = Console()


def today(ctx: typer.Context, root: Path = typer.Option(None, "--root", "-r")) -> None:
    ws = workspace_from_ctx(ctx, root)
    plan = build_plan(ws, mode="today")
    console.print(plan.render())


def week(ctx: typer.Context, root: Path = typer.Option(None, "--root", "-r")) -> None:
    ws = workspace_from_ctx(ctx, root)
    plan = build_plan(ws, mode="week")
    console.print(plan.render())


def month(ctx: typer.Context, root: Path = typer.Option(None, "--root", "-r")) -> None:
    ws = workspace_from_ctx(ctx, root)
    plan = build_plan(ws, mode="month")
    console.print(plan.render())


def tasks(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r"),
    all: bool = typer.Option(False, "--all", help="Include completed tasks."),
) -> None:
    ws = workspace_from_ctx(ctx, root)
    rows = list_tasks(ws, include_completed=all)
    if not rows:
        console.print("[yellow]No tasks found.[/yellow]")
        return
    for row in rows:
        due = row.due_date.isoformat() if row.due_date else "-"
        console.print(f"- [{row.status}] {row.title} (due {due}) — {row.source_path}")
