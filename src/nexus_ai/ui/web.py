from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, session, url_for
try:
    import markdown as md
except ModuleNotFoundError:  # pragma: no cover - optional UI dependency
    md = None

from nexus_ai.core.agent_actions import ActionError, apply_actions, propose_actions
from nexus_ai.core.calendar_sync import sync_calendars
from nexus_ai.core.chat import generate_chat_payload
from nexus_ai.core.config import load_config
from nexus_ai.core.db import NexusDb
from nexus_ai.core.ingest import (
    IngestReviewItem,
    IngestReviewResult,
    apply_ingest_actions,
    ingest_inbox,
)
from nexus_ai.core.google_calendar import (
    GoogleCalendarError,
    create_google_event,
    delete_google_event,
    parse_event_ref,
    update_google_event,
)
from nexus_ai.core.map_store import get_map_store
from nexus_ai.core.markdown import split_front_matter
from nexus_ai.core.outbox import delete_outbox_item, list_outbox_items, mark_outbox_approved
from nexus_ai.core.planner import build_plan, list_tasks
from nexus_ai.core.sync import sync_knowledge
from nexus_ai.core.tasks_parse import parse_tasks_from_markdown
from nexus_ai.core.workspace import Workspace, WorkspaceError

NAV_ITEMS = [
    {"endpoint": "overview", "label": "Overview", "icon": "🏠"},
    {"endpoint": "chat", "label": "Chat", "icon": "💬"},
    {"endpoint": "knowledge", "label": "Knowledge", "icon": "📚"},
    {"endpoint": "plan", "label": "Plan", "icon": "🧭"},
    {"endpoint": "tasks", "label": "Tasks", "icon": "✅"},
    {"endpoint": "inbox", "label": "Inbox", "icon": "📥"},
    {"endpoint": "outbox", "label": "Outbox", "icon": "📤"},
    {"endpoint": "calendar", "label": "Calendar", "icon": "🗓️"},
    {"endpoint": "workspace", "label": "Workspace", "icon": "🧱"},
]


def _default_workspace_root() -> str:
    return os.environ.get("NEXUS_WORKSPACE_ROOT", "").strip()


