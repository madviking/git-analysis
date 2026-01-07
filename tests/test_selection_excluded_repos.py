from __future__ import annotations

import os
import subprocess
from pathlib import Path

from git_analysis.analysis_selection import discover_and_select_repos


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return proc.stdout


def _init_repo(*, repo: Path, remote: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", remote], cwd=repo)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _run(["git", "add", "a.txt"], cwd=repo)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "2025-01-01T00:00:00Z"
    env["GIT_COMMITTER_DATE"] = "2025-01-01T00:00:00Z"
    _run(["git", "commit", "-m", "init"], cwd=repo, env=env)


def test_discover_and_select_repos_respects_excluded_repos(tmp_path: Path) -> None:
    root = tmp_path / "scan"
    included = root / "keepme"
    excluded = root / "skipme"

    _init_repo(repo=included, remote="git@github.com:org/keep.git")
    _init_repo(repo=excluded, remote="git@github.com:org/skip.git")

    candidates, repos_to_analyze, selection_rows = discover_and_select_repos(
        root,
        exclude_dirnames={".git"},
        include_remote_prefixes=[],
        remote_name_priority=["origin"],
        remote_filter_mode="any",
        exclude_forks=False,
        fork_remote_names=["upstream"],
        excluded_repos=["**/skipme"],
        dedupe="path",
    )

    assert len(candidates) == 2
    analyzed_paths = {Path(p).name for _, p, *_rest in repos_to_analyze}
    assert analyzed_paths == {"keepme"}

    skipped = [r for r in selection_rows if r.get("status") == "skipped" and r.get("reason") == "excluded_repo"]
    assert len(skipped) == 1

