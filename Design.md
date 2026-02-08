1.  **Territory (Storage):** Markdown files in `Knowledge/`. (Human-readable, Git-versioned source of truth).
2.  **Map (Compute):** A hybrid retrieval index (SQLite + FTS5 + sqlite-vec embeddings). (AI-optimized navigation layer).
3.  **Abstraction:** A strict `KnowledgeBaseInterface` that prevents the application logic from coupling with specific database technologies.



# Project Specification: Nexus AI (Hybrid Retrieval Edition)

**Role:** Expert Python Architect & Developer.
**Goal:** Build a modular, local-first AI assistant CLI (MVP).
**Architecture Pattern:** "Map vs. Territory". The system manages a user's files (Territory) and builds a derived hybrid retrieval index (Map) for search.
**Constraint:** The Knowledge Graph/Vector implementation must be strictly abstracted behind an interface to allow for future backend swaps.
**Time-Awareness:** The system must understand time-based data (deadlines, events, recurrences) and answer queries like “What should I do today/this week?” using explicit temporal reasoning.
**Knowledge Ownership:** The assistant must be able to create and edit Markdown files in `Knowledge/`, with all changes tracked in Git.
**CLI-First UX:** The primary interface is CLI (and later web chat). The folder structure is “territory” for durability; users primarily interact through queries and generated plans.

For MVP product requirements and acceptance checks, see `REQUIREMENTS.md`.

### Knowledge Curation (Organize and Reorganize)
Nexus should be able to keep the territory tidy over time:
*   Propose where to file new knowledge (PARA + user subfolders) and create folders when needed.
*   Reorganize on instruction (e.g., “Create a tax folder and organize by year”), using Git commits so moves are reversible.

## 1. Core Architecture

### Directory Structure
The application operates on a user-defined root.
```text
/User_Root/
├── .assistant/             # System Data
│   ├── nexus.db            # SQLite (File Metadata + Relational Graph)
│   ├── vector_store/       # Optional external vector store persistence (unused if sqlite-vec lives in nexus.db)
│   ├── config.yaml         # User settings
│   ├── preferences.yaml    # User preferences (timezone/planning defaults)
│   └── logs/
├── 0_Inbox/                # Ingestion landing zone
├── Source/                 # Original user files (Immutable)
├── Knowledge/              # AI-managed Markdown files (Git Repo)
├── Outbox/                 # Draft actions awaiting review
└── Archive/                # Reserved for future use (unused by ingest today)
```

**PARA structure (within `Knowledge/`):**
*   `1_Projects/` — short-term, goal-driven work with a clear outcome and deadline.
*   `2_Areas/` — long-term responsibilities to maintain (no fixed end date).
*   `3_Resources/` — reference material, notes, and general knowledge.
*   `4_Archive/` — completed or inactive items from Projects/Areas/Resources.
*   **Customization:** Users may add subfolders under PARA (e.g., `People/`, `Real_Estate/`, `Wealth_Management/`) without breaking the model.

**Outbox usage:**
*   Ready-to-use deliverables (email drafts, calendar invites, travel plans, call scripts, reports) are staged in `Outbox/` for explicit review.
*   Editing/creating files in `Knowledge/` is a core capability and should not require Outbox staging; it should be Git-tracked and reversible.
*   The CLI should provide commands to list, approve, or delete Outbox items.

### Time-Aware Data Model (Explicit)
Add a calendar-aware layer in the structured store to support scheduling queries and integrations. Store normalized event/deadline metadata so the assistant can reason over time windows.

**Recommended tables (SQLite):**
*   `events` (id, title, start_ts, end_ts, timezone, all_day, recurrence_rule, source, source_id, priority, status)
*   `deadlines` (id, title, due_ts, timezone, source, source_id, priority, status)
*   `tasks` (id, title, status, due_ts, priority, effort, created_ts, completed_ts, source_path, source_anchor, source, source_id)
*   `event_links` (event_id, file_path, entity_id) for linking to knowledge records

