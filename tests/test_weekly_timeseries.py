from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from git_analysis.analysis_periods import Period
from git_analysis.analysis_repo import analyze_repo
from git_analysis.identity import MeMatcher
from git_analysis.models import BootstrapConfig


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return proc.stdout


def _commit_file(*, repo: Path, filename: str, content: str, author_date: str) -> None:
    p = repo / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _run(["git", "add", filename], cwd=repo)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = author_date
    env["GIT_COMMITTER_DATE"] = author_date
    _run(["git", "commit", "-m", f"update {filename}"], cwd=repo, env=env)


def test_weekly_bucketing_uses_author_time_converted_to_utc(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)

    # Sunday in -0800 => Monday UTC, should bucket to 2025-01-06 week.
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-05T23:30:00-0800")
    # Monday in +0200 => Sunday UTC, should bucket to 2024-12-30 week.
    _commit_file(repo=repo, filename="b.txt", content="b\n", author_date="2025-01-06T00:30:00+0200")

    period = Period(label="p", start=dt.date(2024, 12, 29), end=dt.date(2025, 1, 12))
    r = analyze_repo(
        repo=repo,
        key="k",
        remote_name="",
        remote="",
        remote_canonical="",
        duplicates=[],
        periods=[period],
        include_merges=True,
        me=MeMatcher(frozenset(), frozenset()),
        bootstrap=BootstrapConfig(changed_threshold=10_000, files_threshold=10_000, addition_ratio=1.0),
        exclude_path_prefixes=[],
        exclude_path_globs=[],
    )

    weekly = r.weekly_by_period_excl_bootstraps["p"]
    assert weekly["2024-12-30T00:00:00Z"]["commits"] == 1
    assert weekly["2025-01-06T00:00:00Z"]["commits"] == 1

