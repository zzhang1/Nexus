from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.commands.calendar_cmd import calendar_app
from nexus_ai.commands.chat_cmd import chat
from nexus_ai.commands.doctor_cmd import doctor
from nexus_ai.commands.ingest_cmd import ingest
from nexus_ai.commands.init_cmd import init
from nexus_ai.commands.outbox_cmd import outbox_app
from nexus_ai.commands.plan_cmd import today, week, month, tasks
from nexus_ai.commands.sync_cmd import sync
from nexus_ai.commands.tidy_cmd import tidy

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.callback()
def _global_options(
    ctx: typer.Context,
    root: Path = typer.Option(
        None,
        "--root",
        "-r",
        help="Workspace root (optional). If omitted, Nexus auto-discovers from the current directory.",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["root"] = root


app.command()(init)
app.command()(ingest)
app.command()(sync)
app.command()(chat)
app.command()(doctor)
app.command()(tidy)

app.command("today")(today)
app.command("week")(week)
app.command("month")(month)
app.command("tasks")(tasks)

app.add_typer(calendar_app, name="calendar", help="Calendar integrations (read-only by default).")
app.add_typer(outbox_app, name="outbox", help="Manage staged deliverables in Outbox/.")

if __name__ == "__main__":
    app()
