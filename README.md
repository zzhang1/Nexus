# Nexus AI: Local-First, Privacy-Centric Knowledge Assistant

**Nexus AI** is a command-line personal assistant that turns your static files into a living, intelligent knowledge base. It operates entirely on your local machine, respecting your privacy and ownership of data.

By combining the universal file processing of **Apache Tika**, the version control of **Git**, and the reasoning power of **Large Language Models (LLMs)**, Nexus AI organizes your chaotic "My Documents" folder into a structured, chat-able Markdown library.

---

## 🚀 Core Features

*   **📥 Smart Ingestion:** Drop PDFs, Excel sheets, Images, or Word docs into your `Inbox`. Nexus extracts the text, summarizes it with AI, and files a clean Markdown version into your knowledge base.
*   **🧠 Context-Aware Chat:** Ask questions like "What was the budget for Project Alpha?" or "Who is the contact for the ACME contract?" Nexus answers based on your actual files.
*   **🗂️ PARA Organization:** Automatically suggests filing new documents into **Projects**, **Areas**, **Resources**, or **Archive** to keep your digital life MECE (Mutually Exclusive, Collectively Exhaustive).
*   **🔗 Mirror Structure:** Keeps your original source files safe in a `Source` directory while maintaining a parallel, pure-Markdown `Knowledge` directory for the AI to work with.
*   **🛡️ Git-Backed:** Every change—whether by you or the AI—is committed to a local Git repository. You have a complete, undoable history of your knowledge base.
*   **🔍 Local Intelligence:** Uses a local SQLite database to index your files and build a lightweight Knowledge Graph for instant retrieval.

---

## 🛠️ Technical Architecture

Nexus AI is built with a modular, API-first philosophy using Python 3.10+.

*   **CLI:** Built with `typer` and `rich` for a beautiful terminal experience.
*   **LLM Engine:** Uses `litellm` to connect to OpenAI, Anthropic, or local models (Ollama).
*   **Extraction:** Wraps `tika-python` (Apache Tika) for industrial-grade file parsing.
*   **Storage:**
    *   **Unstructured:** Standard Markdown files (`.md`) with YAML front-matter.
    *   **Structured:** SQLite for file maps, caching, and entity relationships.
    *   **Version Control:** `GitPython` for automated repository management.

---

## 📦 Installation

### Prerequisites
*   Python 3.10 or higher
*   Git installed and available in your terminal
*   Java Runtime Environment (required for Apache Tika)

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
    OPENAI_API_KEY=sk-...
    # or
    ANTHROPIC_API_KEY=sk-...
    ```

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

### 3. Chat with Your Data
Now, simply ask a question:

```bash
nexus chat "Summarize the key action items from the meeting notes I just added."
```

---

## 📂 Directory Structure (User Data)

When you run `init`, Nexus creates this structure on your computer:

```text
/Your_Root_Folder/
├── .assistant/             # Database, Config, Logs (Hidden)
├── 0_Inbox/                # Drop new files here
├── Source/                 # Your ORIGINAL files (Immutable Archive)
├── Knowledge/              # AI-Managed Markdown Files (Git Repo)
│   ├── 1_Projects/         # Active goals with deadlines
│   ├── 2_Areas/            # Ongoing responsibilities
│   ├── 3_Resources/        # Reference materials
│   └── 4_Archive/          # Completed projects
└── Archive/                # Processed source files (Mirrors Knowledge structure)
```
