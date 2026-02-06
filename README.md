# Nexus AI: Local-First, Privacy-Centric Knowledge Assistant

**Nexus AI** is a command-line personal assistant that turns your static files into a living, intelligent knowledge base. It operates entirely on your local machine, respecting your privacy and ownership of data.

By combining local document processing, Git-based versioning, and Large Language Models (LLMs), Nexus AI organizes your chaotic "My Documents" folder into a structured, chat-able Markdown library.

See `REQUIREMENTS.md` for the MVP scope and acceptance checks.

---

## 🚀 Core Features

*   **📥 Smart Ingestion:** Drop PDFs, spreadsheets, images, or docs into `0_Inbox/`. Nexus extracts text, converts it to clean Markdown, and auto-files it based on existing Knowledge patterns (with a short filing note).
*   **🧠 Context-Aware Chat:** Ask questions like "What was the budget for Project Alpha?" or "Who is the contact for the ACME contract?" Nexus answers based on your actual files.
*   **🗂️ PARA Organization (Flexible):** Uses PARA at the top level, with user-defined subfolders (e.g., `Taxes/`, `People/`, `Real_Estate/`, `Wealth_Management/`) and guided reorganizations when asked.
*   **🔗 Mirror Structure:** Keeps your original source files safe in a `Source` directory while maintaining a parallel, pure-Markdown `Knowledge` directory for the AI to work with.
*   **✅ Tasks From Anywhere:** Finds tasks, deadlines, and events embedded in your notes and uses them for planning.
*   **📤 Outbox for Deliverables:** Stages ready-to-use artifacts (email drafts, travel plans, call scripts, calendar invites) in `Outbox/` for review.
*   **🛡️ Git-Backed Knowledge:** Changes to `Knowledge/` (by you or the AI) are committed to a local Git repository for a complete, undoable history.
*   **🔍 Local Retrieval Index (MVP):** Uses a local SQLite full-text index (“map”) derived from your Markdown (“territory”) for fast retrieval.
*   **🗓️ Time-Aware Assistance:** Understands deadlines, recurring events, and “what should I do today/this week?” queries by tracking time-based metadata and calendar integrations.
*   **🔌 Extensible Tools:** Connects to calendars, email, contacts, and task systems via MCP or provider APIs as needed.
*   **🌐 Optional Web Research:** Uses web search as a tool for public facts (e.g., standard deadlines) and persists sourced notes back into `Knowledge/`.

---

## 🛠️ Technical Architecture

Nexus AI is built with a modular, API-first philosophy using Python 3.10+.

*   **CLI:** Built with `typer` and `rich` for a beautiful terminal experience.
*   **LLM Engine:** Uses `litellm`, defaulting to OpenRouter (configurable for other providers/models).
*   **Extraction:** Uses `markitdown` for text extraction (pluggable).
*   **Storage:**
    *   **Unstructured:** Standard Markdown files (`.md`) with YAML front-matter.
    *   **Structured:** SQLite for file maps, caching, and entity relationships.
    *   **Version Control:** `GitPython` for automated repository management.
*   **Time Awareness:** Stores deadlines, dates, and recurrence in structured metadata and can sync with external calendars via MCP or provider APIs.
*   **Adaptive Defaults:** Infers tags/context from folder structure; optional `Knowledge/**/.nexus.yaml` files add defaults without forcing manual tagging.
*   **Safety Posture:** Integrations start read-only; write actions are proposed/staged as deliverables unless explicitly enabled.
*   **Tooling:** External capabilities (calendar/email/web search) are exposed as tools and can be added incrementally.
*   **Interfaces:** MVP starts as a CLI; a web app is planned after core workflows stabilize.

Planned: upgrade retrieval from SQLite full-text search to GraphRAG (hybrid search with embeddings + entity graph). See `Design.md` and `MVP_CHECKLIST.md`.

---

## 📦 Installation

### Prerequisites
*   Python 3.10 or higher
*   Git installed and available in your terminal

### Steps

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/yourusername/nexus-ai.git
    cd nexus-ai
    ```

2.  **Set Up Virtual Environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install .
    ```

4.  **Environment Setup:**
    Create a `.env` file in the project root to store your API keys:
    ```bash
    OPENROUTER_API_KEY=sk-...
    # optional alternatives
    # OPENAI_API_KEY=sk-...
    # ANTHROPIC_API_KEY=sk-...
    ```

