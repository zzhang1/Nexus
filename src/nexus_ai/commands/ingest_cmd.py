from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from nexus_ai.commands.common import workspace_from_ctx
from nexus_ai.core.ingest import IngestReviewResult, apply_ingest_actions, ingest_inbox

console = Console()


def ingest(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r", help="Workspace root (defaults to current directory)."),
    review: bool = typer.Option(
        True,
        "--review/--no-review",
        help="Require approval before applying ingest changes.",
    ),
) -> None:
    """
    Ingest files from 0_Inbox/ into Knowledge/ and update the local index.
    """

    ws = workspace_from_ctx(ctx, root)
    result = ingest_inbox(ws, review=review)
    if isinstance(result, IngestReviewResult) and result.review_items:
        console.print(f"[yellow]Review required[/yellow] for {len(result.review_items)} file(s).")
        if result.files_ingested:
            console.print(f"[green]Ingested[/green] {result.files_ingested} file(s).")
        for item in result.review_items:
            console.print(f"\n[bold]From Inbox:[/bold] {item.rel_inbox_path}")
            if item.filing_note:
                console.print(f"[dim]Note:[/dim] {item.filing_note}")
            if not item.proposed:
                console.print("[dim]No diffs available.[/dim]")
                continue
            for change in item.proposed:
                if change.diff:
                    console.print(change.diff)

        if typer.confirm("Apply these changes to Knowledge/?", default=False):
            actions: list[dict] = []
            inbox_paths: list[str] = []
            for item in result.review_items:
                actions.extend(item.actions)
                inbox_paths.append(item.rel_inbox_path)
            apply_result = apply_ingest_actions(
                ws, actions=actions, inbox_paths=inbox_paths
            )
            console.print(apply_result)
        else:
            console.print("No changes applied. Pending files remain in 0_Inbox/.")
        return

    console.print(f"[green]Ingested[/green] {result.files_ingested} file(s).")
