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


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)


def test_bootstrap_detection_flags_extreme_churn_even_with_few_files(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)

    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "seed.txt"], cwd=repo)
    _commit_all(repo=repo, msg="seed", author_date="2024-12-31T12:00:00Z")

    big_content = "".join(f"line {i}\n" for i in range(100))
    (repo / "big.txt").write_text(big_content, encoding="utf-8")
    _run(["git", "add", "big.txt"], cwd=repo)
    _commit_all(repo=repo, msg="big data", author_date="2025-02-10T12:00:00Z")

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
    stats_excl, stats_boot, *_rest, boot_commits, _top_commits, errors = parse_numstat_stream(
        repo=repo,
        period=period,
        include_merges=False,
        me=MeMatcher(frozenset(), frozenset()),
        bootstrap=BootstrapConfig(changed_threshold=10, files_threshold=3, addition_ratio=0.90),
        exclude_path_prefixes=[],
        exclude_path_globs=[],
    )

    assert errors == []
    assert stats_excl.commits_total == 0
    assert stats_boot.commits_total == 1
    assert len(boot_commits) == 1
    assert boot_commits[0]["insertions"] == 100
    assert boot_commits[0]["deletions"] == 0
    assert boot_commits[0]["files_touched"] == 1


def test_bootstrap_detection_flags_extreme_file_sweep_even_when_balanced(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)

    for idx in range(20):
        (repo / f"f{idx}.txt").write_text("a\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo)
    _commit_all(repo=repo, msg="base", author_date="2024-12-31T12:00:00Z")

    for idx in range(20):
        (repo / f"f{idx}.txt").write_text("b\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo)
    _commit_all(repo=repo, msg="sweep rename", author_date="2025-02-10T12:00:00Z")

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
    stats_excl, stats_boot, *_rest, boot_commits, _top_commits, errors = parse_numstat_stream(
        repo=repo,
        period=period,
        include_merges=False,
        me=MeMatcher(frozenset(), frozenset()),
        bootstrap=BootstrapConfig(changed_threshold=10, files_threshold=3, addition_ratio=0.90),
        exclude_path_prefixes=[],
        exclude_path_globs=[],
    )

    assert errors == []
    assert stats_excl.commits_total == 0
    assert stats_boot.commits_total == 1
    assert len(boot_commits) == 1
    assert boot_commits[0]["insertions"] == 20
    assert boot_commits[0]["deletions"] == 20
    assert boot_commits[0]["files_touched"] == 20
