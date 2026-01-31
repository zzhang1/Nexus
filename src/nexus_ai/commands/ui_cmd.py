from __future__ import annotations

import os

import typer


def ui(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", help="Host for the web UI."),
    port: int = typer.Option(5000, help="Port for the web UI."),
    debug: bool = typer.Option(False, help="Enable Flask debug mode."),
) -> None:
    root = None
    if ctx and isinstance(ctx.obj, dict):
        root = ctx.obj.get("root")
    if root:
        os.environ["NEXUS_WORKSPACE_ROOT"] = str(root)
        os.environ["NEXUS_WORKSPACE_AUTO"] = "0"

    os.environ["NEXUS_WEB_HOST"] = host
    os.environ["NEXUS_WEB_PORT"] = str(port)
    if debug:
        os.environ["NEXUS_WEB_DEBUG"] = "1"

    try:
        from nexus_ai.ui.web import main
    except ModuleNotFoundError as exc:
        if exc.name == "flask":
            typer.secho("Missing Flask. Install UI extras with: pip install .[ui]", fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc
        raise

    main()
