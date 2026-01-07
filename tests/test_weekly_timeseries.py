from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from git_analysis.analysis_periods import Period
from git_analysis.analysis_repo import analyze_repo
from git_analysis.analysis_reports import write_reports
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


def test_weekly_timeseries_includes_technologies_per_week(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)

    # Two commits in the same week with different file types.
    _commit_file(repo=repo, filename="a.js", content="console.log('x')\n", author_date="2025-01-02T12:00:00Z")
    _commit_file(repo=repo, filename="b.py", content="print('x')\n", author_date="2025-01-03T12:00:00Z")

    period = Period(label="2025", start=dt.date(2025, 1, 1), end=dt.date(2026, 1, 1))
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

    write_reports(
        report_dir=tmp_path,
        scan_root=tmp_path,
        run_type="years_2025",
        periods=[period],
        results=[r],
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

    weekly_path = tmp_path / "timeseries" / "year_2025_weekly.json"
    obj = json.loads(weekly_path.read_text(encoding="utf-8"))
    rows = obj["series"]["excl_bootstraps"]
    assert rows
    techs = rows[0]["technologies"]
    names = {t["technology"] for t in techs}
    assert "JavaScript" in names
    assert "Python" in names