**Sources of time-aware items:**
*   Parsed from Markdown front-matter (e.g., `due: 2026-04-15`, `scheduled: 2026-01-10T15:00-05:00`)
*   Recurring events via RRULE in front matter (e.g., `recurrence: "FREQ=WEEKLY;BYDAY=SA"`), optionally with `duration` when `end` is omitted
*   Parsed from Markdown task lines anywhere in `Knowledge/` (e.g., `- [ ] File taxes due:2026-04-15 p:P1`)
*   Imported from integrations (Google Calendar, Outlook, etc.) via MCP or provider APIs

**Query support:**
*   `today/this week/this month` windows resolved by local timezone
*   Recurrence expansion for near-term horizons (RRULE)
*   Merge “tasks + events + deadlines” for prioritization prompts
*   Optional time-blocking: propose a draft schedule only when calendar data or user-provided availability is sufficient; otherwise return a prioritized list

### Prioritization (Simple, Explainable)
The assistant should produce plans that feel useful without requiring heavy user configuration.

**MVP fields:**
*   `priority` (e.g., `P1/P2/P3`) and optional `importance/urgency` (Eisenhower-style) when it helps explain tradeoffs.
*   `effort` (rough estimate like `15m`, `2h`) when available.

**Behavior:**
*   Make reasonable guesses from language and context (deadlines, recurrence, consequences).
*   Ask clarifying questions when stakes are high or scheduling decisions would meaningfully change the day (“Is this due today or sometime this week?”).
*   Keep the output grounded: link each recommended action back to its source note/file.

### Task Representation (Territory) vs. Planning (Map)
Tasks may appear anywhere in `Knowledge/` as Markdown checkboxes. Most tasks should live inline with their context; they do not need to become “one file per task”.

**Guideline:**
*   Keep tasks in their source notes; use CLI views for aggregation (avoid a constantly-updating “master task index” file in `Knowledge/`).
*   Planning views should include all tasks by default; optional filters can narrow by tags/folders when the user asks.
*   Optionally “promote” a task into its own Markdown file when it needs substantial notes, subtasks, or becomes a project.

### Web Knowledge (Deadlines and Facts)
For well-known deadlines (e.g., tax filing) and factual lookups, the assistant should be able to use a web search tool and then persist results back into `Knowledge/` with sources and dates.

**Guidelines:**
*   Web results are treated as inputs; the canonical record is a Markdown note with citations/links and extracted deadlines stored in `deadlines`.
*   Prefer conservative phrasing when jurisdiction/user specifics are unknown; ask clarifying questions when needed.

### Tags and Folder Profiles (Optional, Folder-First)
Treat tags (including optional `ctx`) as lightweight helpers. The folder structure is the primary organizer; tags are inferred by default and only need to be explicit when the user wants cross-cutting views.

**Folder profiles (optional, user-editable):**
*   Any folder under `Knowledge/` may contain a `.nexus.yaml` file that declares default metadata for files and tasks in that subtree.
*   Profiles inherit downward unless overridden by a closer `.nexus.yaml` or file front matter.

Example `Knowledge/2_Areas/Home/.nexus.yaml`:
```yaml
defaults:
  tags: [home]
```

**File front matter (canonical territory):**
*   Files created by Nexus always include YAML front matter.
*   On ingest/sync, Nexus may add missing keys (minimal normalization), but must not “fight the user” by overwriting explicit values.

**Inference precedence (highest → lowest):**
1) Explicit inline task fields (e.g., `due:2026-01-15`, `p:P1`, optional `ctx:work`)
2) File front matter (`tags`, `type`, `area`, `project`, optional `ctx`)
3) Nearest folder profile `.nexus.yaml` defaults (inherited)
4) Path heuristics (example mapping: `1_Projects/** => tags: [project]`, `2_Areas/** => tags: [area]`)
5) Global defaults from `.assistant/preferences.yaml`

**DB representation:**
*   Store both canonical and derived fields, e.g. explicit `tags` plus `inferred_tags` and confidence scores.
*   This supports “best effort” planning while keeping the user’s Markdown as the source of truth.

