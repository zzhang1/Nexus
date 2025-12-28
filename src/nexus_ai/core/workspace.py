from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from git import InvalidGitRepositoryError, Repo

from nexus_ai.core.config import default_config_dict, default_preferences_dict, save_yaml
from nexus_ai.core.db import NexusDb


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path

    @property
    def assistant_dir(self) -> Path:
        return self.root / ".assistant"

    @property
    def config_yaml(self) -> Path:
        return self.assistant_dir / "config.yaml"

    @property
    def preferences_yaml(self) -> Path:
        return self.assistant_dir / "preferences.yaml"

    @property
    def db_path(self) -> Path:
        return self.assistant_dir / "nexus.db"

    @property
    def vector_store_dir(self) -> Path:
        return self.assistant_dir / "vector_store"

    @property
    def logs_dir(self) -> Path:
        return self.assistant_dir / "logs"

    @property
    def inbox_dir(self) -> Path:
        return self.root / "0_Inbox"

    @property
    def source_dir(self) -> Path:
        return self.root / "Source"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "Knowledge"

    @property
    def outbox_dir(self) -> Path:
        return self.root / "Outbox"

    @property
    def archive_dir(self) -> Path:
        return self.root / "Archive"


class WorkspaceError(RuntimeError):
    pass


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.paths = WorkspacePaths(self.root)

    @staticmethod
    def from_optional_root(root: Path | None) -> "Workspace":
        if root is not None:
            return Workspace(root)
        return Workspace.discover(Path.cwd())

    @staticmethod
    def discover(start: Path) -> "Workspace":
        current = start.expanduser().resolve()
        for parent in [current, *current.parents]:
            if (parent / ".assistant").is_dir() and (parent / "Knowledge").is_dir():
                return Workspace(parent)
        raise WorkspaceError(
            "Could not find a Nexus workspace. Run `nexus init --root <path>` or pass --root."
        )

    def init_workspace(self) -> list[str]:
        created: list[str] = []

        dirs = [
            self.paths.assistant_dir,
            self.paths.logs_dir,
            self.paths.vector_store_dir,
            self.paths.inbox_dir,
            self.paths.source_dir,
            self.paths.knowledge_dir,
            self.paths.outbox_dir,
            self.paths.archive_dir,
            self.paths.knowledge_dir / "1_Projects",
            self.paths.knowledge_dir / "2_Areas",
            self.paths.knowledge_dir / "3_Resources",
            self.paths.knowledge_dir / "4_Archive",
        ]

        for d in dirs:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))

        if not self.paths.config_yaml.exists():
            save_yaml(self.paths.config_yaml, default_config_dict())
            created.append(str(self.paths.config_yaml))

        if not self.paths.preferences_yaml.exists():
            save_yaml(self.paths.preferences_yaml, default_preferences_dict())
            created.append(str(self.paths.preferences_yaml))

        db = NexusDb(self.paths.db_path)
        db.init_schema()

        self._init_knowledge_git()
        return created

    def _init_knowledge_git(self) -> None:
        knowledge = self.paths.knowledge_dir
        try:
            Repo(knowledge)
        except InvalidGitRepositoryError:
            repo = Repo.init(knowledge)
            (knowledge / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
            repo.index.add([".gitignore"])
            repo.index.commit("Initialize Knowledge repo")

    def iter_knowledge_markdown_files(self) -> Iterable[Path]:
        for path in self.paths.knowledge_dir.rglob("*.md"):
            if path.is_file() and "/.git/" not in str(path):
                yield path

