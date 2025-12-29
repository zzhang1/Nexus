from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from zoneinfo import ZoneInfo

from nexus_ai.core.config import load_config, load_preferences, resolve_llm_settings
from nexus_ai.core.db import NexusDb
from nexus_ai.core.workspace import Workspace, WorkspaceError

console = Console()


def doctor(
    ctx: typer.Context,
    root: Path = typer.Option(None, "--root", "-r", help="Workspace root (defaults to auto-discovery)."),
) -> None:
    """
    Check workspace health and configuration (paths, DB, git repo, LLM settings).
    """

    table = Table(title="Nexus Doctor", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    try:
        from nexus_ai.commands.common import workspace_from_ctx

        ws = workspace_from_ctx(ctx, root)
        table.add_row("Workspace", "OK", str(ws.root))
    except WorkspaceError as e:
        table.add_row("Workspace", "FAIL", str(e))
        console.print(table)
        raise typer.Exit(code=2)

    # Config
    try:
        cfg = load_config(ws.paths.config_yaml)
        llm = resolve_llm_settings(cfg.llm)
        table.add_row("Config", "OK", str(ws.paths.config_yaml))
    except Exception as e:
        table.add_row("Config", "FAIL", f"{ws.paths.config_yaml}: {e}")
        console.print(table)
        raise typer.Exit(code=2)

    # Preferences
    try:
        prefs = load_preferences(ws.paths.preferences_yaml)
        ZoneInfo(prefs.timezone)
        table.add_row("Preferences", "OK", f"timezone={prefs.timezone}")
    except Exception as e:
        table.add_row("Preferences", "WARN", f"{ws.paths.preferences_yaml}: {e}")

    # DB
    try:
        db = NexusDb(ws.paths.db_path)
        db.init_schema()
        n_docs = len(db.list_document_paths())
        table.add_row("Database", "OK", f"{ws.paths.db_path} (documents={n_docs})")
    except Exception as e:
        table.add_row("Database", "FAIL", f"{ws.paths.db_path}: {e}")

    # Knowledge git
    try:
        from git import Repo

        Repo(ws.paths.knowledge_dir)
        table.add_row("Knowledge Git", "OK", str(ws.paths.knowledge_dir))
    except Exception as e:
        table.add_row("Knowledge Git", "WARN", f"{ws.paths.knowledge_dir}: {e}")

    # LLM settings
    provider_model = llm["model"]
    env = llm.get("api_key_env")
    base_url = llm.get("base_url")
    if provider_model.startswith("ollama/"):
        table.add_row("LLM", "OK", f"{provider_model} (base_url={base_url})")
    else:
        has_key = bool(env and os.getenv(env))
        table.add_row(
            "LLM",
            "OK" if has_key else "WARN",
            f"{provider_model} (needs {env})" if env else provider_model,
        )

    console.print(table)
