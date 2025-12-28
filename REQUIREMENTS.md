# Nexus AI — Product Requirements (MVP)

## Product Goal
Help a user stay organized and productive by turning their existing files and notes into a local-first knowledge base that can answer questions and produce time-aware plans (“today / this week / this month”) grounded in real documents and calendars.

## Core Principles
- **Local-first ownership:** `Knowledge/` Markdown is the canonical record (“territory”). Derived indexes are replaceable (“map”).
- **CLI-first experience:** Users primarily interact via `nexus ...` commands (web app later).
- **Safe action delivery:** Outbound artifacts are staged in `Outbox/` for review.
- **Extensible tools:** External systems (calendar/email/contacts/tasks/web search) are accessed via tools (MCP or APIs) with permission escalation.

## Functional Requirements
### Ingestion & Organization
- Ingest files from `0_Inbox/`, extract text, and write a Markdown representation into `Knowledge/` using PARA as the top-level structure.
- Preserve originals under `Source/` and/or `Archive/` (no destructive edits to originals).
- Create/edit files in `Knowledge/` as part of normal assistant operation and commit changes to the `Knowledge/` Git repo.
- Support user-defined subfolders under PARA and allow Nexus to create/move folders/files when instructed.

### Knowledge Retrieval (GraphRAG “Map”)
- Build and maintain a local GraphRAG index from `Knowledge/` content (and structured metadata below).
- Provide answers grounded in `Knowledge/` and linked sources; do not treat the index as authoritative if it conflicts with Markdown.
- Provide `nexus sync` to detect changes (user edits, new files, moves) and update the index idempotently.

### Time Awareness, Planning, and Tasks
- Extract **deadlines/events** from front matter and **tasks** from Markdown task lines (`- [ ] ...`) anywhere in `Knowledge/`.
- Store normalized `tasks/events/deadlines` in SQLite for fast “today/week/month” queries.
- `nexus today|week|month` returns:
  - a prioritized list (default), and
  - a draft time-block plan only when calendar data or user-supplied availability makes it reasonable.

### Outbox (Deliverables)
- Stage ready-to-use artifacts in `Outbox/` (email drafts, calendar invites, travel plans, call scripts, reports).
- Provide commands to list/open/approve/delete Outbox items.
- Outbox is not required for routine edits inside `Knowledge/`.

### Integrations & Web Search
- Integrations are tool-driven and start **read-only** by default; writes require explicit enablement.
- Web search is available as a tool for well-known deadlines/facts; results must be persisted into `Knowledge/` with dates and sources, and any extracted deadlines must enter the structured deadline store.

## Non-Goals (MVP)
- No full-featured GUI/web app (CLI only).
- No automatic “master task index” file in `Knowledge/` (use CLI views instead).

## Validation (Acceptance Checks)
- Given a mixed set of PDFs/images/docs in `0_Inbox/`, `nexus ingest` produces Markdown in `Knowledge/` and archives originals.
- Editing a Markdown file manually, then running `nexus sync`, updates the index and planning outputs.
- A note containing `- [ ] File taxes due:2026-04-15 p:P1` appears in `nexus today|week` at the right time.
- Calendar events imported via integration affect time-window answers and (when enabled) time-block proposals.
- Outbox artifacts can be reviewed and approved without mutating unrelated Knowledge files.

