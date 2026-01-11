from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from git_analysis.analysis_periods import Period
from git_analysis.analysis_reports import write_reports
from git_analysis.analysis_repo import analyze_repo
from git_analysis.identity import MeMatcher
from git_analysis.models import BootstrapConfig


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _commit(repo: Path, *, message: str, date_iso: str) -> str:
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = date_iso
    env["GIT_COMMITTER_DATE"] = date_iso
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", message], cwd=repo, env=env)
    return _run(["git", "rev-parse", "HEAD"], cwd=repo)


def _init_repo_with_two_commits(repo: Path) -> tuple[str, str]:
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)

    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    sha1 = _commit(repo, message="small", date_iso="2025-01-01T12:00:00Z")

    (repo / "a.txt").write_text("a\n" + ("x\n" * 10), encoding="utf-8")
    sha2 = _commit(repo, message="big", date_iso="2025-01-02T12:00:00Z")
    return sha1, sha2


def test_top_commits_csv_is_written_and_sorted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _sha1, sha2 = _init_repo_with_two_commits(repo)

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
    result = analyze_repo(
        repo=repo,
        key="k",
        remote_name="origin",
        remote="git@github.com:org/repo.git",
        remote_canonical="github.com/org/repo",
        duplicates=[],
        periods=[period],
        include_merges=False,
        me=MeMatcher(frozenset(), frozenset()),
        bootstrap=BootstrapConfig(changed_threshold=1_000_000, files_threshold=1_000_000, addition_ratio=1.0),
        exclude_path_prefixes=[],
        exclude_path_globs=[],
    )

    write_reports(
        report_dir=tmp_path,
        scan_root=tmp_path,
        run_type="years_2025",
        periods=[period],
        results=[result],
        selection_rows=[{"status": "included", "candidate_path": str(repo)}],
        repo_count_candidates=1,
        dedupe="remote",
        max_repos=0,
        include_merges=False,
        include_bootstraps=False,
        bootstrap_cfg=BootstrapConfig(),
        include_remote_prefixes=[],
        remote_name_priority=["origin"],
        remote_filter_mode="any",
        exclude_forks=False,
        fork_remote_names=["upstream"],
        exclude_path_prefixes=[],
        exclude_path_globs=[],
        me=MeMatcher(frozenset(), frozenset()),
        top_authors=10,
        detailed=False,
        ascii_top_n=5,
    )

    top_path = tmp_path / "csv" / "top_commits.csv"
    assert top_path.exists()
    rows = top_path.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("period,repo_key,repo_path,remote_canonical,sha,")
    assert any((f",{sha2},") in r for r in rows[1:])


def test_exclude_commits_skips_stats_and_top_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha1, sha2 = _init_repo_with_two_commits(repo)

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
    result = analyze_repo(
        repo=repo,
        key="k",
        remote_name="origin",
        remote="git@github.com:org/repo.git",
        remote_canonical="github.com/org/repo",
        duplicates=[],
        periods=[period],
        include_merges=False,
        me=MeMatcher(frozenset(), frozenset()),
        bootstrap=BootstrapConfig(changed_threshold=1_000_000, files_threshold=1_000_000, addition_ratio=1.0),
        exclude_path_prefixes=[],
        exclude_path_globs=[],
        exclude_commits={sha2},
    )

    assert result.period_stats_excl_bootstraps["2025"].commits_total == 1

    write_reports(
        report_dir=tmp_path,
        scan_root=tmp_path,
        run_type="years_2025",
        periods=[period],
        results=[result],
        selection_rows=[{"status": "included", "candidate_path": str(repo)}],
        repo_count_candidates=1,
        dedupe="remote",
        max_repos=0,
        include_merges=False,
        include_bootstraps=False,
        bootstrap_cfg=BootstrapConfig(),
        include_remote_prefixes=[],
        remote_name_priority=["origin"],
        remote_filter_mode="any",
        exclude_forks=False,
        fork_remote_names=["upstream"],
        exclude_path_prefixes=[],
        exclude_path_globs=[],
        me=MeMatcher(frozenset(), frozenset()),
        top_authors=10,
        detailed=False,
        ascii_top_n=5,
    )

    top_path = tmp_path / "csv" / "top_commits.csv"
    rows = top_path.read_text(encoding="utf-8").splitlines()
    assert any((f",{sha1},") in r for r in rows[1:])
    assert not any((f",{sha2},") in r for r in rows[1:])
