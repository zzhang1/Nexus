# Nexus AI MVP Build Checklist

Use this as a sequential checklist for a coding agent. It assumes the canonical product intent is in `README.md`, `Design.md`, and `REQUIREMENTS.md`.

## 0) Repo Scaffolding
- [x] Create Python package skeleton (`src/nexus_ai/`) and `pyproject.toml`.
- [x] Add CLI entrypoint `nexus` (Typer) with `--help` working.
- [ ] Add basic logging + error handling (human-readable CLI output).
- [x] Add config loading: `.env` + `.assistant/config.yaml` + `.assistant/preferences.yaml`.
- [x] Decide minimal dependency set and pin versions (document in `pyproject.toml`).

## 1) Workspace Initialization (`nexus init`)
- [x] Implement `nexus init --root <path>` creating:
  - `.assistant/` (`nexus.db`, `vector_store/` optional, `config.yaml`, `preferences.yaml`, `logs/`)
  - `0_Inbox/`, `Source/`, `Knowledge/`, `Archive/`, `Outbox/`
  - `Knowledge/1_Projects`, `Knowledge/2_Areas`, `Knowledge/3_Resources`, `Knowledge/4_Archive`
- [x] Initialize Git repo in `Knowledge/` (or ensure existing repo is supported).
- [x] Write default `preferences.yaml` (timezone + minimal defaults).
- [x] Acceptance check: running `init` twice is idempotent (no destructive overwrites).

## 2) Canonical Markdown Rules (Front Matter + IDs)
- [x] Define minimal YAML front matter schema (write-only defaults):
  - required: `type`, `title`, `created`, `updated`, `status`
  - optional: `tags`
- [x] Define a stable way to reference extracted tasks:
  - store `source_path` + `source_anchor` (e.g., heading + line hash) in DB
  - keep edits reversible and avoid rewriting note bodies unless requested
- [x] Add a small Markdown writer utility (safe file creation + atomic writes).

## 3) Local DB Schema (Map: Hybrid Retrieval + Structured Time Items)
- [x] Create SQLite schema migrations (even if simple) for:
  - documents/files (path, hash, modified time, front matter fields)
  - `tasks` (id, title, status, due_ts, priority, effort, created_ts, completed_ts, source_path, source_anchor)
  - `events` (id, title, start_ts, end_ts, timezone, all_day, rrule/recurrence_rule, source, source_id, status)
  - `deadlines` (id, title, due_ts, timezone, source, source_id, status)
- [x] Create vector store initialization (placeholder). Prefer sqlite-vec tables in `nexus.db` for embeddings; keep `.assistant/vector_store/` only if external stores are used.
- [x] Wrap DB + vector operations behind interfaces used by the app (no direct coupling from CLI handlers).
- [ ] Hybrid embedding search upgrade (later):
  - add vector embeddings stored via sqlite-vec in `nexus.db`
  - add hybrid retrieval (FTS5 + vector similarity)
  - add query re-ranking and caching
  - ensure embeddings are rebuildable from Markdown
- [ ] GraphRAG upgrade (later):
  - add entity extraction + graph tables (`nodes`, `edges`)
  - hybrid retrieval (FTS + vector + graph neighbors)
  - context assembly with relevance scores/citations

## 4) Ingestion Pipeline (`nexus ingest`)
- [x] Read `0_Inbox/` and for each file:
  - copy/move original into `Source/` (preserve originals)
  - extract text via pluggable extractor (current: PDF/DOCX/text fallback)
  - convert to “clean Markdown” (no summarization requirement)
  - choose a suggested target path under `Knowledge/` (PARA top-level; user folder structure is a hint, not a rule)
  - write Markdown file with front matter
- [x] Upsert Markdown content into the local index (chunking + SQLite FTS).
- [x] Extract time items:
  - front matter dates (`due`, `scheduled`, `start/end`, `rrule` if present)
  - task lines (`- [ ] ...`) anywhere in Markdown
- [x] Commit resulting changes to the `Knowledge/` Git repo.
- [x] Acceptance check: drop a few files into `0_Inbox/` and confirm Markdown appears in `Knowledge/`, originals are preserved, and DB has rows.
- [x] Intelligent filing (LLM-assisted):
  - inventory `Knowledge/` structure + tags + recent files
  - detect existing patterns (e.g., statements by bank/month)
  - retrieve nearest neighbors for new documents (heuristic for now; vector-based later)
  - have LLM choose destination folder + tags
  - auto-file and record a brief filing note (where/why)
- [ ] Advanced filing (depends on embedding similarity + graph expansion):
  - embedding-based nearest neighbor retrieval for filing
  - explicit pattern detection (e.g., monthly statements, recurring vendors)
  - re-ranking based on similarity + folder/tag consistency

