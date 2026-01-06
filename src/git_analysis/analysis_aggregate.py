from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .analysis_periods import Period
from .identity import MeMatcher
from .models import AuthorStats, RepoResult, RepoYearStats


def add_repo_year_stats(dst: RepoYearStats, src: RepoYearStats) -> None:
    dst.commits_total += src.commits_total
    dst.insertions_total += src.insertions_total
    dst.deletions_total += src.deletions_total
    dst.commits_me += src.commits_me
    dst.insertions_me += src.insertions_me
    dst.deletions_me += src.deletions_me


def repo_period_stats(r: RepoResult, period_label: str, include_bootstraps: bool) -> RepoYearStats:
    out = RepoYearStats()
    add_repo_year_stats(out, r.period_stats_excl_bootstraps.get(period_label, RepoYearStats()))
    if include_bootstraps:
        add_repo_year_stats(out, r.period_stats_bootstraps.get(period_label, RepoYearStats()))
    return out


def merge_breakdown(dst: dict[str, dict[str, int]], src: dict[str, dict[str, int]]) -> None:
    for key, st in src.items():
        cur = dst.get(key)
        if cur is None:
            dst[key] = {k: int(v) for k, v in st.items()}
            continue
        for k, v in st.items():
            cur[k] = int(cur.get(k, 0)) + int(v)


def merge_me_monthly(dst: dict[str, dict[str, int]], src: dict[str, dict[str, int]]) -> None:
    for month, st in src.items():
        cur = dst.get(month)
        if cur is None:
            dst[month] = {k: int(v) for k, v in st.items()}
            continue
        for k, v in st.items():
            cur[k] = int(cur.get(k, 0)) + int(v)


def merge_weekly(dst: dict[str, dict[str, int]], src: dict[str, dict[str, int]]) -> None:
    for week_start, st in src.items():
        cur = dst.get(week_start)
        if cur is None:
            dst[week_start] = {k: int(v) for k, v in st.items()}
            continue
        for k, v in st.items():
            cur[k] = int(cur.get(k, 0)) + int(v)


def aggregate_weekly(
    repos: list[RepoResult],
    period_label: str,
    *,
    include_bootstraps: bool,
    bootstraps_only: bool = False,
) -> dict[str, dict[str, int]]:
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    for r in repos:
        if bootstraps_only:
            merge_weekly(agg, r.weekly_by_period_bootstraps.get(period_label, {}))
        else:
            merge_weekly(agg, r.weekly_by_period_excl_bootstraps.get(period_label, {}))
            if include_bootstraps:
                merge_weekly(agg, r.weekly_by_period_bootstraps.get(period_label, {}))

    out: dict[str, dict[str, int]] = {}
    for week_start, st in agg.items():
        ins = int(st.get("insertions", 0))
        dele = int(st.get("deletions", 0))
        out[week_start] = {
            "commits": int(st.get("commits", 0)),
            "insertions": ins,
            "deletions": dele,
            "changed": ins + dele,
        }
    return out


def merge_me_monthly_tech(dst: dict[str, dict[str, dict[str, int]]], src: dict[str, dict[str, dict[str, int]]]) -> None:
    for month, techs in src.items():
        cur_month = dst.get(month)
        if cur_month is None:
            dst[month] = {tech: {k: int(v) for k, v in st.items()} for tech, st in techs.items()}
            continue
        for tech, st in techs.items():
            cur_tech = cur_month.get(tech)
            if cur_tech is None:
                cur_month[tech] = {k: int(v) for k, v in st.items()}
                continue
            for k, v in st.items():
                cur_tech[k] = int(cur_tech.get(k, 0)) + int(v)