### The Interface Abstraction (Crucial)
The application logic must **never** talk directly to ChromaDB or SQLite for retrieval. It must use a `KnowledgeBaseEngine` abstract base class.

*   **`ingest_document(path, text, metadata)`**: Handles chunking, embedding, entity extraction, and storage.
*   **`search(query)`**: Returns a list of relevant `Document` objects or text chunks based on hybrid search (Vector + Graph traversal).
*   **`delete_document(path)`**: Handles cleanup of vectors and graph nodes when a file is removed.

### Retrieval Roadmap (MVP → Hybrid Embeddings → GraphRAG)
**MVP (current):**
*   Chunk Markdown content and store it in SQLite + FTS for fast keyword retrieval.
*   Use structured tables (`tasks/events/deadlines`) for time-aware planning queries.

**Planned hybrid embedding search (FTS5 + sqlite-vec):**
*   **Enable sqlite-vec:** load the extension and create an `embeddings` table keyed by chunk IDs in `nexus.db`.
*   **Chunk/embedding pipeline:** compute embeddings per chunk during ingest/sync; store vectors with model/version metadata.
*   **Hybrid retrieval:** run FTS5 keyword search and sqlite-vec vector similarity; merge, de-dupe, and re-rank.
*   **Quality controls:** prefer lexical matches for exact phrases, fallback to FTS5 when embeddings are missing, and cache query embeddings.
*   **Rebuildability:** treat embeddings as derived from Markdown; allow full rebuilds when models change.

**Later GraphRAG upgrade:**
*   **Graph:** extract entities/relationships into `nodes/edges` tables linked to source files and chunks.
*   **Graph expansion:** enrich candidate chunks with 1-hop neighbor retrieval.
*   **Hybrid retrieval:** combine FTS5 + sqlite-vec + graph neighborhood expansion.
*   **Re-ranking + citations:** score retrieved context, dedupe, and produce answers/plans with file citations.

## Backlog (Ideas to Consider)
These are product/UX patterns seen in modern assistants that fit Nexus’s “persistent knowledge + approval-first edits” philosophy.

*   **Global quick access:** a global hotkey / command palette that opens `nexus chat` / `nexus today` instantly (later: tray app).
*   **Better diff review UX:** side-by-side preview, clearer change summaries, and “accept/reject” per change (trust + safety).
*   **Auto-organization rules (user-steerable):** translate natural-language rules into `.nexus.yaml` defaults (and/or explicit rule files).
*   **Dynamic planning / rescheduling (calendar-aware):** propose time blocks and reshuffle when availability or deadlines change (opt-in).
*   **Web source discovery flow:** “discover sources → show why → user selects → persist sourced note into Knowledge/” (auditable research).
*   **Domain-specific email workflows:** email ingestion, summarization, and draft replies as tool modules (read-only by default; Outbox for drafts).

## Chat Intent Model (Formal)
All chat interactions resolve to one of three explicit intents, which drives behavior and permissions:

*   **Answer:** Informational response grounded in `Knowledge/` (no file writes).
*   **Plan:** A time-window view (`today|week|month`) that merges events, deadlines, and tasks.
*   **Actions:** Structured file edits under `Knowledge/`, always previewed with diffs and requiring user approval.

This intent model allows both free-form chat and CLI commands (`nexus chat ...`) to be deterministic and safe.

**Tool loop (internal):** The model may request read-only tools using `mode: "tool"` during a multi-step loop. The final response shown to the user must still be `answer`, `plan`, or `actions`.

