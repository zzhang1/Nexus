# Repository Guidelines

## Project Structure & Module Organization
- Current repo is documentation-focused: `README.md` (overview/usage) and `Design.md` (architecture/spec).
- The implementation is planned to live under `src/nexus_ai/` with a CLI entrypoint (see `Design.md`).
- User data created by the CLI is outside the repo root. Expected layout after `nexus init`:
  - `.assistant/` (db/config/logs), `0_Inbox/`, `Source/`, `Knowledge/`, `Archive/`.

## Build, Test, and Development Commands
- `python -m venv venv` and `source venv/bin/activate` (Windows: `venv\\Scripts\\activate`) to set up a virtualenv.
- `pip install .` to install the package in editable/packaged form (as described in `README.md`).
- `nexus init --root ~/Documents/MyNexusKnowledgeBase` to create the workspace folders.
- `nexus ingest` to process files from `0_Inbox` into `Knowledge/`.
- `nexus chat "<question>"` to query the knowledge base.

## Coding Style & Naming Conventions
- Python code should follow standard PEP 8 conventions: 4-space indentation, `snake_case` for functions/modules, `PascalCase` for classes.
- Keep CLI commands and subcommands lowercase (e.g., `nexus ingest`, `nexus chat`).
- Markdown docs should use short sections, bulleted lists, and code fences for commands.

## Testing Guidelines
- No automated test suite is defined yet in this repo.
- If you add tests, place them under `tests/` and document how to run them in `README.md`.

## Commit & Pull Request Guidelines
- Commit messages in history are short, imperative, and sentence-cased (e.g., “Revise README with comprehensive project details”).
- PRs should include: a concise summary, any user-facing changes, and how you validated the change (commands run or “not run”).

## Agent-Specific Instructions
- **Graph consistency:** when changing Markdown content that represents entities (people/projects), ensure the graph/index layer is updated accordingly.
- **Source of truth:** Markdown in `Knowledge/` is canonical; vector/graph indexes are derived and should not override Markdown content.
