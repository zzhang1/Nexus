from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class TaskRow:
    id: str
    title: str
    status: str
    due_date: datetime.date | None
    priority: str | None
    effort: str | None
    source_path: str
    source_anchor: str


@dataclass(frozen=True)
class OutboxItemRow:
    rel_path: str
    status: str


class NexusDb:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                  path TEXT PRIMARY KEY,
                  sha256 TEXT NOT NULL,
                  mtime REAL NOT NULL,
                  title TEXT,
                  doc_type TEXT,
                  status TEXT,
                  tags_json TEXT,
                  created_ts TEXT,
                  updated_ts TEXT,
                  indexed_ts TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  path TEXT NOT NULL,
                  chunk_index INTEGER NOT NULL,
                  content TEXT NOT NULL,
                  FOREIGN KEY(path) REFERENCES documents(path) ON DELETE CASCADE
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(content, path UNINDEXED, chunk_id UNINDEXED);

                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                  INSERT INTO chunks_fts(rowid, content, path, chunk_id) VALUES (new.id, new.content, new.path, new.id);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                  INSERT INTO chunks_fts(chunks_fts, rowid, content, path, chunk_id)
                  VALUES ('delete', old.id, old.content, old.path, old.id);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                  INSERT INTO chunks_fts(chunks_fts, rowid, content, path, chunk_id)
                  VALUES ('delete', old.id, old.content, old.path, old.id);
                  INSERT INTO chunks_fts(rowid, content, path, chunk_id) VALUES (new.id, new.content, new.path, new.id);
                END;

                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  status TEXT NOT NULL,
                  due_date TEXT,
                  priority TEXT,
                  effort TEXT,
                  tags_json TEXT,
                  source_path TEXT NOT NULL,
                  source_anchor TEXT NOT NULL,
                  created_ts TEXT NOT NULL,
                  completed_ts TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  start_ts TEXT NOT NULL,
                  end_ts TEXT,
                  timezone TEXT,
                  all_day INTEGER NOT NULL DEFAULT 0,
                  recurrence_rule TEXT,
                  source_path TEXT,
                  source TEXT,
                  source_id TEXT,
                  status TEXT
                );

                CREATE TABLE IF NOT EXISTS deadlines (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  due_ts TEXT NOT NULL,
                  timezone TEXT,
                  source_path TEXT,
                  source TEXT,
                  source_id TEXT,
                  status TEXT
                );

                CREATE TABLE IF NOT EXISTS outbox_items (
                  rel_path TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  created_ts TEXT NOT NULL,
                  approved_ts TEXT
                );
                """
            )
            # Lightweight migrations for older DBs (safe to ignore failures).
            for stmt in [
                "ALTER TABLE events ADD COLUMN source_path TEXT",
                "ALTER TABLE deadlines ADD COLUMN source_path TEXT",
            ]:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass

    def upsert_document(
        self,
        *,
        path: str,
        sha256: str,
        mtime: float,
        title: str | None,
        doc_type: str | None,
        status: str | None,
        tags: list[str] | None,
        created_ts: str | None,
        updated_ts: str | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(path, sha256, mtime, title, doc_type, status, tags_json, created_ts, updated_ts, indexed_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                  sha256=excluded.sha256,
                  mtime=excluded.mtime,
                  title=excluded.title,
                  doc_type=excluded.doc_type,
                  status=excluded.status,
                  tags_json=excluded.tags_json,
                  created_ts=COALESCE(documents.created_ts, excluded.created_ts),
                  updated_ts=excluded.updated_ts,
                  indexed_ts=excluded.indexed_ts
                """,
                (
                    path,
                    sha256,
                    mtime,
                    title,
                    doc_type,
                    status,
                    json.dumps(tags or []),
                    created_ts,
                    updated_ts,
                    _utc_now_iso(),
                ),
            )

    def delete_document(self, path: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM documents WHERE path=?", (path,))
            conn.execute("DELETE FROM tasks WHERE source_path=?", (path,))
            conn.execute("DELETE FROM events WHERE source_path=?", (path,))
            conn.execute("DELETE FROM deadlines WHERE source_path=?", (path,))

    def rename_document(self, old_path: str, new_path: str) -> None:
        """
        Rename a document path and all dependent rows.
        """
        with self.connect() as conn:
            conn.execute("UPDATE documents SET path=? WHERE path=?", (new_path, old_path))
            conn.execute("UPDATE chunks SET path=? WHERE path=?", (new_path, old_path))
            # FTS stores path as an unindexed column; easiest is to rebuild FTS entries by updating chunks.
            # We force a touch update to trigger chunks_au.
            conn.execute(
                "UPDATE chunks SET content=content WHERE path=?",
                (new_path,),
            )
            conn.execute("UPDATE tasks SET source_path=? WHERE source_path=?", (new_path, old_path))
            conn.execute("UPDATE events SET source_path=? WHERE source_path=?", (new_path, old_path))
            conn.execute("UPDATE deadlines SET source_path=? WHERE source_path=?", (new_path, old_path))

    def get_document(self, path: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE path=?", (path,)).fetchone()
            return dict(row) if row else None

    def list_document_paths(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT path FROM documents").fetchall()
            return {r["path"] for r in rows}

    def replace_chunks(self, *, path: str, chunks: list[str]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE path=?", (path,))
            conn.executemany(
                "INSERT INTO chunks(path, chunk_index, content) VALUES (?, ?, ?)",
                [(path, i, content) for i, content in enumerate(chunks)],
            )

    def search_chunks(self, query: str, limit: int = 8) -> list[sqlite3.Row]:
        # FTS5 is sensitive to punctuation; normalize to tokens.
        import re

        tokens = re.findall(r"[A-Za-z0-9_]+", query)
        if not tokens:
            return []
        q = " ".join(tokens)
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT path, content, bm25(chunks_fts) AS score
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (q, limit),
            ).fetchall()

    def replace_tasks_for_document(self, source_path: str, tasks: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM tasks WHERE source_path=?", (source_path,))
            conn.executemany(
                """
                INSERT INTO tasks(id, title, status, due_date, priority, effort, tags_json, source_path, source_anchor, created_ts, completed_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        t["id"],
                        t["title"],
                        t["status"],
                        t.get("due_date"),
                        t.get("priority"),
                        t.get("effort"),
                        json.dumps(t.get("tags", [])),
                        source_path,
                        t["source_anchor"],
                        t.get("created_ts") or _utc_now_iso(),
                        t.get("completed_ts"),
                    )
                    for t in tasks
                ],
            )

    def list_tasks(self, *, include_completed: bool) -> list[TaskRow]:
        with self.connect() as conn:
            where = "" if include_completed else "WHERE status != 'done'"
            rows = conn.execute(
                f"""
                SELECT id, title, status, due_date, priority, effort, source_path, source_anchor
                FROM tasks
                {where}
                ORDER BY
                  CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 9 END,
                  COALESCE(due_date, '9999-12-31'),
                  title
                """
            ).fetchall()

        result: list[TaskRow] = []
        for r in rows:
            due = None
            if r["due_date"]:
                try:
                    due = datetime.strptime(r["due_date"], "%Y-%m-%d").date()
                except Exception:
                    due = None
            result.append(
                TaskRow(
                    id=r["id"],
                    title=r["title"],
                    status=r["status"],
                    due_date=due,
                    priority=r["priority"],
                    effort=r["effort"],
                    source_path=r["source_path"],
                    source_anchor=r["source_anchor"],
                )
            )
        return result

    def upsert_events(self, events: Iterable[dict[str, Any]]) -> int:
        with self.connect() as conn:
            count = 0
            for e in events:
                conn.execute(
                    """
                    INSERT INTO events(id, title, start_ts, end_ts, timezone, all_day, recurrence_rule, source_path, source, source_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      title=excluded.title,
                      start_ts=excluded.start_ts,
                      end_ts=excluded.end_ts,
                      timezone=excluded.timezone,
                      all_day=excluded.all_day,
                      recurrence_rule=excluded.recurrence_rule,
                      source_path=excluded.source_path,
                      source=excluded.source,
                      source_id=excluded.source_id,
                      status=excluded.status
                    """,
                    (
                        e["id"],
                        e["title"],
                        e["start_ts"],
                        e.get("end_ts"),
                        e.get("timezone"),
                        int(bool(e.get("all_day", False))),
                        e.get("recurrence_rule"),
                        e.get("source_path"),
                        e.get("source"),
                        e.get("source_id"),
                        e.get("status"),
                    ),
                )
                count += 1
            return count

    def upsert_deadlines(self, deadlines: Iterable[dict[str, Any]]) -> int:
        with self.connect() as conn:
            count = 0
            for d in deadlines:
                conn.execute(
                    """
                    INSERT INTO deadlines(id, title, due_ts, timezone, source_path, source, source_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      title=excluded.title,
                      due_ts=excluded.due_ts,
                      timezone=excluded.timezone,
                      source_path=excluded.source_path,
                      source=excluded.source,
                      source_id=excluded.source_id,
                      status=excluded.status
                    """,
                    (
                        d["id"],
                        d["title"],
                        d["due_ts"],
                        d.get("timezone"),
                        d.get("source_path"),
                        d.get("source"),
                        d.get("source_id"),
                        d.get("status"),
                    ),
                )
                count += 1
            return count

    def delete_time_items_for_source_path(self, source_path: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM events WHERE source_path=?", (source_path,))
            conn.execute("DELETE FROM deadlines WHERE source_path=?", (source_path,))

    def list_events_between(self, *, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM events
                WHERE start_ts >= ? AND start_ts < ?
                ORDER BY start_ts
                """,
                (start_iso, end_iso),
            ).fetchall()

    def list_deadlines_between(self, *, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM deadlines
                WHERE due_ts >= ? AND due_ts < ?
                ORDER BY due_ts
                """,
                (start_iso, end_iso),
            ).fetchall()

    def upsert_outbox_item(self, rel_path: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO outbox_items(rel_path, status, created_ts, approved_ts)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT(rel_path) DO UPDATE SET
                  status=excluded.status
                """,
                (rel_path, status, _utc_now_iso()),
            )

    def set_outbox_approved(self, rel_path: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO outbox_items(rel_path, status, created_ts, approved_ts)
                VALUES (?, 'approved', ?, ?)
                ON CONFLICT(rel_path) DO UPDATE SET
                  status='approved',
                  approved_ts=excluded.approved_ts
                """,
                (rel_path, _utc_now_iso(), _utc_now_iso()),
            )

    def delete_outbox_item(self, rel_path: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM outbox_items WHERE rel_path=?", (rel_path,))

    def list_outbox_items(self) -> list[OutboxItemRow]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT rel_path, status FROM outbox_items ORDER BY rel_path"
            ).fetchall()
        return [OutboxItemRow(rel_path=r["rel_path"], status=r["status"]) for r in rows]