def aggregate_me_monthly(
    repos: list[RepoResult],
    period_label: str,
    *,
    include_bootstraps: bool,
    bootstraps_only: bool = False,
) -> dict[str, dict[str, int]]:
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    for r in repos:
        if bootstraps_only:
            merge_me_monthly(agg, r.me_monthly_by_period_bootstraps.get(period_label, {}))
        else:
            merge_me_monthly(agg, r.me_monthly_by_period_excl_bootstraps.get(period_label, {}))
            if include_bootstraps:
                merge_me_monthly(agg, r.me_monthly_by_period_bootstraps.get(period_label, {}))

    out: dict[str, dict[str, int]] = {}
    for month, st in agg.items():
        ins = int(st.get("insertions", 0))
        dele = int(st.get("deletions", 0))
        out[month] = {
            "commits": int(st.get("commits", 0)),
            "insertions": ins,
            "deletions": dele,
            "changed": ins + dele,
        }
    return out


def aggregate_me_monthly_tech(
    repos: list[RepoResult],
    period_label: str,
    *,
    include_bootstraps: bool,
    bootstraps_only: bool = False,
) -> dict[str, dict[str, dict[str, int]]]:
    agg: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    )
    for r in repos:
        if bootstraps_only:
            merge_me_monthly_tech(agg, r.me_monthly_tech_by_period_bootstraps.get(period_label, {}))
        else:
            merge_me_monthly_tech(agg, r.me_monthly_tech_by_period_excl_bootstraps.get(period_label, {}))
            if include_bootstraps:
                merge_me_monthly_tech(agg, r.me_monthly_tech_by_period_bootstraps.get(period_label, {}))

    out: dict[str, dict[str, dict[str, int]]] = {}
    for month, techs in agg.items():
        out[month] = {}
        for tech, st in techs.items():
            ins = int(st.get("insertions", 0))
            dele = int(st.get("deletions", 0))
            out[month][tech] = {
                "commits": int(st.get("commits", 0)),
                "insertions": ins,
                "deletions": dele,
                "changed": ins + dele,
            }
    return out


def merge_author_stats(dst: dict[str, AuthorStats], src: dict[str, AuthorStats]) -> None:
    for email_key, st in src.items():
        cur = dst.get(email_key)
        if cur is None:
            dst[email_key] = AuthorStats(
                name=st.name,
                email=st.email,
                commits=st.commits,
                insertions=st.insertions,
                deletions=st.deletions,
            )
            continue
        if not cur.name and st.name:
            cur.name = st.name
        if not cur.email and st.email:
            cur.email = st.email
        cur.commits += st.commits
        cur.insertions += st.insertions
        cur.deletions += st.deletions


def aggregate_authors(
    repos: list[RepoResult],
    period_label: str,
    *,
    include_bootstraps: bool,
    bootstraps_only: bool = False,
) -> dict[str, AuthorStats]:
    agg: dict[str, AuthorStats] = {}
    for r in repos:
        if bootstraps_only:
            merge_author_stats(agg, r.authors_by_period_bootstraps.get(period_label, {}))
        else:
            merge_author_stats(agg, r.authors_by_period_excl_bootstraps.get(period_label, {}))
            if include_bootstraps:
                merge_author_stats(agg, r.authors_by_period_bootstraps.get(period_label, {}))
    return agg


