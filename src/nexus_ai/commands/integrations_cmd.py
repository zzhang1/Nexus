from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.config import load_config, parse_integration_mode, set_integrations_mode
from nexus_ai.core.integrations import IntegrationRegistry

console = Console()
integrations_app = typer.Typer(no_args_is_help=True)


@integrations_app.command("list")
def integrations_list(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    ws = workspace_from_ctx(ctx, root)
    cfg = load_config(ws.paths.config_yaml)
    registry = IntegrationRegistry(cfg)

    table = Table(title=f"Integrations (mode={registry.mode})", show_lines=False)
    table.add_column("Integration", style="bold")
    table.add_column("Capability")
    table.add_column("Access")
    table.add_column("Surface")
    table.add_column("Status")
    table.add_column("Details")

    for row in registry.list_capabilities():
        if row.allowed:
            status = "ENABLED"
        elif row.implemented:
            status = "DISABLED"
        else:
            status = "PLANNED"
        table.add_row(
            row.integration,
            row.capability,
            row.access,
            row.surface,
            status,
            row.reason or "",
        )
    console.print(table)


@integrations_app.command("mode")
def integrations_mode(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    ws = workspace_from_ctx(ctx, root)
    cfg = load_config(ws.paths.config_yaml)
    registry = IntegrationRegistry(cfg)
    console.print(f"integrations.mode={registry.mode}")


@integrations_app.command("set-mode")
def integrations_set_mode(
    ctx: typer.Context,
    mode: str = typer.Argument(..., help="read_only or write_enabled"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    ws = workspace_from_ctx(ctx, root)
    try:
        parsed_mode = parse_integration_mode(mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    if parsed_mode == "write_enabled" and not yes:
        if not typer.confirm(
            "Enable write operations for integrations? This allows external data mutation.",
            default=False,
        ):
            raise typer.Exit(code=1)

    saved_mode = set_integrations_mode(ws.paths.config_yaml, mode=parsed_mode)
    console.print(f"[green]Updated[/green] integrations.mode={saved_mode}")