### Action Schema (JSON)
When the intent is **Actions**, the model must return JSON that specifies edits under `Knowledge/`:
```json
{
  "mode": "actions",
  "note": "short explanation",
  "actions": [
    {"type": "append_task", "path": "2_Areas/Home/Home.md", "task": "- [ ] ... due:YYYY-MM-DD p:P1", "create_if_missing": true},
    {"type": "create_file", "path": "3_Resources/...", "content": "..."},
    {"type": "replace_file", "path": "2_Areas/...", "content": "..."},
    {"type": "edit_block", "path": "2_Areas/...", "old": "exact block", "new": "replacement block"},
    {"type": "move_file", "from": "3_Resources/Old.md", "to": "3_Resources/New.md"},
    {"type": "delete_file", "path": "4_Archive/Old.md"}
  ]
}
```

**Safety & behavior:**
* Paths must be relative to `Knowledge/` and must not start with `.` or contain `..`.
* `edit_block` replaces the first exact match of `old` in the file.
* All actions are previewed as diffs and require approval before being applied.

### Read-Only Tool Actions (JSON)
Before proposing edits, the model may request read-only tools using `mode: "tool"`. These do not modify files and must be followed by a final `answer|plan|actions` response.
```json
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "search", "args": {"query": "keyword", "limit": 8}}]}
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "find_files", "args": {"query": "keyword", "limit": 20}}]}
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "list_files", "args": {"root": "Knowledge/", "recursive": true, "limit": 1000}}]}
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "read_file", "args": {"path": "2_Areas/Home/Home.md", "max_chars": 4000}}]}
```

## 2. Tech Stack

*   **Language:** Python 3.10+
*   **Core API:** `typer` (CLI), `pydantic` (Data Validation).
*   **LLM Interface:** `litellm` with modular providers (OpenRouter default; OpenAI and Ollama supported).
*   **Default Provider:** Use OpenRouter by default via `litellm` (configurable for OpenAI or Ollama in `.assistant/config.yaml`).
*   **Ingestion:** `markitdown` (Text Extraction).
*   **Vector/Graph Store:**
    *   *Interface:* Abstract Python Class.
    *   *Implementation (MVP):* `sqlite3` + FTS5 for lexical search, with `sqlite-vec` planned for embeddings in the same `nexus.db`.
*   **Graph Logic:** `networkx` (Optional, for in-memory traversal algorithms).
*   **Version Control:** `GitPython`.
*   **Integrations:** MCP clients and/or provider APIs for calendar, email, contacts, and task sources (Google Calendar, Outlook, CalDAV, IMAP, etc.).
*   **Permissions:** Start read-only by default; require explicit enablement for write scopes and/or execution.
*   **Interface Roadmap:** Start with a CLI MVP; plan a web app once ingestion, retrieval, and time-aware workflows are stable.

### Preferences (MVP)
Store user preferences separately from system config to keep behavior predictable and easy to tune. Keep it small and composable.

Example `.assistant/preferences.yaml`:
```yaml
timezone: America/New_York
defaults:
  tags: []
```

## 3. Implementation Plan

### Phase 1: Foundation & Abstraction

**1.1 Project Scaffolding**
*   Create `src/nexus_ai/` structure.
*   Setup `config.py` to load YAML config and `.env` secrets.

**1.2 The Knowledge Interface (`src/nexus_ai/knowledge_base/interface.py`)**
*   Define the `AbstractKnowledgeBase` class.
    ```python
    class AbstractKnowledgeBase(ABC):
        @abstractmethod
        def upsert_document(self, file_path: str, content: str, metadata: dict): pass

        @abstractmethod
        def query(self, query_text: str, n_results: int = 5) -> List[SearchResult]: pass
        
        @abstractmethod
        def get_graph_context(self, file_path: str) -> str: pass # Returns related entities
    ```

**1.3 The Concrete Implementation (`src/nexus_ai/knowledge_base/simple_rag.py`)**
*   Implement `SimpleHybridSearch` inheriting from the interface.
*   **SQLite Store:** Initialize `sqlite3` in `.assistant/nexus.db` with:
    *   `chunks` (id, file_path, content, metadata)
    *   `chunks_fts` (FTS5 virtual table for lexical search)
    *   `embeddings` (sqlite-vec table keyed by chunk id, vector, model metadata)
