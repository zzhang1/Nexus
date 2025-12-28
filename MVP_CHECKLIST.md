# Nexus AI MVP Build Checklist

Use this as a sequential checklist for a coding agent. It assumes the canonical product intent is in `README.md`, `Design.md`, and `REQUIREMENTS.md`.

## 0) Repo Scaffolding
- [ ] Create Python package skeleton (`src/nexus_ai/`) and `pyproject.toml`.
- [ ] Add CLI entrypoint `nexus` (Typer) with `--help` working.
- [ ] Add basic logging + error handling (human-readable CLI output).
- [ ] Add config loading: `.env` + `.assistant/config.yaml` + `.assistant/preferences.yaml`.
- [ ] Decide minimal dependency set and pin versions (document in `pyproject.toml`).

## 1) Workspace Initialization (`nexus init`)
- [ ] Implement `nexus init --root <path>` creating:
  - `.assistant/` (`nexus.db`, `vector_store/`, `config.yaml`, `preferences.yaml`, `logs/`)
  - `0_Inbox/`, `Source/`, `Knowledge/`, `Archive/`, `Outbox/`
  - `Knowledge/1_Projects`, `Knowledge/2_Areas`, `Knowledge/3_Resources`, `Knowledge/4_Archive`
- [ ] Initialize Git repo in `Knowledge/` (or ensure existing repo is supported).
- [ ] Write default `preferences.yaml` (timezone + minimal defaults).
- [ ] Acceptance check: running `init` twice is idempotent (no destructive overwrites).

## 2) Canonical Markdown Rules (Front Matter + IDs)
- [ ] Define minimal YAML front matter schema (write-only defaults):
  - required: `type`, `title`, `created`, `updated`, `status`
  - optional: `tags`
- [ ] Define a stable way to reference extracted tasks:
  - store `source_path` + `source_anchor` (e.g., heading + line hash) in DB
  - keep edits reversible and avoid rewriting note bodies unless requested
- [ ] Add a small Markdown writer utility (safe file creation + atomic writes).

## 3) Local DB Schema (Map: GraphRAG + Structured Time Items)
- [ ] Create SQLite schema migrations (even if simple) for:
  - documents/files (path, hash, modified time, front matter fields)
  - `tasks` (id, title, status, due_ts, priority, effort, created_ts, completed_ts, source_path, source_anchor)
  - `events` (id, title, start_ts, end_ts, timezone, all_day, rrule/recurrence_rule, source, source_id, status)
  - `deadlines` (id, title, due_ts, timezone, source, source_id, status)
- [ ] Create vector store initialization (persisted under `.assistant/vector_store/`).
- [ ] Wrap DB + vector operations behind interfaces used by the app (no direct coupling from CLI handlers).

## 4) Ingestion Pipeline (`nexus ingest`)
- [ ] Read `0_Inbox/` and for each file:
  - copy/move original into `Source/` and/or `Archive/` (preserve originals)
  - extract text via `markitdown` (pluggable extractor interface)
  - convert to “clean Markdown” (no summarization requirement)
  - choose a target path under `Knowledge/` (PARA top-level; create folders as needed)
  - write Markdown file with front matter
- [ ] Upsert Markdown content into the GraphRAG index (chunk → embed → store).
- [ ] Extract time items:
  - front matter dates (`due`, `scheduled`, `start/end`, `rrule` if present)
  - task lines (`- [ ] ...`) anywhere in Markdown
- [ ] Commit resulting changes to the `Knowledge/` Git repo.
- [ ] Acceptance check: drop a few files into `0_Inbox/` and confirm Markdown appears in `Knowledge/`, originals are preserved, and DB has rows.

## 5) Sync & Drift Handling (`nexus sync`)
- [ ] Scan `Knowledge/` for changes since last index:
  - new files, modified files, moved/renamed files, deleted files
- [ ] Update DB + vector store idempotently:
  - reindex modified files
  - remove vectors/rows for deleted files
  - update paths for renames
- [ ] Re-extract tasks/events/deadlines from affected files.
- [ ] Acceptance check: manually edit a note to add a task line, run `sync`, and verify task appears in planning output.

## 6) Planning Views (`nexus today|week|month` + `nexus tasks`)
- [ ] Implement `nexus tasks` (default: all open tasks; filters later).
- [ ] Implement `nexus today`, `nexus week`, `nexus month`:
  - pull time-window events/deadlines
  - pull due/overdue tasks and high-priority open tasks
  - output a prioritized list with links back to source notes
- [ ] Implement “draft time-blocking” rule:
  - only propose time blocks when calendar integration is present OR user provides availability
  - otherwise return list-only
- [ ] Add minimal prioritization heuristics:
  - parse `p:P1/P2/P3`, `due:`, `effort:`
  - if ambiguous and high-stakes, ask a short clarifying question (CLI prompt)
- [ ] Acceptance check: a note containing `- [ ] File taxes due:2026-04-15 p:P1` shows up appropriately in `week/month`.

## 7) Chat (`nexus chat`)
- [ ] Implement `nexus chat "<query>"` using GraphRAG retrieval + response synthesis.
- [ ] Add planning awareness:
  - route planning-like queries to the planning pipeline (or augment with structured time items)
- [ ] Keep answers grounded and link to files when referencing them.

## 8) Outbox (`nexus outbox ...`)
- [ ] Define Outbox item format (Markdown by default) and metadata (front matter optional):
  - type: `email_draft`, `itinerary`, `call_script`, `report`, `calendar_invite`, etc.
- [ ] Implement:
  - `nexus outbox list`
  - `nexus outbox open <id|path>`
  - `nexus outbox delete <id|path>`
  - `nexus outbox approve <id|path>` (record approval; later can trigger tool execution)
- [ ] Ensure Outbox is for deliverables only (not required for Knowledge edits).

## 9) Tools & Integrations (Read-Only First)
- [ ] Create a tool registry abstraction (MCP or direct APIs) with:
  - capability discovery
  - permission mode (`read_only` default; explicit enable for writes)
- [ ] Calendar integration MVP:
  - `nexus calendar sync` imports events into `events` table (read-only)
- [ ] Web search tool (optional in MVP, but wire the interface):
  - `search(query) -> results`
  - persist a sourced note into `Knowledge/3_Resources/` when used
  - extract any deadlines found into `deadlines`

## 10) Docs, Samples, and Validation
- [ ] Add a small “demo workflow” section to `README.md` once commands exist.
- [ ] Add a minimal sample dataset or scripted walkthrough (optional).
- [ ] Add smoke tests (or a `scripts/` runner) to verify:
  - init → ingest → sync → today/week → chat
- [ ] Re-check `REQUIREMENTS.md` acceptance checks and ensure each can be demonstrated.

