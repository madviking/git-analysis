from __future__ import annotations

import datetime as dt
from pathlib import Path

from git_analysis.analysis_periods import Period
from git_analysis.analysis_reports import write_reports
from git_analysis.identity import MeMatcher
from git_analysis.models import BootstrapConfig, RepoResult


def _empty_repo_result(*, repo_key: str = "k") -> RepoResult:
    return RepoResult(
        key=repo_key,
        path="/tmp/repo",
        remote_name="origin",
        remote="git@github.com:org/repo.git",
        remote_canonical="github.com/org/repo",
        duplicates=[],
        first_commit_iso=None,
        first_commit_author_name=None,
        first_commit_author_email=None,
        last_commit_iso=None,
        period_stats_excl_bootstraps={},
        period_stats_bootstraps={},
        weekly_by_period_excl_bootstraps={},
        weekly_by_period_bootstraps={},
        authors_by_period_excl_bootstraps={},
        authors_by_period_bootstraps={},
        languages_by_period_excl_bootstraps={},
        languages_by_period_bootstraps={},
        dirs_by_period_excl_bootstraps={},
        dirs_by_period_bootstraps={},
        me_monthly_by_period_excl_bootstraps={},
        me_monthly_by_period_bootstraps={},
        me_monthly_tech_by_period_excl_bootstraps={},
        me_monthly_tech_by_period_bootstraps={},
        excluded_by_period={},
        bootstrap_commits_by_period={},
        errors=[],
    )


def test_comparison_txt_and_markup_written(tmp_path: Path) -> None:
    p0 = Period(label="2025H1", start=dt.date(2025, 1, 1), end=dt.date(2025, 7, 1))
    p1 = Period(label="2025H2", start=dt.date(2025, 7, 1), end=dt.date(2026, 1, 1))
    write_reports(
        report_dir=tmp_path,
        scan_root=tmp_path,
        run_type="halves_2025",
        periods=[p0, p1],
        results=[_empty_repo_result()],
        selection_rows=[{"status": "included", "candidate_path": "/tmp/repo"}],
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

    assert (tmp_path / "comparison_2025H1_vs_2025H2.txt").exists()
    assert (tmp_path / "markup" / "comparison_2025H1_vs_2025H2.md").exists()
    assert (tmp_path / "comparison_2025H1_vs_2025H2.md").exists() is False
    comp_md = (tmp_path / "markup" / "comparison_2025H1_vs_2025H2.md").read_text(encoding="utf-8")
    assert comp_md.startswith("# Git comparison:")
    assert "Bootstraps (totals)" not in comp_md
    assert "Totals (including bootstraps)" not in comp_md
    assert (tmp_path / "period_in_review_2025H1_vs_2025H2.txt").exists()
    assert (tmp_path / "markup" / "period_in_review_2025H1_vs_2025H2.md").exists()