def aggregate_period(
    repos: list[RepoResult],
    period: Period,
    me: MeMatcher,
    *,
    include_bootstraps: bool,
    bootstraps_only: bool = False,
) -> dict:
    total = RepoYearStats()
    repos_with_commits = 0
    repos_with_my_commits = 0
    new_projects_by_history = 0
    new_projects_started_by_me = 0

    for r in repos:
        if bootstraps_only:
            ys = r.period_stats_bootstraps.get(period.label, RepoYearStats())
        else:
            ys = repo_period_stats(r, period.label, include_bootstraps=include_bootstraps)
        if ys.commits_total > 0:
            repos_with_commits += 1
        if ys.commits_me > 0:
            repos_with_my_commits += 1

        if r.first_commit_iso:
            try:
                first_date = dt.date.fromisoformat(r.first_commit_iso[:10])
            except ValueError:
                first_date = None
            if first_date is not None and (period.start <= first_date < period.end):
                new_projects_by_history += 1
                if r.first_commit_author_name and r.first_commit_author_email:
                    if me.matches(r.first_commit_author_name, r.first_commit_author_email):
                        new_projects_started_by_me += 1

        total.commits_total += ys.commits_total
        total.commits_me += ys.commits_me
        total.insertions_total += ys.insertions_total
        total.deletions_total += ys.deletions_total
        total.insertions_me += ys.insertions_me
        total.deletions_me += ys.deletions_me

    out: dict[str, object] = {
        "period": period.label,
        "start": period.start_iso,
        "end": period.end_iso,
        "repos_total": len(repos),
        "repos_with_commits": repos_with_commits,
        "repos_with_my_commits": repos_with_my_commits,
        "new_projects_by_history": new_projects_by_history,
        "new_projects_started_by_me": new_projects_started_by_me,
        "commits_total": total.commits_total,
        "commits_me": total.commits_me,
        "commits_others": total.commits_total - total.commits_me,
        "insertions_total": total.insertions_total,
        "deletions_total": total.deletions_total,
        "changed_total": total.changed_total,
        "insertions_me": total.insertions_me,
        "deletions_me": total.deletions_me,
        "changed_me": total.changed_me,
        "insertions_others": total.insertions_total - total.insertions_me,
        "deletions_others": total.deletions_total - total.deletions_me,
        "changed_others": total.changed_total - total.changed_me,
    }
    if period.label.isdigit() and len(period.label) == 4:
        out["year"] = int(period.label)
    return out


def aggregate_languages(
    repos: list[RepoResult],
    period_label: str,
    *,
    include_bootstraps: bool,
    bootstraps_only: bool = False,
) -> dict[str, dict[str, int]]:
    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0}
    )
    for r in repos:
        if bootstraps_only:
            merge_breakdown(agg, r.languages_by_period_bootstraps.get(period_label, {}))
        else:
            merge_breakdown(agg, r.languages_by_period_excl_bootstraps.get(period_label, {}))
            if include_bootstraps:
                merge_breakdown(agg, r.languages_by_period_bootstraps.get(period_label, {}))

    # Convert to plain dicts with derived fields.
    out: dict[str, dict[str, int]] = {}
    for lang, st in agg.items():
        ins = st["insertions"]
        dele = st["deletions"]
        ins_me = st["insertions_me"]
        dele_me = st["deletions_me"]
        out[lang] = {
            "insertions": ins,
            "deletions": dele,
            "changed": ins + dele,
            "insertions_me": ins_me,
            "deletions_me": dele_me,
            "changed_me": ins_me + dele_me,
            "insertions_others": ins - ins_me,
            "deletions_others": dele - dele_me,
            "changed_others": (ins + dele) - (ins_me + dele_me),
        }
    return out


def aggregate_dirs(
    repos: list[RepoResult],
    period_label: str,
    *,
    include_bootstraps: bool,
    bootstraps_only: bool = False,
) -> dict[str, dict[str, int]]:
    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0}
    )
    for r in repos:
        if bootstraps_only:
            merge_breakdown(agg, r.dirs_by_period_bootstraps.get(period_label, {}))
        else:
            merge_breakdown(agg, r.dirs_by_period_excl_bootstraps.get(period_label, {}))
            if include_bootstraps:
                merge_breakdown(agg, r.dirs_by_period_bootstraps.get(period_label, {}))

    out: dict[str, dict[str, int]] = {}
    for d, st in agg.items():
        ins = st["insertions"]
        dele = st["deletions"]
        ins_me = st["insertions_me"]
        dele_me = st["deletions_me"]
        out[d] = {
            "insertions": ins,
            "deletions": dele,
            "changed": ins + dele,
            "insertions_me": ins_me,
            "deletions_me": dele_me,
            "changed_me": ins_me + dele_me,
            "insertions_others": ins - ins_me,
            "deletions_others": dele - dele_me,
            "changed_others": (ins + dele) - (ins_me + dele_me),
        }
    return out


def aggregate_excluded(repos: list[RepoResult], period_label: str) -> dict[str, int]:
    agg: dict[str, int] = defaultdict(int)
    for r in repos:
        ex = r.excluded_by_period.get(period_label, {})
        for k, v in ex.items():
            agg[k] += int(v)
    return dict(agg)
