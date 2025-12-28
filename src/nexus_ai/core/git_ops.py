from __future__ import annotations

from pathlib import Path

from git import Repo


def commit_all(repo_dir: Path, message: str) -> str | None:
    repo = Repo(repo_dir)
    repo.git.add(A=True)
    if not repo.is_dirty(untracked_files=True):
        return None
    commit = repo.index.commit(message)
    return commit.hexsha