### LLM Providers (OpenRouter / OpenAI / Ollama)
Configure the provider in `.assistant/config.yaml`:
```yaml
llm:
  provider: openrouter   # openrouter | openai | ollama
  model: xiaomi/mimo-v2-flash:free   # strong model (default)
  weak_model: xiaomi/mimo-v2-flash:free   # weak model for enrichment/tagging
  # base_url: http://localhost:11434   # required for ollama if non-default
  enrich:
    enabled: true
    max_chars: 12000
```
Notes:
- **OpenRouter** uses `OPENROUTER_API_KEY`.
- **OpenAI** uses `OPENAI_API_KEY`.
- **Ollama** runs locally and needs no API key (default base URL: `http://localhost:11434`).

---

## 🚦 Getting Started

### 1. Initialize Your Workspace
Tell Nexus where you want your knowledge base to live. It will create the necessary `Source`, `Knowledge`, and `Inbox` folders there.

```bash
nexus init --root ~/Documents/MyNexusKnowledgeBase
```

If something isn’t working (missing API keys, bad timezone, etc.), run:
```bash
nexus doctor
```

### 2. Ingest Documents
Drag some files (PDFs, receipts, notes) into the `0_Inbox` folder created inside your root directory. Then, tell Nexus to process them:

```bash
nexus ingest
```
*Nexus will read the files, convert them to Markdown, file them into `Knowledge/`, move the originals into `Source/`, and commit the changes to Git.*

You can also drop entire folders into `0_Inbox/`. Nexus will ingest files recursively and use the folder names as hints for where to file notes (PARA remains the top-level structure).
When AI enrichment is enabled, Nexus also looks at existing Knowledge folder patterns and similar files to choose a destination and records a brief filing note under `Knowledge/3_Resources/Filing_Notes/`.
Ingest runs in review mode by default: all proposed changes are shown with diffs, and nothing is applied unless you approve. If you decline, the files stay in `0_Inbox/`.

If you manually edit Markdown files in `Knowledge/`, re-index with:
```bash
nexus sync
```

### 3. Chat with Your Data
Now, simply ask a question:

```bash
nexus chat "Summarize the key action items from the meeting notes I just added."
```
If your request implies an update to your knowledge base (e.g., “Add that I need to clean the gutters by next month”), Nexus will propose a change, show a diff, and ask for approval before writing to `Knowledge/` and reindexing.
You can also ask time-based questions:
```bash
nexus chat "What should I do today?"
```

Or use the planning views directly:
```bash
nexus today
nexus today --availability 09:00-17:00
nexus week
nexus month
```

**Chat intents (formal):** each chat response is classified into one of three modes:
* **Answer** — informational response grounded in `Knowledge/` (no file changes).
* **Plan** — time-aware view for `today|week|month`, combining events/deadlines/tasks.
* **Actions** — structured file edits in `Knowledge/` with diffs + user approval.

This intent model is used both for interactive chat and CLI commands that proxy to chat (e.g., `nexus chat "What should I do today?"` produces a **Plan**).

**Action JSON (formal):** chat actions use structured JSON. Nexus validates paths, previews diffs, and requires approval.
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

**Read-only tool calls (JSON):** the model can fetch context before editing, then return final actions. Tools use `mode: "tool"` with `tool_calls`.
```json
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "search", "args": {"query": "keyword", "limit": 8}}]}
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "find_files", "args": {"query": "keyword", "limit": 20}}]}
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "list_files", "args": {"root": "Knowledge/", "recursive": true, "limit": 1000}}]}
{"mode": "tool", "tool_calls": [{"id": "t1", "type": "read_file", "args": {"path": "2_Areas/Home/Home.md", "max_chars": 4000}}]}
```
Tool results are returned to the model as:
```json
{"tool_results": [{"id": "t1", "type": "search", "ok": true, "result": {"results": []}}]}
```

### Web UI (Local)
For a lightweight, local web UI that mirrors the CLI workflows:
```bash
pip install .[ui]
nexus ui
```
The UI uses the same workspace and safety model (review diffs before applying changes).

