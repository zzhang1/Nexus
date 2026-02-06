from __future__ import annotations

from datetime import date
from pathlib import Path
import re

import typer
from rich.console import Console

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.planner import build_plan, list_tasks
from nexus_ai.core.workspace import Workspace

console = Console()


def _parse_availability_window(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", raw)
    if not m:
        raise typer.BadParameter("availability must be formatted as HH:MM-HH:MM")
    sh, sm, eh, em = [int(x) for x in m.groups()]
    if sh > 23 or eh > 23 or sm > 59 or em > 59:
        raise typer.BadParameter("availability time values are out of range")
    start = sh * 60 + sm
    end = eh * 60 + em
    if end <= start:
        raise typer.BadParameter("availability end must be after start")
    return start, end


def today(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r"),
    availability: str = typer.Option(
        None,
        "--availability",
        "-a",
        help="Optional work window for draft time blocks (HH:MM-HH:MM).",
    ),
) -> None:
    ws = workspace_from_ctx(ctx, root)
    plan = build_plan(ws, mode="today", availability=_parse_availability_window(availability))
    console.print(plan.render())


def week(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r"),
    availability: str = typer.Option(
        None,
        "--availability",
        "-a",
        help="Optional work window for draft time blocks (HH:MM-HH:MM).",
    ),
) -> None:
    ws = workspace_from_ctx(ctx, root)
    plan = build_plan(ws, mode="week", availability=_parse_availability_window(availability))
    console.print(plan.render())


def month(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r"),
    availability: str = typer.Option(
        None,
        "--availability",
        "-a",
        help="Optional work window for draft time blocks (HH:MM-HH:MM).",
    ),
) -> None:
    ws = workspace_from_ctx(ctx, root)
    plan = build_plan(ws, mode="month", availability=_parse_availability_window(availability))
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