*   **Logic:**
    *   `upsert`: Chunk text -> Store in `chunks` + `chunks_fts`; compute embeddings (via `litellm.embedding`) and store vectors via sqlite-vec.
    *   **Graph (later):** Extract entities and store in `nodes`/`edges` tables for graph expansion.

### Phase 2: Ingestion Pipeline (`src/nexus_ai/ingest.py`)

**2.1 File Processor**
*   Use `markitdown` to extract text from `0_Inbox` files.
*   Calculate SHA-256 hash.

**2.2 The "Markdownification" Step**
*   Convert extracted text into clean Markdown (no summarization required).
*   **Crucial:** The prompt must ask the LLM to identify "Key Entities" and "Relationships" in a structured block (JSON or YAML) at the end of the generation, to feed the Graph.
*   **Time extraction:** Detect dates, deadlines, and scheduled events; normalize into structured fields and write to the `events`/`deadlines` tables.
*   **Task extraction:** Parse Markdown task lines (`- [ ] ...`) anywhere in `Knowledge/` and normalize into the `tasks` table (see inference rules above).
*   **Front matter:** Ensure new Markdown files include minimal YAML front matter (at least `type`, `title`, `created`, `updated`, `status`, optional `tags`).

**2.3 Storage & Sync**
*   Write the Markdown file to `Knowledge/`.
*   Call `knowledge_engine.upsert_document()` with the new Markdown content.
*   Move original to `Source/`.
*   Commit to Git.
*   **Initial run:** Treat the first execution as a larger `0_Inbox` ingestion (no separate “cold start” system required).

### Phase 3: The Chat Loop (`src/nexus_ai/chat.py`)

**3.1 Retrieval Augmented Generation**
*   **Step A (Search):** Call `knowledge_engine.query(user_input)`.
    *   *MVP Implementation:* Perform FTS5 keyword search for relevant chunks.
    *   *Planned Hybrid:* Combine FTS5 with sqlite-vec vector similarity, then re-rank and de-dupe.
    *   **Time window retrieval:** If query implies a time range (today/this week), fetch events/deadlines within that window.
    *   **Task retrieval:** For planning queries, pull tasks by due date/status and link back to their source notes.
*   **Step B (Synthesize):** Construct System Prompt.
    ```text
    Context from Knowledge Base:
    {retrieved_chunks}

    Related Graph Concepts:
    {related_entities_and_edges}

    Time Window (Local TZ):
    {events_and_deadlines}
    ```
*   **Step C (Generate):** Call `litellm.completion` with the prompt and user input.

### Phase 4: CLI Assembly (`src/nexus_ai/main.py`)

*   `nexus init`: Setup folders, DBs, and default Config.
*   `nexus ingest`: Run the pipeline on `0_Inbox`.
*   `nexus chat [query]`: Run the RAG loop.
*   `nexus sync`: Detect changes in `Knowledge/` (and `Source/` where relevant) and update the retrieval index + structured stores idempotently.
*   `nexus calendar sync`: Pull calendar events from integrations and update `events`.
*   `nexus today|week|month`: Summarize across tasks, deadlines, and events; optionally propose time blocks.
*   `nexus outbox list|open|approve|delete`: Manage staged deliverables.

## 4. Operational Directives (Agents.md Draft)

*Include a file `AGENTS.md` in the repo to guide the AI's behavior:*

*   **Graph Consistency:** "When modifying a file, you must identify if entities (People, Projects) have changed and update the graph representation accordingly."
*   **Source of Truth:** "The Markdown file is the master record. The Vector Index is a search tool. If they conflict, trust the Markdown."
*   **Time Normalization:** "Store all times with timezone, normalize to local time for queries, and keep raw source metadata for traceability."
*   **Clarify When Needed:** "If priority/urgency is ambiguous and the decision affects scheduling or external actions, ask a short clarifying question instead of guessing silently."
*   **Tool Safety:** "Use integrations in read-only mode by default; stage outbound artifacts in Outbox unless the user has explicitly enabled write scopes and approved execution."
