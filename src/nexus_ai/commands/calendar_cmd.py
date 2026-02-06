from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.calendar_sync import sync_calendars
from nexus_ai.core.config import load_config
from nexus_ai.core.google_calendar import (
    GoogleCalendarError,
    authorize_google_calendar,
    create_google_event,
    delete_google_event,
    parse_event_ref,
    update_google_event,
)

console = Console()
calendar_app = typer.Typer(no_args_is_help=True)


def _confirm_write(message: str, *, yes: bool) -> None:
    if yes:
        return
    if not typer.confirm(message, default=False):
        raise typer.Exit(code=1)


@calendar_app.command("auth")
def calendar_auth(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r"),
    write: bool = typer.Option(False, "--write", help="Request write access to events."),
) -> None:
    """
    Authorize Google Calendar access (stores OAuth token under .assistant/).
    """

    ws = workspace_from_ctx(ctx, root)
    cfg = load_config(ws.paths.config_yaml)
    try:
        token_path = authorize_google_calendar(ws, cfg, write_access=write)
    except GoogleCalendarError as exc:
        console.print(f"[red]Calendar auth failed:[/red] {exc}")
        raise typer.Exit(code=2)
    console.print(f"[green]Calendar auth complete[/green] (token={token_path}).")


@calendar_app.command("sync")
def calendar_sync(ctx: typer.Context, root: Path = typer.Option(None, "--root", "-r")) -> None:
    """
    Import events from configured calendar sources (read-only by default).
    """

    ws = workspace_from_ctx(ctx, root)
    result = sync_calendars(ws)
    console.print(f"[green]Calendar sync complete[/green] (events_upserted={result.events_upserted}).")
    if result.warnings:
        for warning in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")


