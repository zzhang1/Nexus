# Nexus AI: Local-First, Privacy-Centric Knowledge Assistant

**Nexus AI** is a command-line personal assistant that turns your static files into a living, intelligent knowledge base. It operates entirely on your local machine, respecting your privacy and ownership of data.

By combining local document processing, Git-based versioning, and Large Language Models (LLMs), Nexus AI organizes your chaotic "My Documents" folder into a structured, chat-able Markdown library.

See `REQUIREMENTS.md` for the MVP scope and acceptance checks.

---

## 🚀 Core Features

*   **📥 Smart Ingestion:** Drop PDFs, spreadsheets, images, or docs into `0_Inbox/`. Nexus extracts text, converts it to clean Markdown, and files it into your knowledge base.
*   **🧠 Context-Aware Chat:** Ask questions like "What was the budget for Project Alpha?" or "Who is the contact for the ACME contract?" Nexus answers based on your actual files.
*   **🗂️ PARA Organization (Flexible):** Uses PARA at the top level, with user-defined subfolders (e.g., `Taxes/`, `People/`, `Real_Estate/`, `Wealth_Management/`) and guided reorganizations when asked.
*   **🔗 Mirror Structure:** Keeps your original source files safe in a `Source` directory while maintaining a parallel, pure-Markdown `Knowledge` directory for the AI to work with.
*   **✅ Tasks From Anywhere:** Finds tasks, deadlines, and events embedded in your notes and uses them for planning.
*   **📤 Outbox for Deliverables:** Stages ready-to-use artifacts (email drafts, travel plans, call scripts, calendar invites) in `Outbox/` for review.
*   **🛡️ Git-Backed Knowledge:** Changes to `Knowledge/` (by you or the AI) are committed to a local Git repository for a complete, undoable history.
*   **🔍 GraphRAG Index:** Uses a local SQLite + vector index (“map”) derived from your Markdown (“territory”) for fast retrieval.
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
  model: anthropic/claude-3.5-sonnet
  # base_url: http://localhost:11434   # required for ollama if non-default
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

### 2. Ingest Documents
Drag some files (PDFs, receipts, notes) into the `0_Inbox` folder created inside your root directory. Then, tell Nexus to process them:

```bash
nexus ingest
```
*Nexus will read the files, convert them to Markdown, file them into `Knowledge/`, archive the originals, and commit the changes to Git.*

If you manually edit Markdown files in `Knowledge/`, re-index with:
```bash
nexus sync
```

### 3. Chat with Your Data
Now, simply ask a question:

```bash
nexus chat "Summarize the key action items from the meeting notes I just added."
```
You can also ask time-based questions:
```bash
nexus chat "What should I do today?"
```

Or use the planning views directly:
```bash
nexus today
nexus week
nexus month
```

### 4. Track Tasks in Notes
Add tasks anywhere in `Knowledge/` using Markdown checkboxes with optional inline metadata:
```md
- [ ] File taxes due:2026-04-15 p:P1
- [ ] Repaint door p:P2 effort:2h
```
Then run `nexus sync` and view them with `nexus tasks`.

---

## 📂 Directory Structure (User Data)

When you run `init`, Nexus creates this structure on your computer:

```text
/Your_Root_Folder/
├── .assistant/             # Database, Config, Preferences, Logs (Hidden)
├── 0_Inbox/                # Drop new files here
├── Source/                 # Your ORIGINAL files (Immutable Archive)
├── Knowledge/              # AI-Managed Markdown Files (Git Repo)
│   ├── 1_Projects/         # Active goals with deadlines
│   ├── 2_Areas/            # Ongoing responsibilities
│   ├── 3_Resources/        # Reference materials
│   └── 4_Archive/          # Completed projects
├── Outbox/                 # Draft actions awaiting review
└── Archive/                # Processed source files (Mirrors Knowledge structure)
```
