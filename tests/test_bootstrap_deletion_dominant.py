from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from git_analysis.analysis_periods import Period
from git_analysis.analysis_repo import parse_numstat_stream
from git_analysis.identity import MeMatcher
from git_analysis.models import BootstrapConfig


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return proc.stdout


def _commit_all(*, repo: Path, msg: str, author_date: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = author_date
    env["GIT_COMMITTER_DATE"] = author_date
    _run(["git", "commit", "-m", msg], cwd=repo, env=env)


def test_bootstrap_detection_flags_deletion_dominant_commits(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)

    # Build up 3 small files over multiple small commits (each commit below bootstrap threshold).
    files = ["a.html", "b.html", "c.html"]
    for i in range(5):
        for fn in files:
            p = repo / fn
            p.write_text((p.read_text(encoding="utf-8") if p.exists() else "") + f"line {i}\n", encoding="utf-8")
        _run(["git", "add", "."], cwd=repo)
        _commit_all(repo=repo, msg=f"append lines {i}", author_date=f"2025-02-{i+1:02d}T12:00:00Z")

    # One large deletion-dominant commit (many deletions, few/no insertions).
    _run(["git", "rm", *files], cwd=repo)
    _commit_all(repo=repo, msg="remove generated html", author_date="2025-02-10T12:00:00Z")

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
    stats_excl, stats_boot, *_rest, boot_commits, errors = parse_numstat_stream(
        repo=repo,
        period=period,
        include_merges=False,
        me=MeMatcher(frozenset(), frozenset()),
        bootstrap=BootstrapConfig(changed_threshold=10, files_threshold=3, addition_ratio=0.90),
        exclude_path_prefixes=[],
        exclude_path_globs=[],
    )

    assert errors == []
    assert stats_excl.commits_total == 5
    assert stats_excl.insertions_total == 15
    assert stats_excl.deletions_total == 0

    assert stats_boot.commits_total == 1
    assert stats_boot.insertions_total == 0
    assert stats_boot.deletions_total == 15

    assert len(boot_commits) == 1
    assert boot_commits[0]["insertions"] == 0
    assert boot_commits[0]["deletions"] == 15
    assert boot_commits[0]["files_touched"] == 3