@calendar_app.command("create")
def calendar_create(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Event title."),
    start: str = typer.Option(
        ...,
        "--start",
        help="Start in RFC3339 datetime (timed) or YYYY-MM-DD (all-day).",
    ),
    end: str = typer.Option(
        None,
        "--end",
        help="End in RFC3339 datetime (timed) or YYYY-MM-DD (all-day).",
    ),
    calendar_id: str = typer.Option("primary", "--calendar-id", help="Target Google calendar id."),
    all_day: bool = typer.Option(False, "--all-day", help="Treat start/end as all-day date values."),
    timezone_name: str = typer.Option(None, "--tz", help="Timezone for timed events."),
    description: str = typer.Option(None, "--description", help="Event description."),
    location: str = typer.Option(None, "--location", help="Event location."),
    recurrence_rrule: str = typer.Option(
        None,
        "--rrule",
        help="Recurrence rule (e.g. FREQ=WEEKLY;BYDAY=MO).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    """
    Create a Google Calendar event (write scope required).
    """

    ws = workspace_from_ctx(ctx, root)
    cfg = load_config(ws.paths.config_yaml)
    _confirm_write(
        f"Create event on calendar '{calendar_id}' titled '{title}' starting '{start}'?",
        yes=yes,
    )
    try:
        result = create_google_event(
            ws,
            cfg,
            calendar_id=calendar_id,
            title=title,
            start=start,
            end=end,
            all_day=all_day,
            timezone_name=timezone_name,
            description=description,
            location=location,
            recurrence_rrule=recurrence_rrule,
        )
    except GoogleCalendarError as exc:
        console.print(f"[red]Calendar create failed:[/red] {exc}")
        raise typer.Exit(code=2)
    console.print(
        f"[green]Calendar create complete[/green] "
        f"(source_id={result.source_id}, status={result.status})."
    )


@calendar_app.command("update")
def calendar_update(
    ctx: typer.Context,
    source_id: str = typer.Option(
        None,
        "--source-id",
        help="Nexus source id format: <calendar_id>:<event_id>.",
    ),
    calendar_id: str = typer.Option(None, "--calendar-id", help="Google calendar id."),
    event_id: str = typer.Option(None, "--event-id", help="Google event id."),
    title: str = typer.Option(None, "--title", help="New title."),
    start: str = typer.Option(
        None,
        "--start",
        help="New start (RFC3339 datetime or YYYY-MM-DD for all-day).",
    ),
    end: str = typer.Option(
        None,
        "--end",
        help="New end (RFC3339 datetime or YYYY-MM-DD for all-day).",
    ),
    clear_end: bool = typer.Option(False, "--clear-end", help="Reset end for all-day start."),
    event_type: str = typer.Option(
        "keep",
        "--event-type",
        help="Type update when setting start/end: keep|all_day|timed.",
    ),
    timezone_name: str = typer.Option(None, "--tz", help="Timezone for timed events."),
    description: str = typer.Option(None, "--description", help="New description."),
    clear_description: bool = typer.Option(
        False, "--clear-description", help="Clear description."
    ),
    location: str = typer.Option(None, "--location", help="New location."),
    clear_location: bool = typer.Option(False, "--clear-location", help="Clear location."),
    recurrence_rrule: str = typer.Option(
        None,
        "--rrule",
        help="New recurrence rule (without or with RRULE: prefix).",
    ),
    clear_recurrence: bool = typer.Option(False, "--clear-recurrence", help="Clear recurrence."),
    status: str = typer.Option(
        None,
        "--status",
        help="Set status (confirmed|tentative|cancelled).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    """
    Update an existing Google Calendar event (write scope required).
    """

    ws = workspace_from_ctx(ctx, root)
    cfg = load_config(ws.paths.config_yaml)
    try:
        resolved_calendar_id, resolved_event_id = parse_event_ref(
            source_id=source_id,
            calendar_id=calendar_id,
            event_id=event_id,
        )
    except GoogleCalendarError as exc:
        console.print(f"[red]Calendar update failed:[/red] {exc}")
        raise typer.Exit(code=2)

    _confirm_write(
        f"Update event '{resolved_calendar_id}:{resolved_event_id}' on Google Calendar?",
        yes=yes,
    )
    mode = (event_type or "keep").strip().lower()
    if mode not in {"keep", "all_day", "timed"}:
        console.print("[red]Calendar update failed:[/red] --event-type must be keep|all_day|timed.")
        raise typer.Exit(code=2)
    all_day_value: bool | None = None
    if mode == "all_day":
        all_day_value = True
    elif mode == "timed":
        all_day_value = False
    try:
        result = update_google_event(
            ws,
            cfg,
            calendar_id=resolved_calendar_id,
            event_id=resolved_event_id,
            title=title,
            start=start,
            end=end,
            clear_end=clear_end,
            all_day=all_day_value,
            timezone_name=timezone_name,
            description=description,
            clear_description=clear_description,
            location=location,
            clear_location=clear_location,
            recurrence_rrule=recurrence_rrule,
            clear_recurrence=clear_recurrence,
            status=status,
        )
    except GoogleCalendarError as exc:
        console.print(f"[red]Calendar update failed:[/red] {exc}")
        raise typer.Exit(code=2)
    console.print(
        f"[green]Calendar update complete[/green] "
        f"(source_id={result.source_id}, status={result.status})."
    )


@calendar_app.command("delete")
def calendar_delete(
    ctx: typer.Context,
    source_id: str = typer.Option(
        None,
        "--source-id",
        help="Nexus source id format: <calendar_id>:<event_id>.",
    ),
    calendar_id: str = typer.Option(None, "--calendar-id", help="Google calendar id."),
    event_id: str = typer.Option(None, "--event-id", help="Google event id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    root: Path = typer.Option(None, "--root", "-r"),
) -> None:
    """
    Delete a Google Calendar event (write scope required).
    """

    ws = workspace_from_ctx(ctx, root)
    cfg = load_config(ws.paths.config_yaml)
    try:
        resolved_calendar_id, resolved_event_id = parse_event_ref(
            source_id=source_id,
            calendar_id=calendar_id,
            event_id=event_id,
        )
    except GoogleCalendarError as exc:
        console.print(f"[red]Calendar delete failed:[/red] {exc}")
        raise typer.Exit(code=2)

    _confirm_write(
        f"Delete event '{resolved_calendar_id}:{resolved_event_id}' from Google Calendar?",
        yes=yes,
    )
    try:
        result = delete_google_event(
            ws,
            cfg,
            calendar_id=resolved_calendar_id,
            event_id=resolved_event_id,
        )
    except GoogleCalendarError as exc:
        console.print(f"[red]Calendar delete failed:[/red] {exc}")
        raise typer.Exit(code=2)
    console.print(
        f"[green]Calendar delete complete[/green] "
        f"(source_id={result.source_id}, status={result.status})."
    )
