from __future__ import annotations

from git_analysis.analysis_aggregate import repo_period_stats
from git_analysis.models import RepoResult, RepoYearStats


def test_repo_period_stats_include_bootstraps() -> None:
    period = "2025"
    r = RepoResult(
        key="k",
        path="/tmp/repo",
        remote_name="origin",
        remote="git@example.com:org/repo.git",
        remote_canonical="git@example.com:org/repo.git",
        duplicates=[],
        first_commit_iso=None,
        first_commit_author_name=None,
        first_commit_author_email=None,
        last_commit_iso=None,
        period_stats_excl_bootstraps={period: RepoYearStats(commits_total=1, insertions_total=2, deletions_total=3, commits_me=0, insertions_me=0, deletions_me=0)},
        period_stats_bootstraps={period: RepoYearStats(commits_total=4, insertions_total=5, deletions_total=6, commits_me=0, insertions_me=0, deletions_me=0)},
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

    excl = repo_period_stats(r, period, include_bootstraps=False)
    assert excl.commits_total == 1
    assert excl.changed_total == 5

    incl = repo_period_stats(r, period, include_bootstraps=True)
    assert incl.commits_total == 5
    assert incl.changed_total == (2 + 3) + (5 + 6)
