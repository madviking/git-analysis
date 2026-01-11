from __future__ import annotations

import datetime as dt
from pathlib import Path

from .analysis_aggregate import (
    aggregate_authors,
    aggregate_dirs,
    aggregate_excluded,
    aggregate_languages,
    aggregate_me_monthly,
    aggregate_me_monthly_tech,
    aggregate_period,
    aggregate_weekly,
    aggregate_weekly_tech,
)
from .analysis_periods import Period, month_labels_for_period
from .analysis_render import render_comparison_txt_from_md, render_year_in_review, render_yoy_year_in_review, write_comparison_md
from .analysis_write import (
    ensure_dir,
    write_authors_csv,
    write_bootstrap_commits_csv,
    write_dirs_csv,
    write_json,
    write_languages_csv,
    write_repo_activity_csv,
    write_repo_selection_csv,
    write_repo_selection_summary,
    write_repos_csv,
    write_top_commits_csv,
)
from .identity import MeMatcher
from .models import AuthorStats, BootstrapConfig, RepoResult


def write_reports(
    *,
    report_dir: Path,
    scan_root: Path,
    run_type: str,
    periods: list[Period],
    results: list[RepoResult],
    selection_rows: list[dict[str, str]],
    repo_count_candidates: int,
    dedupe: str,
    max_repos: int,
    include_merges: bool,
    include_bootstraps: bool,
    bootstrap_cfg: BootstrapConfig,
    include_remote_prefixes: list[str],
    remote_name_priority: list[str],
    remote_filter_mode: str,
    exclude_forks: bool,
    fork_remote_names: list[str],
    exclude_path_prefixes: list[str],
    exclude_path_globs: list[str],
    me: MeMatcher,
    top_authors: int,
    detailed: bool,
    ascii_top_n: int = 10,
) -> None:
    generated_at = dt.datetime.now(tz=dt.timezone.utc).isoformat()

    csv_dir = report_dir / "csv"
    json_dir = report_dir / "json"
    timeseries_dir = report_dir / "timeseries"
    debug_dir = report_dir / "debug"
    markup_dir = report_dir / "markup"
    ensure_dir(csv_dir)
    ensure_dir(json_dir)
    ensure_dir(timeseries_dir)
    ensure_dir(debug_dir)
    ensure_dir(markup_dir)

    def review_prefix_for_label(label: str) -> str:
        s = str(label or "").strip()
        return "year_in_review" if s.isdigit() and len(s) == 4 else "period_in_review"

    def review_prefix_for_compare(a: str, b: str) -> str:
        return "year_in_review" if review_prefix_for_label(a) == "year_in_review" and review_prefix_for_label(b) == "year_in_review" else "period_in_review"

    def write_txt_and_markup(*, txt_path: Path, text: str, write_markup: bool = True) -> None:
        txt_path.write_text(text, encoding="utf-8")
        if write_markup:
            md_path = (
                markup_dir / (txt_path.name[:-4] + ".md")
                if txt_path.name.endswith(".txt")
                else markup_dir / (txt_path.name + ".md")
            )
            md_path.write_text(f"```text\n{text.rstrip()}\n```\n", encoding="utf-8")

    write_repo_selection_csv(debug_dir / "repo_selection.csv", selection_rows)
    write_repo_selection_summary(debug_dir / "repo_selection_summary.json", selection_rows)

    period_aggs_excl: dict[str, dict] = {}
    period_aggs_boot: dict[str, dict] = {}
    period_aggs_incl: dict[str, dict] = {}
    period_langs_excl: dict[str, dict[str, dict[str, int]]] = {}
    period_langs_boot: dict[str, dict[str, dict[str, int]]] = {}
    period_langs_incl: dict[str, dict[str, dict[str, int]]] = {}
    period_dirs_excl: dict[str, dict[str, dict[str, int]]] = {}
    period_dirs_boot: dict[str, dict[str, dict[str, int]]] = {}
    period_dirs_incl: dict[str, dict[str, dict[str, int]]] = {}
    period_authors_excl: dict[str, dict[str, AuthorStats]] = {}
    period_authors_boot: dict[str, dict[str, AuthorStats]] = {}
    period_authors_incl: dict[str, dict[str, AuthorStats]] = {}
    detailed_periods: dict[str, dict[str, object]] = {}

    for period in periods:
        label = period.label
        agg_excl = aggregate_period(results, period, me, include_bootstraps=False)
        agg_boot = aggregate_period(results, period, me, include_bootstraps=False, bootstraps_only=True)
        agg_incl = aggregate_period(results, period, me, include_bootstraps=True)

        authors_excl = aggregate_authors(results, label, include_bootstraps=False)
        authors_boot = aggregate_authors(results, label, include_bootstraps=False, bootstraps_only=True)
        authors_incl = aggregate_authors(results, label, include_bootstraps=True)

        languages_excl = aggregate_languages(results, label, include_bootstraps=False)
        languages_boot = aggregate_languages(results, label, include_bootstraps=False, bootstraps_only=True)
        languages_incl = aggregate_languages(results, label, include_bootstraps=True)

        dirs_excl = aggregate_dirs(results, label, include_bootstraps=False)
        dirs_boot = aggregate_dirs(results, label, include_bootstraps=False, bootstraps_only=True)
        dirs_incl = aggregate_dirs(results, label, include_bootstraps=True)

        period_aggs_excl[label] = agg_excl
        period_aggs_boot[label] = agg_boot
        period_aggs_incl[label] = agg_incl
        period_langs_excl[label] = languages_excl
        period_langs_boot[label] = languages_boot
        period_langs_incl[label] = languages_incl
        period_dirs_excl[label] = dirs_excl
        period_dirs_boot[label] = dirs_boot
        period_dirs_incl[label] = dirs_incl
        period_authors_excl[label] = authors_excl
        period_authors_boot[label] = authors_boot
        period_authors_incl[label] = authors_incl

        agg = agg_incl if include_bootstraps else agg_excl
        authors_agg = authors_incl if include_bootstraps else authors_excl
        languages_agg = languages_incl if include_bootstraps else languages_excl
        dirs_agg = dirs_incl if include_bootstraps else dirs_excl
        excluded_agg = aggregate_excluded(results, label)

        top_authors_rows = sorted(authors_agg.values(), key=lambda s: (-s.commits, -s.changed, s.email.lower()))[:top_authors]
        top_dirs = dict(sorted(dirs_agg.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))[:50])
        summary = {
            "generated_at": generated_at,
            "root": str(scan_root),
            "period": label,
            "start": period.start_iso,
            "end": period.end_iso,
            "dedupe": dedupe,
            "max_repos": int(max_repos),
            "include_merges": bool(include_merges),
            "include_bootstraps": bool(include_bootstraps),
            "bootstrap_config": {
                "changed_threshold": bootstrap_cfg.changed_threshold,
                "files_threshold": bootstrap_cfg.files_threshold,
                "addition_ratio": bootstrap_cfg.addition_ratio,
            },
            "include_remote_prefixes": include_remote_prefixes,
            "remote_name_priority": remote_name_priority,
            "remote_filter_mode": remote_filter_mode,
            "exclude_forks": exclude_forks,
            "fork_remote_names": fork_remote_names,
            "exclude_path_prefixes": exclude_path_prefixes,
            "exclude_path_globs": exclude_path_globs,
            "me": {
                "emails": sorted(me.emails),
                "names": sorted(me.names),
                "email_globs": list(me.email_globs),
                "name_globs": list(me.name_globs),
                "github_usernames": sorted(me.github_usernames),
            },
            "aggregate": agg,
            "aggregate_excl_bootstraps": agg_excl,
            "aggregate_bootstraps": agg_boot,
            "aggregate_including_bootstraps": agg_incl,
            "languages": languages_agg,
            "excluded": excluded_agg,
            "dirs_top": top_dirs,
            "dirs_bootstraps_top": dict(sorted(dirs_boot.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))[:50]),
            "top_authors": [
                {
                    "name": a.name,
                    "email": a.email,
                    "commits": a.commits,
                    "insertions": a.insertions,
                    "deletions": a.deletions,
                    "changed": a.changed,
                    "is_me": me.matches(a.name, a.email),
                }
                for a in top_authors_rows
            ],
            "errors": [e for r in results for e in r.errors],
        }
        if label.isdigit() and len(label) == 4:
            summary["year"] = int(label)

        write_json(json_dir / f"year_{label}_summary.json", summary)
        write_json(json_dir / f"year_{label}_excluded.json", excluded_agg)
        write_repos_csv(csv_dir / f"year_{label}_repos.csv", results, label, me)
        write_authors_csv(csv_dir / f"year_{label}_authors.csv", authors_agg, me)
        write_languages_csv(csv_dir / f"year_{label}_languages.csv", languages_agg)
        write_dirs_csv(csv_dir / f"year_{label}_dirs.csv", dirs_agg)
        write_bootstrap_commits_csv(csv_dir / f"year_{label}_bootstraps_commits.csv", results, label)
        bootstrap_rows: list[dict[str, object]] = []
        for r in results:
            for c in r.bootstrap_commits_by_period.get(label, []):
                row = dict(c)
                row["repo_path"] = r.path
                row["repo_key"] = r.key
                row["remote_canonical"] = r.remote_canonical
                bootstrap_rows.append(row)
        bootstrap_rows.sort(key=lambda d: (-int(d.get("changed", 0)), str(d.get("repo_key", "")), str(d.get("sha", ""))))
        write_json(
            debug_dir / f"bootstraps_commits_{label}.json",
            {
                "period": label,
                "bootstrap_config": {
                    "changed_threshold": bootstrap_cfg.changed_threshold,
                    "files_threshold": bootstrap_cfg.files_threshold,
                    "addition_ratio": bootstrap_cfg.addition_ratio,
                },
                "commits": bootstrap_rows,
            },
        )
        write_authors_csv(csv_dir / f"year_{label}_bootstraps_authors.csv", authors_boot, me)
        write_languages_csv(csv_dir / f"year_{label}_bootstraps_languages.csv", languages_boot)
        write_dirs_csv(csv_dir / f"year_{label}_bootstraps_dirs.csv", dirs_boot)

        write_txt_and_markup(
            txt_path=report_dir / f"{review_prefix_for_label(label)}_{label}.txt",
            text=render_year_in_review(
                period=period,
                year_agg=agg,
                year_agg_bootstraps=agg_boot,
                languages=languages_agg,
                dirs=dirs_agg,
                excluded=excluded_agg,
                authors=authors_agg,
                repos=results,
                include_remote_prefixes=include_remote_prefixes,
                exclude_path_prefixes=exclude_path_prefixes,
                exclude_path_globs=exclude_path_globs,
                dedupe=dedupe,
                include_merges=bool(include_merges),
                include_bootstraps=include_bootstraps,
                bootstrap_cfg=bootstrap_cfg,
                top_n=ascii_top_n,
                me=me,
            ),
        )

        if detailed:
            months = month_labels_for_period(period)

            def filled_month_rows(stats_by_month: dict[str, dict[str, int]]) -> list[dict[str, int | str]]:
                out_rows: list[dict[str, int | str]] = []
                for m in months:
                    st = stats_by_month.get(m, {})
                    out_rows.append(
                        {
                            "month": m,
                            "commits": int(st.get("commits", 0)),
                            "insertions": int(st.get("insertions", 0)),
                            "deletions": int(st.get("deletions", 0)),
                            "changed": int(st.get("changed", 0)),
                        }
                    )
                return out_rows

            def tech_rows(stats_by_month: dict[str, dict[str, dict[str, int]]]) -> list[dict[str, int | str]]:
                rows: list[dict[str, int | str]] = []
                for m in months:
                    for tech, st in stats_by_month.get(m, {}).items():
                        changed = int(st.get("changed", 0))
                        commits = int(st.get("commits", 0))
                        if changed <= 0 and commits <= 0:
                            continue
                        rows.append(
                            {
                                "month": m,
                                "technology": tech,
                                "commits": commits,
                                "insertions": int(st.get("insertions", 0)),
                                "deletions": int(st.get("deletions", 0)),
                                "changed": changed,
                            }
                        )
                rows.sort(key=lambda r: (str(r.get("month", "")), -int(r.get("changed", 0)), str(r.get("technology", "")).lower()))
                return rows

            me_monthly_excl = aggregate_me_monthly(results, label, include_bootstraps=False)
            me_monthly_boot = aggregate_me_monthly(results, label, include_bootstraps=False, bootstraps_only=True)
            me_monthly_incl = aggregate_me_monthly(results, label, include_bootstraps=True)

            me_tech_excl = aggregate_me_monthly_tech(results, label, include_bootstraps=False)
            me_tech_boot = aggregate_me_monthly_tech(results, label, include_bootstraps=False, bootstraps_only=True)
            me_tech_incl = aggregate_me_monthly_tech(results, label, include_bootstraps=True)

            detailed_json = {
                "generated_at": generated_at,
                "root": str(scan_root),
                "period": label,
                "start": period.start_iso,
                "end": period.end_iso,
                "me_only": True,
                "technology_kind": "language_for_path",
                "months": months,
                "series": {
                    "excl_bootstraps": {
                        "totals_by_month": filled_month_rows(me_monthly_excl),
                        "by_technology_by_month": tech_rows(me_tech_excl),
                    },
                    "bootstraps": {
                        "totals_by_month": filled_month_rows(me_monthly_boot),
                        "by_technology_by_month": tech_rows(me_tech_boot),
                    },
                    "including_bootstraps": {
                        "totals_by_month": filled_month_rows(me_monthly_incl),
                        "by_technology_by_month": tech_rows(me_tech_incl),
                    },
                },
            }
            detailed_periods[label] = detailed_json
            write_json(timeseries_dir / f"year_{label}_me_timeseries.json", detailed_json)

        weekly_excl = aggregate_weekly(results, label, include_bootstraps=False)
        weekly_boot = aggregate_weekly(results, label, include_bootstraps=False, bootstraps_only=True)
        weekly_incl = aggregate_weekly(results, label, include_bootstraps=True)

        weekly_tech_excl = aggregate_weekly_tech(results, label, include_bootstraps=False)
        weekly_tech_boot = aggregate_weekly_tech(results, label, include_bootstraps=False, bootstraps_only=True)
        weekly_tech_incl = aggregate_weekly_tech(results, label, include_bootstraps=True)

        def weekly_rows(w: dict[str, dict[str, int]], tech: dict[str, dict[str, dict[str, int]]]) -> list[dict[str, object]]:
            rows: list[dict[str, int | str]] = []
            keys = sorted(set(w.keys()) | set(tech.keys()))
            for week_start in keys:
                st = w.get(week_start, {})
                techs = tech.get(week_start, {})
                tech_rows: list[dict[str, int | str]] = []
                for tname, tst in techs.items():
                    changed = int(tst.get("changed", 0))
                    commits = int(tst.get("commits", 0))
                    if changed <= 0 and commits <= 0:
                        continue
                    tech_rows.append(
                        {
                            "technology": tname,
                            "commits": commits,
                            "insertions": int(tst.get("insertions", 0)),
                            "deletions": int(tst.get("deletions", 0)),
                            "changed": changed,
                        }
                    )
                tech_rows.sort(key=lambda r: (-int(r.get("changed", 0)), str(r.get("technology", "")).lower()))
                rows.append(
                    {
                        "week_start": week_start,
                        "commits": int(st.get("commits", 0)),
                        "insertions": int(st.get("insertions", 0)),
                        "deletions": int(st.get("deletions", 0)),
                        "changed": int(st.get("changed", 0)),
                        "technologies": tech_rows,
                    }
                )
            return rows

        write_json(
            timeseries_dir / f"year_{label}_weekly.json",
            {
                "generated_at": generated_at,
                "period": label,
                "start": period.start_iso,
                "end": period.end_iso,
                "technology_kind": "language_for_path",
                "definition": {
                    "bucket": "week_start_monday_00_00_00Z",
                    "timestamp_source": "author_time_%aI_converted_to_utc",
                },
                "series": {
                    "excl_bootstraps": weekly_rows(weekly_excl, weekly_tech_excl),
                    "bootstraps": weekly_rows(weekly_boot, weekly_tech_boot),
                    "including_bootstraps": weekly_rows(weekly_incl, weekly_tech_incl),
                },
            },
        )

    write_repo_activity_csv(csv_dir / "repo_activity.csv", results, [p.label for p in periods])
    write_top_commits_csv(csv_dir / "top_commits.csv", results, [p.label for p in periods], limit=50)
    if detailed:
        write_json(timeseries_dir / "me_timeseries.json", {"generated_at": generated_at, "periods": detailed_periods})

    # Comparison markdown (if exactly two periods)
    if len(periods) == 2:
        p0 = periods[0]
        p1 = periods[1]
        y0 = period_aggs_incl[p0.label] if include_bootstraps else period_aggs_excl[p0.label]
        y1 = period_aggs_incl[p1.label] if include_bootstraps else period_aggs_excl[p1.label]
        l0 = period_langs_incl[p0.label] if include_bootstraps else period_langs_excl[p0.label]
        l1 = period_langs_incl[p1.label] if include_bootstraps else period_langs_excl[p1.label]
        d0 = period_dirs_incl[p0.label] if include_bootstraps else period_dirs_excl[p0.label]
        d1 = period_dirs_incl[p1.label] if include_bootstraps else period_dirs_excl[p1.label]

        write_comparison_md(
            markup_dir / f"comparison_{p0.label}_vs_{p1.label}.md",
            y0,
            y1,
            l0,
            l1,
            d0,
            d1,
            include_bootstraps=include_bootstraps,
        )
        comp_md_path = markup_dir / f"comparison_{p0.label}_vs_{p1.label}.md"
        comp_txt_path = report_dir / f"comparison_{p0.label}_vs_{p1.label}.txt"
        comp_md = comp_md_path.read_text(encoding="utf-8")
        write_txt_and_markup(txt_path=comp_txt_path, text=render_comparison_txt_from_md(comp_md), write_markup=False)

        write_txt_and_markup(
            txt_path=report_dir / f"{review_prefix_for_compare(p0.label, p1.label)}_{p0.label}_vs_{p1.label}.txt",
            text=render_yoy_year_in_review(
                period0=p0,
                period1=p1,
                agg0=y0,
                agg1=y1,
                langs0=l0,
                langs1=l1,
                top_n=ascii_top_n,
            ),
        )

    meta = {
        "generated_at": generated_at,
        "root": str(scan_root),
        "reports_dir": str(report_dir),
        "run_type": run_type,
        "periods": [{"label": p.label, "start": p.start_iso, "end": p.end_iso} for p in periods],
        "repo_count_candidates": int(repo_count_candidates),
        "repo_count_unique": len(results),
        "dedupe": dedupe,
        "max_repos": int(max_repos),
        "include_merges": bool(include_merges),
        "include_bootstraps": bool(include_bootstraps),
        "detailed": bool(detailed),
        "bootstrap_config": {
            "changed_threshold": bootstrap_cfg.changed_threshold,
            "files_threshold": bootstrap_cfg.files_threshold,
            "addition_ratio": bootstrap_cfg.addition_ratio,
        },
        "include_remote_prefixes": include_remote_prefixes,
        "remote_name_priority": remote_name_priority,
        "remote_filter_mode": remote_filter_mode,
        "exclude_forks": exclude_forks,
        "fork_remote_names": fork_remote_names,
        "exclude_path_prefixes": exclude_path_prefixes,
        "exclude_path_globs": exclude_path_globs,
        "me": {
            "emails": sorted(me.emails),
            "names": sorted(me.names),
            "email_globs": list(me.email_globs),
            "name_globs": list(me.name_globs),
            "github_usernames": sorted(me.github_usernames),
        },
        "errors_count": sum(len(r.errors) for r in results),
    }
    write_json(json_dir / "run_meta.json", meta)