def _default_auto_discover() -> bool:
    env = os.environ.get("NEXUS_WORKSPACE_AUTO", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    return not bool(_default_workspace_root())


def _resolve_workspace() -> tuple[Workspace | None, str | None]:
    root_query = request.values.get("root")
    auto_query = request.values.get("auto")
    if root_query is not None:
        session["workspace_root"] = root_query.strip()
        session["workspace_auto"] = False
    if auto_query is not None:
        session["workspace_auto"] = auto_query.strip().lower() in {"1", "true", "yes", "on"}

    root_text = session.get("workspace_root", "") or _default_workspace_root()
    auto_discover = session.get("workspace_auto")
    if auto_discover is None:
        auto_discover = _default_auto_discover()

    if auto_discover:
        try:
            return Workspace.discover(Path.cwd()), None
        except WorkspaceError as e:
            if root_text:
                return Workspace(Path(root_text).expanduser()), None
            return None, str(e)

    if not root_text:
        return None, "Provide a workspace root or enable auto-discovery."
    return Workspace(Path(root_text).expanduser()), None


def _workspace_ready(ws: Workspace) -> bool:
    return ws.paths.assistant_dir.exists() and ws.paths.knowledge_dir.exists()


def _db_counts(ws: Workspace) -> dict[str, int]:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    with db.connect() as conn:
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'done'").fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        deadlines = conn.execute("SELECT COUNT(*) FROM deadlines").fetchone()[0]
        outbox = conn.execute("SELECT COUNT(*) FROM outbox_items").fetchone()[0]
    return {
        "documents": int(docs or 0),
        "tasks": int(tasks or 0),
        "events": int(events or 0),
        "deadlines": int(deadlines or 0),
        "outbox": int(outbox or 0),
    }


def _map_health(ws: Workspace) -> dict[str, Any]:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    with db.connect() as conn:
        last_indexed = conn.execute("SELECT MAX(indexed_ts) FROM documents").fetchone()[0]
    return {"last_indexed": last_indexed}


def _map_staleness(ws: Workspace) -> dict[str, int]:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute("SELECT path, mtime FROM documents").fetchall()
    docs = {row["path"]: float(row["mtime"] or 0) for row in rows}
    existing = set(docs.keys())
    seen: set[str] = set()
    new_files = 0
    stale_files = 0
    for path in ws.iter_knowledge_markdown_files():
        rel = path.relative_to(ws.paths.knowledge_dir).as_posix()
        seen.add(rel)
        if rel not in docs:
            new_files += 1
            continue
        try:
            file_mtime = path.stat().st_mtime
            db_mtime = docs.get(rel, 0)
            if file_mtime > db_mtime + 1e-6:
                stale_files += 1
        except Exception:
            stale_files += 1
    deleted_files = len(existing - seen)
    return {"new": new_files, "stale": stale_files, "deleted": deleted_files}


def _serialize_ingest_review(items: list[IngestReviewItem]) -> dict[str, Any]:
    review_actions: list[dict[str, Any]] = []
    inbox_paths: list[str] = []
    serialized_items: list[dict[str, Any]] = []
    for item in items:
        inbox_paths.append(item.rel_inbox_path)
        review_actions.extend(item.actions)
        serialized_items.append(
            {
                "rel_inbox_path": item.rel_inbox_path,
                "proposed": [{"rel_path": c.rel_path, "diff": c.diff} for c in item.proposed],
            }
        )
    return {
        "items": serialized_items,
        "actions": review_actions,
        "inbox_paths": inbox_paths,
    }


def _list_knowledge_dirs(ws: Workspace) -> list[str]:
    dirs: set[str] = set()
    dirs.add(".")
    for p in ws.paths.knowledge_dir.rglob("*"):
        if not p.is_dir():
            continue
        if ".git" in p.parts or p.name.startswith("."):
            continue
        rel = p.relative_to(ws.paths.knowledge_dir).as_posix()
        dirs.add(rel if rel else ".")
    return sorted(dirs)


def _list_markdown_files(ws: Workspace, rel_dir: str) -> list[str]:
    base = ws.paths.knowledge_dir if rel_dir == "." else ws.paths.knowledge_dir / rel_dir
    files: list[str] = []
    if base.exists():
        for p in base.rglob("*.md"):
            if ".git" in p.parts:
                continue
            rel = p.relative_to(ws.paths.knowledge_dir).as_posix()
            files.append(rel)
    return sorted(files)


def _recent_markdown_files(ws: Workspace, limit: int = 25) -> list[str]:
    items: list[tuple[float, str]] = []
    for p in ws.iter_knowledge_markdown_files():
        try:
            items.append((p.stat().st_mtime, p.relative_to(ws.paths.knowledge_dir).as_posix()))
        except Exception:
            continue
    items.sort(key=lambda x: x[0], reverse=True)
    return [rel for _mtime, rel in items[:limit]]


def _related_docs_by_tags(ws: Workspace, rel_path: str, tags: list[str]) -> list[str]:
    if not tags:
        return []
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    results: list[str] = []
    with db.connect() as conn:
        rows = conn.execute("SELECT path, tags_json FROM documents").fetchall()
    for row in rows:
        path = row["path"]
        if path == rel_path:
            continue
        try:
            row_tags = json.loads(row["tags_json"] or "[]")
        except Exception:
            row_tags = []
        if any(t in row_tags for t in tags):
            results.append(path)
    return results[:20]


def _render_markdown(text: str) -> str | None:
    if not md:
        return None
    return md.markdown(text, extensions=["fenced_code", "tables"])


def _safe_rel_path(rel: str) -> str | None:
    rel = rel.strip().lstrip("/").replace("\\", "/")
    if not rel or rel.startswith("."):
        return None
    if ".." in Path(rel).parts:
        return None
    return rel


def _list_inbox_files(ws: Workspace, limit: int = 40) -> list[str]:
    inbox = ws.paths.inbox_dir
    if not inbox.exists():
        return []
    files: list[tuple[float, str]] = []
    for p in inbox.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(inbox).as_posix()
        try:
            files.append((p.stat().st_mtime, rel))
        except Exception:
            files.append((0, rel))
    files.sort(key=lambda x: x[0], reverse=True)
    return [rel for _mtime, rel in files[:limit]]


def _list_upcoming(ws: Workspace, days: int = 14) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    db = NexusDb(ws.paths.db_path)
    db.init_schema()
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=days)
    events: list[dict[str, str]] = []
    deadlines: list[dict[str, str]] = []
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, start_ts, end_ts, timezone, all_day
            FROM events
            WHERE start_ts IS NOT NULL
              AND start_ts >= ?
              AND start_ts <= ?
              AND (status IS NULL OR status != 'cancelled')
            ORDER BY start_ts ASC
            LIMIT 50
            """,
            (now.isoformat(), future.isoformat()),
        ).fetchall()
        for row in rows:
            events.append(
                {
                    "title": row["title"],
                    "start": row["start_ts"],
                    "end": row["end_ts"] or "",
                    "all_day": "Yes" if row["all_day"] else "No",
                }
            )

        rows = conn.execute(
            """
            SELECT id, title, due_ts, timezone
            FROM deadlines
            WHERE due_ts IS NOT NULL
              AND due_ts >= ?
              AND due_ts <= ?
              AND (status IS NULL OR status != 'cancelled')
            ORDER BY due_ts ASC
            LIMIT 50
            """,
            (now.isoformat(), future.isoformat()),
        ).fetchall()
        for row in rows:
            deadlines.append(
                {
                    "title": row["title"],
                    "due": row["due_ts"],
                }
            )
    return events, deadlines


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("NEXUS_SECRET_KEY") or os.urandom(24).hex()

    @app.context_processor
    def _inject_nav():
        ws, _err = _resolve_workspace()
        root_text = session.get("workspace_root", "") or _default_workspace_root()
        return {
            "nav_items": NAV_ITEMS,
            "workspace_root": root_text,
            "workspace_ready": bool(ws and _workspace_ready(ws)),
        }

    @app.get("/")
    @app.post("/")
    def overview():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "init":
                created = ws.init_workspace()
                flash(f"Workspace initialized ({len(created)} items created).", "success")
            elif action == "sync":
                if not _workspace_ready(ws):
                    flash("Initialize the workspace before syncing.", "error")
                else:
                    stats = sync_knowledge(ws)
                    flash(
                        f"Sync complete (indexed={stats.indexed}, deleted={stats.deleted}, unchanged={stats.unchanged}).",
                        "success",
                    )
            elif action == "ingest":
                if not _workspace_ready(ws):
                    flash("Initialize the workspace before ingesting.", "error")
                else:
                    result = ingest_inbox(ws, review=True)
                    if isinstance(result, IngestReviewResult) and result.review_items:
                        payload = _serialize_ingest_review(result.review_items)
                        payload["files_ingested"] = result.files_ingested
                        session["pending_ingest"] = payload
                        flash("Ingest needs review. Please approve changes in Inbox.", "warning")
                        return redirect(url_for("inbox"))
                    session.pop("pending_ingest", None)
                    flash(f"Ingested {result.files_ingested} file(s).", "success")
            return redirect(url_for("overview"))

        counts = _db_counts(ws)
        map_status = _map_staleness(ws)
        map_health = _map_health(ws)
        today_label = datetime.now().strftime("%A, %B %d")
        return render_template(
            "overview.html",
            workspace=ws,
            counts=counts,
            map_status=map_status,
            last_indexed=map_health.get("last_indexed") or "Never",
            today_label=today_label,
        )

    @app.get("/knowledge")
    @app.post("/knowledge")
    def knowledge():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "sync":
                if not _workspace_ready(ws):
                    flash("Initialize the workspace before syncing.", "error")
                else:
                    stats = sync_knowledge(ws)
                    flash(
                        f"Sync complete (indexed={stats.indexed}, deleted={stats.deleted}, unchanged={stats.unchanged}).",
                        "success",
                    )
            return redirect(url_for("knowledge"))

        view = (request.args.get("view") or "all").strip().lower()
        rel_dir = (request.args.get("dir") or ".").strip() or "."
        filter_text = (request.args.get("filter") or "").strip()
        selected_file = (request.args.get("file") or "").strip()
        query = (request.args.get("q") or "").strip()
        limit_raw = (request.args.get("limit") or "8").strip()
        try:
            limit = max(3, min(20, int(limit_raw)))
        except ValueError:
            limit = 8

        dirs = _list_knowledge_dirs(ws)
        if rel_dir not in dirs:
            rel_dir = "."

        if view == "recent":
            files = _recent_markdown_files(ws)
        else:
            files = _list_markdown_files(ws, rel_dir)
        if filter_text:
            needle = filter_text.lower()
            files = [f for f in files if needle in f.lower()]

        if files and selected_file not in files:
            selected_file = files[0]

        file_context: dict[str, Any] | None = None
        if selected_file:
            safe_rel = _safe_rel_path(selected_file)
            if safe_rel:
                file_path = ws.paths.knowledge_dir / safe_rel
                if file_path.exists():
                    text = file_path.read_text(encoding="utf-8", errors="replace")
                    doc = split_front_matter(text)
                    fm = doc.front_matter
                    tags: list[str] = []
                    if isinstance(fm.get("tags"), list):
                        tags = [str(t) for t in fm.get("tags")]
                    tasks = parse_tasks_from_markdown(
                        markdown_text=text,
                        source_path=file_path,
                        knowledge_root=ws.paths.knowledge_dir,
                    )
                    related = _related_docs_by_tags(ws, safe_rel, tags)
                    body = doc.body
                    if len(body) > 8000:
                        body = body[:8000] + "\n\n... (truncated)"
                    preview = body
                    rendered_html = _render_markdown(body)
                    file_context = {
                        "rel_path": safe_rel,
                        "front_matter": fm,
                        "tags": tags,
                        "tasks": tasks,
                        "related": related,
                        "preview": preview,
                        "rendered_html": rendered_html,
                    }

        hits = []
        if query:
            try:
                map_store = get_map_store(ws)
                hits = map_store.search(query, limit=limit)
            except Exception:
                hits = []

        map_status = _map_staleness(ws)
        map_health = _map_health(ws)
        return render_template(
            "knowledge.html",
            workspace=ws,
            view=view,
            rel_dir=rel_dir,
            filter_text=filter_text,
            selected_file=selected_file,
            files=files,
            dirs=dirs,
            file_context=file_context,
            query=query,
            limit=limit,
            hits=hits,
            map_status=map_status,
            last_indexed=map_health.get("last_indexed") or "Never",
        )

    @app.get("/chat")
    @app.post("/chat")
    def chat():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        payload = None
        proposed = []
        has_diffs = False
        query = ""
        error = None
        note = None
        plan_obj = None
        applied = False

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "ask":
                query = (request.form.get("query") or "").strip()
                if not query:
                    flash("Ask something to continue.", "error")
                else:
                    payload = generate_chat_payload(ws, query=query)
                    if payload.get("mode") == "actions":
                        actions = payload.get("actions", [])
                        note = payload.get("note", "")
                        try:
                            proposed = propose_actions(ws, actions)
                            has_diffs = any(change.diff for change in proposed)
                        except ActionError as exc:
                            error = str(exc)
                    elif payload.get("mode") == "plan":
                        scope = payload.get("scope", "today")
                        plan_obj = build_plan(ws, mode=scope)
            elif action == "apply":
                actions_json = request.form.get("actions_json") or "[]"
                approved = request.form.get("approved") == "on"
                if not approved:
                    flash("Please confirm you reviewed the diffs before applying changes.", "error")
                else:
                    try:
                        actions = json.loads(actions_json)
                        result = apply_actions(ws, actions, require_approval=False)
                        flash(result, "success")
                        payload = {"mode": "actions", "actions": actions}
                        proposed = []
                        has_diffs = False
                        note = result
                        applied = True
                    except (json.JSONDecodeError, ActionError) as exc:
                        error = str(exc)

        return render_template(
            "chat.html",
            workspace=ws,
            payload=payload,
            proposed=proposed,
            query=query,
            error=error,
            note=note,
            plan_obj=plan_obj,
            has_diffs=has_diffs,
            applied=applied,
        )

    @app.get("/plan")
    def plan():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        scope = (request.args.get("scope") or "today").strip().lower()
        if scope not in {"today", "week", "month"}:
            scope = "today"
        plan_obj = build_plan(ws, mode=scope)
        return render_template("plan.html", workspace=ws, plan=plan_obj, scope=scope)

    @app.get("/tasks")
    def tasks():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        include_completed = request.args.get("include") == "1"
        rows = list_tasks(ws, include_completed=include_completed)
        return render_template(
            "tasks.html",
            workspace=ws,
            rows=rows,
            include_completed=include_completed,
        )

    @app.get("/inbox")
    @app.post("/inbox")
    def inbox():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        review_payload = session.get("pending_ingest")

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "ingest":
                if not _workspace_ready(ws):
                    flash("Initialize the workspace before ingesting.", "error")
                else:
                    result = ingest_inbox(ws, review=True)
                    if isinstance(result, IngestReviewResult) and result.review_items:
                        review_payload = _serialize_ingest_review(result.review_items)
                        review_payload["files_ingested"] = result.files_ingested
                        session["pending_ingest"] = review_payload
                    else:
                        session.pop("pending_ingest", None)
                        flash(f"Ingested {result.files_ingested} file(s).", "success")
                return redirect(url_for("inbox"))
            if action == "apply_ingest":
                approved = request.form.get("approved") == "on"
                if not approved:
                    flash("Please confirm you reviewed the diffs before applying changes.", "error")
                else:
                    try:
                        actions = json.loads(request.form.get("actions_json") or "[]")
                        inbox_paths = json.loads(request.form.get("inbox_paths_json") or "[]")
                        result = apply_ingest_actions(
                            ws,
                            actions=actions,
                            inbox_paths=inbox_paths,
                        )
                        flash(result, "success")
                        session.pop("pending_ingest", None)
                    except (json.JSONDecodeError, ActionError) as exc:
                        flash(str(exc), "error")
                return redirect(url_for("inbox"))

        inbox_files = _list_inbox_files(ws)
        return render_template(
            "inbox.html",
            workspace=ws,
            inbox_files=inbox_files,
            review_payload=review_payload,
        )

    @app.get("/outbox")
    @app.post("/outbox")
    def outbox():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        items = list_outbox_items(ws)
        selected = (request.args.get("item") or "").strip()

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            rel_path = (request.form.get("rel_path") or "").strip()
            if action == "approve" and rel_path:
                mark_outbox_approved(ws, Path(rel_path))
                flash("Outbox item approved.", "success")
            elif action == "delete" and rel_path:
                delete_outbox_item(ws, Path(rel_path))
                flash("Outbox item deleted.", "success")
            return redirect(url_for("outbox", item=rel_path))

        if items and selected not in {item.rel_path for item in items}:
            selected = items[0].rel_path

        preview = ""
        rendered_html = None
        status = ""
        if selected:
            status = next((item.status for item in items if item.rel_path == selected), "")
            file_path = ws.paths.outbox_dir / selected
            if file_path.exists():
                preview = file_path.read_text(encoding="utf-8", errors="replace")
                if file_path.suffix.lower() == ".md":
                    rendered_html = _render_markdown(preview)

        return render_template(
            "outbox.html",
            workspace=ws,
            items=items,
            selected=selected,
            status=status,
            preview=preview,
            rendered_html=rendered_html,
        )

    @app.get("/calendar")
    @app.post("/calendar")
    def calendar():
        ws, err = _resolve_workspace()
        if err or ws is None:
            return redirect(url_for("workspace", error=err or ""))

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "sync":
                if not _workspace_ready(ws):
                    flash("Initialize the workspace before syncing calendars.", "error")
                else:
                    result = sync_calendars(ws)
                    flash(f"Upserted {result.events_upserted} event(s).", "success")
                    if result.warnings:
                        for warning in result.warnings:
                            flash(warning, "error")
            elif action == "create_event":
                cfg = load_config(ws.paths.config_yaml)
                if request.form.get("approved_write") != "on":
                    flash("Confirm approval before writing to Google Calendar.", "error")
                    return redirect(url_for("calendar"))
                try:
                    result = create_google_event(
                        ws,
                        cfg,
                        calendar_id=(request.form.get("calendar_id") or "primary").strip() or "primary",
                        title=(request.form.get("title") or "").strip(),
                        start=(request.form.get("start") or "").strip(),
                        end=(request.form.get("end") or "").strip() or None,
                        all_day=request.form.get("all_day") == "on",
                        timezone_name=(request.form.get("timezone_name") or "").strip() or None,
                        description=(request.form.get("description") or "").strip() or None,
                        location=(request.form.get("location") or "").strip() or None,
                        recurrence_rrule=(request.form.get("recurrence_rrule") or "").strip() or None,
                    )
                    flash(
                        f"Created event {result.source_id} ({result.status}).",
                        "success",
                    )
                except GoogleCalendarError as exc:
                    flash(str(exc), "error")
            elif action == "update_event":
                cfg = load_config(ws.paths.config_yaml)
                if request.form.get("approved_write") != "on":
                    flash("Confirm approval before writing to Google Calendar.", "error")
                    return redirect(url_for("calendar"))
                try:
                    cal_id, ev_id = parse_event_ref(
                        source_id=(request.form.get("source_id") or "").strip() or None,
                        calendar_id=(request.form.get("calendar_id") or "").strip() or None,
                        event_id=(request.form.get("event_id") or "").strip() or None,
                    )
                    all_day_mode = (request.form.get("all_day_mode") or "").strip()
                    all_day_value: bool | None
                    if all_day_mode == "all_day":
                        all_day_value = True
                    elif all_day_mode == "timed":
                        all_day_value = False
                    else:
                        all_day_value = None
                    result = update_google_event(
                        ws,
                        cfg,
                        calendar_id=cal_id,
                        event_id=ev_id,
                        title=(request.form.get("title") or "").strip() or None,
                        start=(request.form.get("start") or "").strip() or None,
                        end=(request.form.get("end") or "").strip() or None,
                        clear_end=request.form.get("clear_end") == "on",
                        all_day=all_day_value,
                        timezone_name=(request.form.get("timezone_name") or "").strip() or None,
                        description=(request.form.get("description") or "").strip() or None,
                        clear_description=request.form.get("clear_description") == "on",
                        location=(request.form.get("location") or "").strip() or None,
                        clear_location=request.form.get("clear_location") == "on",
                        recurrence_rrule=(request.form.get("recurrence_rrule") or "").strip() or None,
                        clear_recurrence=request.form.get("clear_recurrence") == "on",
                        status=(request.form.get("status") or "").strip() or None,
                    )
                    flash(
                        f"Updated event {result.source_id} ({result.status}).",
                        "success",
                    )
                except GoogleCalendarError as exc:
                    flash(str(exc), "error")
            elif action == "delete_event":
                cfg = load_config(ws.paths.config_yaml)
                if request.form.get("approved_write") != "on":
                    flash("Confirm approval before writing to Google Calendar.", "error")
                    return redirect(url_for("calendar"))
                try:
                    cal_id, ev_id = parse_event_ref(
                        source_id=(request.form.get("source_id") or "").strip() or None,
                        calendar_id=(request.form.get("calendar_id") or "").strip() or None,
                        event_id=(request.form.get("event_id") or "").strip() or None,
                    )
                    result = delete_google_event(
                        ws,
                        cfg,
                        calendar_id=cal_id,
                        event_id=ev_id,
                    )
                    flash(
                        f"Deleted event {result.source_id} ({result.status}).",
                        "success",
                    )
                except GoogleCalendarError as exc:
                    flash(str(exc), "error")
            return redirect(url_for("calendar"))

        cfg = load_config(ws.paths.config_yaml)
        events, deadlines = _list_upcoming(ws)
        return render_template(
            "calendar.html",
            workspace=ws,
            ics_paths=cfg.calendar.ics_paths,
            events=events,
            deadlines=deadlines,
        )

    @app.get("/workspace")
    @app.post("/workspace")
    def workspace():
        ws, err = _resolve_workspace()
        error = request.args.get("error") or err
        root_text = session.get("workspace_root", "") or _default_workspace_root()
        auto_discover = session.get("workspace_auto")
        if auto_discover is None:
            auto_discover = _default_auto_discover()

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "save":
                root_text = (request.form.get("root") or "").strip()
                auto_discover = request.form.get("auto") == "on"
                session["workspace_root"] = root_text
                session["workspace_auto"] = auto_discover
                return redirect(url_for("overview"))
            if action == "init" and ws:
                created = ws.init_workspace()
                flash(f"Workspace initialized ({len(created)} items created).", "success")
                return redirect(url_for("overview"))

        return render_template(
            "workspace.html",
            workspace=ws,
            error=error,
            root_text=root_text,
            auto_discover=auto_discover,
        )

    return app


def main() -> None:
    host = os.environ.get("NEXUS_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("NEXUS_WEB_PORT", "5000"))
    debug = os.environ.get("NEXUS_WEB_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