### 4. Track Tasks in Notes
Add tasks anywhere in `Knowledge/` using Markdown checkboxes with optional inline metadata:
```md
- [ ] File taxes due:2026-04-15 p:P1
- [ ] Repaint door p:P2 effort:2h
```
Then run `nexus sync` and view them with `nexus tasks`.

### 5. Recurring Events (Markdown + Chat)
Recurring events are captured in front matter using RRULE (RFC5545), which is also compatible with Google/Apple calendars.
Example:
```yaml
---
type: event
title: Mow lawn
start: 2026-01-04T09:00:00-05:00
duration: 1h
recurrence: "FREQ=WEEKLY;INTERVAL=2;BYDAY=SU"
---
```
The planner expands recurrences within the current window for `today/week/month`.

---

## ✅ Commands (CLI)
All commands accept `--root` / `-r` to point at a workspace (otherwise auto-discovered).

**Workspace + Index**
```bash
nexus init --root /path/to/workspace
nexus ingest
nexus ingest --no-review
nexus sync
nexus doctor
```

**Planning & Tasks**
```bash
nexus today
nexus today --availability 09:00-17:00
nexus week
nexus month
nexus tasks
```

**Chat + Cleanup**
```bash
nexus chat "What should I do today?"
nexus tidy --focus home
nexus tidy --stale-days 90
```

**Web UI**
```bash
nexus ui
```

**Calendar**
```bash
nexus integrations mode
nexus integrations list
nexus integrations set-mode write_enabled
nexus calendar auth
nexus calendar auth --write
nexus calendar sync
nexus calendar create --calendar-id primary --title "Focus block" --start "2026-02-10T09:00:00-05:00" --end "2026-02-10T10:00:00-05:00"
nexus calendar update --source-id primary:EVENT_ID --title "Updated title" --event-type keep
nexus calendar delete --source-id primary:EVENT_ID
```
Google Calendar support (read-only sync) requires extra deps:
```bash
pip install .[gcal]
```
Set `calendar.google.client_secrets_path` (OAuth client JSON) in `.assistant/config.yaml`, then run `nexus calendar auth`.
For create/update/delete commands, run `nexus calendar auth --write` to grant write scope.

**Google Calendar Configuration (`.assistant/config.yaml`)**
```yaml
calendar:
  ics_paths:
    - "/absolute/path/to/personal.ics"

  google:
    enabled: true
    client_secrets_path: "/absolute/path/to/google_client_secret.json"
    token_path: ""               # optional; defaults to .assistant/google_calendar_token.json
    calendar_ids:
      - "primary"
    sync_past_days: 30
    sync_future_days: 365

integrations:
  mode: "read_only"           # read_only | write_enabled
```

**Google Calendar Write Notes**
- `nexus calendar create|update|delete` are explicit write operations and require confirmation unless `--yes` is passed.
- External writes are blocked unless `integrations.mode` is set to `write_enabled` (use `nexus integrations set-mode write_enabled`).
- `nexus calendar update` accepts either `--source-id <calendar_id>:<event_id>` or both `--calendar-id` and `--event-id`.
- `nexus calendar update --event-type` accepts `keep|all_day|timed`.
- Calendar sync/write data is stored in `.assistant/nexus.db` (`events` table), and Google sync state is stored in `.assistant/google_calendar_sync.json`.
- Write audits are logged under `.assistant/logs/` as `action_audit_calendar_write_*.json`.
- The web UI `/calendar` page also supports create/update/delete with explicit approval checkboxes.

**Outbox**
```bash
nexus outbox list
nexus outbox open drafts/email.md
nexus outbox approve drafts/email.md
nexus outbox delete drafts/email.md
```

## 📂 Directory Structure (User Data)

When you run `init`, Nexus creates this structure on your computer:

```text
/Your_Root_Folder/
├── .assistant/             # Database, Config, Preferences, Logs (Hidden)
├── 0_Inbox/                # Drop new files here
├── Source/                 # Original files after ingest (immutable)
├── Knowledge/              # AI-Managed Markdown Files (Git Repo)
│   ├── 1_Projects/         # Active goals with deadlines
│   ├── 2_Areas/            # Ongoing responsibilities
│   ├── 3_Resources/        # Reference materials
│   └── 4_Archive/          # Completed projects
├── Outbox/                 # Draft actions awaiting review
└── Archive/                # Reserved for future use (unused by ingest today)
```