def write_llm_inflection_stats(
    *,
    report_dir: Path,
    period_before: Period,
    period_after: Period,
    results: list[RepoResult],
    me: MeMatcher,
    include_bootstraps: bool,
) -> None:
    markup_dir = report_dir / "markup"
    ensure_dir(markup_dir)

    y0 = aggregate_period(results, period_before, me, include_bootstraps=include_bootstraps)
    y1 = aggregate_period(results, period_after, me, include_bootstraps=include_bootstraps)
    l0 = aggregate_languages(results, period_before.label, include_bootstraps=include_bootstraps)
    l1 = aggregate_languages(results, period_after.label, include_bootstraps=include_bootstraps)
    d0 = aggregate_dirs(results, period_before.label, include_bootstraps=include_bootstraps)
    d1 = aggregate_dirs(results, period_after.label, include_bootstraps=include_bootstraps)

    md_path = markup_dir / "llm_inflection_stats.md"
    write_comparison_md(
        md_path,
        y0,
        y1,
        l0,
        l1,
        d0,
        d1,
        include_bootstraps=include_bootstraps,
    )

    txt_path = report_dir / "llm_inflection_stats.txt"
    txt_path.write_text(render_comparison_txt_from_md(md_path.read_text(encoding="utf-8")), encoding="utf-8")