## 5) Sync & Drift Handling (`nexus sync`)
- [x] Scan `Knowledge/` for changes since last index:
  - new files, modified files, moved/renamed files, deleted files
- [x] Update DB idempotently (reindex modified files, remove deleted rows).
  - reindex modified files
  - remove rows for deleted files
  - update paths for renames
- [x] Re-extract tasks/events/deadlines from affected files.
- [x] Acceptance check: manually edit a note to add a task line, run `sync`, and verify task appears in planning output.

## 6) Planning Views (`nexus today|week|month` + `nexus tasks`)
- [x] Implement `nexus tasks` (default: all open tasks; filters later).
- [x] Implement `nexus today`, `nexus week`, `nexus month`:
  - pull time-window events/deadlines
  - pull due/overdue tasks and high-priority open tasks
  - output a prioritized list with links back to source notes
- [x] Recurrence expansion for near-term horizons (RRULE).
- [x] Implement “draft time-blocking” rule:
  - only propose time blocks when calendar integration is present OR user provides availability
  - otherwise return list-only
- [x] Add minimal prioritization heuristics:
  - parse `p:P1/P2/P3`, `due:`, `effort:`
  - if ambiguous and high-stakes, ask a short clarifying question (CLI prompt)
- [x] Acceptance check: a note containing `- [ ] File taxes due:2026-04-15 p:P1` shows up appropriately in `week/month`.

## 7) Chat (`nexus chat`)
- [x] Implement `nexus chat "<query>"` using local retrieval + response synthesis.
- [x] Add planning awareness:
  - route planning-like queries to the planning pipeline (or augment with structured time items)
- [x] Keep answers grounded and link to files when referencing them.
- [x] Chat-driven knowledge updates (with approval):
  - detect when the user is asking to add/change knowledge
  - propose file ops (create/edit/move/delete) and show diffs
  - apply changes only after approval, then reindex + commit
- [x] Avoid no-op task edits (detect duplicates, skip and report “no changes needed”).
- [x] Improve file selection rules (prefer existing relevant files; ask clarifying questions before creating new files).
- [x] Add `nexus tidy` for LLM-guided cleanup with approval.

## 8) Outbox (`nexus outbox ...`)
- [ ] Define Outbox item format (Markdown by default) and metadata (front matter optional):
  - type: `email_draft`, `itinerary`, `call_script`, `report`, `calendar_invite`, etc.
- [x] Implement:
  - `nexus outbox list`
  - `nexus outbox open <id|path>`
  - `nexus outbox delete <id|path>`
  - `nexus outbox approve <id|path>` (record approval; later can trigger tool execution)
- [ ] Ensure Outbox is for deliverables only (not required for Knowledge edits).

## 9) Tools & Integrations (Read-Only First)
- [x] Create a tool registry abstraction (MCP or direct APIs) with:
  - capability discovery
  - permission mode (`read_only` default; explicit enable for writes)
- [x] Calendar integration MVP:
  - `nexus calendar sync` imports events into `events` table (read-only)
- [x] Google Calendar integration (read-only first):
  - OAuth client + token storage under `.assistant/`
  - sync via `syncToken` with bounded time window
  - calendar selection via config (default: primary)
  - surface warnings/errors in CLI/UI
- [x] Google Calendar write actions (post-read-only):
  - create/edit/delete events with explicit approval
  - write scopes and audit logging
- [ ] Web search tool (optional in MVP, but wire the interface):
  - `search(query) -> results`
  - persist a sourced note into `Knowledge/3_Resources/` when used
  - extract any deadlines found into `deadlines`

## 10) Docs, Samples, and Validation
- [x] Add a small “demo workflow” section to `README.md` once commands exist.
- [ ] Add a minimal sample dataset or scripted walkthrough (optional).
- [x] Add smoke tests (or a `scripts/` runner) to verify:
  - init → ingest → sync → today/week → chat
- [ ] Re-check `REQUIREMENTS.md` acceptance checks and ensure each can be demonstrated.

## 11) LLM-Assisted Territory Management (Post-MVP)
- [x] LLM-guided pruning/archiving suggestions for stale notes.
- [ ] File naming + metadata normalization (consistent titles/tags/front matter).
- [ ] Duplicate content detection + merge suggestions for notes.
- [ ] Task clustering / project rollups without moving tasks.
- [ ] Better context routing for new tasks to the most relevant file.
- [ ] Priority/urgency inference (Eisenhower-style) with user confirmation when stakes are high.
- [ ] Calendar conflict detection when creating or importing events.
- [ ] Weekly “what changed” digest from Knowledge Git history.
- [ ] Auto-refactoring of ad-hoc notes into canonical systems (e.g., Home Maintenance).

## 12) UX & Interaction (Post-MVP)
- [ ] Persistent chat session mode (REPL-style), maintaining context across turns.
