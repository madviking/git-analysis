from __future__ import annotations

from pathlib import Path

from .analysis_aggregate import repo_period_stats
from .analysis_periods import Period
from .identity import MeMatcher
from .models import AuthorStats, BootstrapConfig, RepoResult

YEAR_IN_REVIEW_BANNER = r"""
+------------------------------------------------------------------------+
|                              YEAR IN REVIEW                             |
+------------------------------------------------------------------------+
""".strip("\n")


def fmt_int(n: int) -> str:
    return f"{int(n):,}"


def trunc(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    if max_len <= 1:
        return s[:max_len]
    return s[: max_len - 1] + "…"


def bar(value: int, max_value: int, width: int = 22) -> str:
    if max_value <= 0:
        filled = 0
    else:
        filled = int(round((value / max_value) * width))
    filled = max(0, min(width, filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def repo_label(r: RepoResult) -> str:
    if r.remote_canonical:
        return r.remote_canonical
    return Path(r.path).name


def render_year_in_review(
    *,
    period: Period,
    year_agg: dict,
    year_agg_bootstraps: dict,
    languages: dict[str, dict[str, int]],
    dirs: dict[str, dict[str, int]],
    excluded: dict[str, int],
    authors: dict[str, AuthorStats],
    repos: list[RepoResult],
    include_remote_prefixes: list[str],
    exclude_path_prefixes: list[str],
    exclude_path_globs: list[str],
    dedupe: str,
    include_merges: bool,
    include_bootstraps: bool,
    bootstrap_cfg: BootstrapConfig,
    top_n: int,
    me: MeMatcher,
) -> str:
    lines: list[str] = []
    lines.append(YEAR_IN_REVIEW_BANNER)
    lines.append("")
    lines.append(f"YEAR IN REVIEW: {period.label}")
    lines.append(f"Range: {period.start_iso} -> {period.end_iso} (exclusive end)")
    lines.append("")
    lines.append(
        f"Repos analyzed: {fmt_int(int(year_agg.get('repos_total', 0)))} (dedupe={dedupe}, merges={'yes' if include_merges else 'no'}, refs=all)"
    )
    lines.append(
        f"Bootstraps: {'included' if include_bootstraps else 'excluded'} "
        f"(thresholds: changed>={bootstrap_cfg.changed_threshold}, files>={bootstrap_cfg.files_threshold}, add_ratio>={bootstrap_cfg.addition_ratio:.2f})"
    )
    if include_remote_prefixes:
        lines.append(f"Remote filter: {', '.join(include_remote_prefixes)}")
    if exclude_path_prefixes or exclude_path_globs:
        lines.append(
            "Path excludes: "
            + ", ".join([*exclude_path_prefixes, *exclude_path_globs][:6])
            + (" ..." if (len(exclude_path_prefixes) + len(exclude_path_globs)) > 6 else "")
        )
    lines.append("")
    lines.append("Totals")
    lines.append("-" * 72)
    lines.append(
        f"Commits:        {fmt_int(int(year_agg.get('commits_total', 0))):>12}  "
        f"(me {fmt_int(int(year_agg.get('commits_me', 0))):>10}, others {fmt_int(int(year_agg.get('commits_others', 0))):>10})"
    )
    lines.append(
        f"Lines changed:  {fmt_int(int(year_agg.get('changed_total', 0))):>12}  "
        f"(me {fmt_int(int(year_agg.get('changed_me', 0))):>10}, others {fmt_int(int(year_agg.get('changed_others', 0))):>10})"
    )
    lines.append(
        f"Insertions:     {fmt_int(int(year_agg.get('insertions_total', 0))):>12}  "
        f"(me {fmt_int(int(year_agg.get('insertions_me', 0))):>10}, others {fmt_int(int(year_agg.get('insertions_others', 0))):>10})"
    )
    lines.append(
        f"Deletions:      {fmt_int(int(year_agg.get('deletions_total', 0))):>12}  "
        f"(me {fmt_int(int(year_agg.get('deletions_me', 0))):>10}, others {fmt_int(int(year_agg.get('deletions_others', 0))):>10})"
    )
    if int(year_agg_bootstraps.get("changed_total", 0)) > 0:
        lines.append(
            f"Bootstraps:     {fmt_int(int(year_agg_bootstraps.get('changed_total', 0))):>12}  "
            f"(commits {fmt_int(int(year_agg_bootstraps.get('commits_total', 0)))})"
        )
    if int(excluded.get("excluded_changed", 0)) > 0:
        lines.append(
            f"Excluded lines: {fmt_int(int(excluded.get('excluded_changed', 0))):>12}  "
            f"(files {fmt_int(int(excluded.get('excluded_files', 0)))})"
        )
    lines.append("")
    lines.append(
        f"Active repos:   {fmt_int(int(year_agg.get('repos_with_commits', 0)))} "
        f"(mine: {fmt_int(int(year_agg.get('repos_with_my_commits', 0)))}), "
        f"new projects: {fmt_int(int(year_agg.get('new_projects_by_history', 0)))} "
        f"(started by me: {fmt_int(int(year_agg.get('new_projects_started_by_me', 0)))})"
    )
    lines.append("")

    # Languages
    lines.append("Top languages (changed lines)")
    lines.append("-" * 72)
    langs_sorted = sorted(languages.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
    max_changed = int(langs_sorted[0][1].get("changed", 0)) if langs_sorted else 0
    for lang, st in langs_sorted[:top_n]:
        changed = int(st.get("changed", 0))
        lines.append(f"{trunc(lang, 20):20} {fmt_int(changed):>12}  {bar(changed, max_changed)}")
    if not langs_sorted:
        lines.append("(no file changes detected)")
    lines.append("")

    # Directories
    lines.append("Top directories (changed lines)")
    lines.append("-" * 72)
    dirs_sorted = sorted(dirs.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
    max_dir = int(dirs_sorted[0][1].get("changed", 0)) if dirs_sorted else 0
    for d, st in dirs_sorted[:top_n]:
        changed = int(st.get("changed", 0))
        lines.append(f"{trunc(d, 20):20} {fmt_int(changed):>12}  {bar(changed, max_dir)}")
    if not dirs_sorted:
        lines.append("(no directories detected)")
    lines.append("")

    # Repos
    lines.append("Top repos (changed lines)")
    lines.append("-" * 72)
    repo_items: list[tuple[int, RepoResult]] = []
    for r in repos:
        ys = repo_period_stats(r, period.label, include_bootstraps=include_bootstraps)
        repo_items.append((ys.changed_total, r))
    repo_items.sort(key=lambda t: (-t[0], repo_label(t[1]).lower()))
    max_repo = repo_items[0][0] if repo_items else 0
    for changed, r in repo_items[:top_n]:
        label = trunc(repo_label(r), 44)
        lines.append(f"{label:44} {fmt_int(changed):>12}  {bar(changed, max_repo)}")
    if not repo_items:
        lines.append("(no repo changes detected)")
    lines.append("")

    # Authors
    lines.append("Top authors (commits)")
    lines.append("-" * 72)
    author_items = sorted(authors.values(), key=lambda a: (-a.commits, -a.changed, (a.email or "").lower()))
    shown = 0
    for a in author_items:
        is_me = me.matches(a.name, a.email)
        label = trunc((a.name or a.email or "unknown") + (" [me]" if is_me else ""), 28)
        lines.append(f"{label:28} commits {fmt_int(a.commits):>8}  changed {fmt_int(a.changed):>10}")
        shown += 1
        if shown >= top_n:
            break
    if shown == 0:
        lines.append("(no non-me authors detected)")

    return "\n".join(lines) + "\n"


def render_yoy_year_in_review(
    *,
    period0: Period,
    period1: Period,
    agg0: dict,
    agg1: dict,
    langs0: dict[str, dict[str, int]],
    langs1: dict[str, dict[str, int]],
    top_n: int,
) -> str:
    def row(label: str, key: str) -> str:
        old = int(agg0.get(key, 0))
        new = int(agg1.get(key, 0))
        delta = new - old
        delta_s = f"{delta:+,}"
        return f"{label:18} {fmt_int(old):>12} -> {fmt_int(new):>12}   {delta_s:>12}   {pct_change(old, new):>8}"

    lines: list[str] = []
    lines.append(YEAR_IN_REVIEW_BANNER)
    lines.append("")
    lines.append(f"YEAR IN REVIEW: {period0.label} -> {period1.label}")
    lines.append(f"Range: {period0.start_iso}->{period0.end_iso} vs {period1.start_iso}->{period1.end_iso}")
    lines.append("")
    lines.append("Year-over-year totals")
    lines.append("-" * 72)
    lines.append(row("Commits (total)", "commits_total"))
    lines.append(row("Lines changed", "changed_total"))
    lines.append(row("Insertions", "insertions_total"))
    lines.append(row("Deletions", "deletions_total"))
    lines.append(row("Active repos", "repos_with_commits"))
    lines.append(row("New projects", "new_projects_by_history"))
    lines.append("")
    lines.append("Year-over-year languages (changed lines)")
    lines.append("-" * 72)

    def top_langs(d: dict[str, dict[str, int]]) -> list[str]:
        return [k for k, _ in sorted(d.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))[:top_n]]

    candidate: list[str] = []
    for l in top_langs(langs0) + top_langs(langs1):
        if l not in candidate:
            candidate.append(l)
    for lang in candidate[:top_n]:
        old = int(langs0.get(lang, {}).get("changed", 0))
        new = int(langs1.get(lang, {}).get("changed", 0))
        delta = new - old
        delta_s = f"{delta:+,}"
        lines.append(
            f"{trunc(lang, 18):18} {fmt_int(old):>12} -> {fmt_int(new):>12}   {delta_s:>12}   {pct_change(old, new):>8}"
        )

    return "\n".join(lines) + "\n"


def pct_change(old: int, new: int) -> str:
    if old == 0:
        return "n/a" if new == 0 else "+inf"
    return f"{((new - old) / old) * 100.0:+.1f}%"


def write_comparison_md(
    path: Path,
    y0: dict,
    y1: dict,
    languages0: dict[str, dict[str, int]] | None = None,
    languages1: dict[str, dict[str, int]] | None = None,
    dirs0: dict[str, dict[str, int]] | None = None,
    dirs1: dict[str, dict[str, int]] | None = None,
    y0_boot: dict | None = None,
    y1_boot: dict | None = None,
    languages0_boot: dict[str, dict[str, int]] | None = None,
    languages1_boot: dict[str, dict[str, int]] | None = None,
    dirs0_boot: dict[str, dict[str, int]] | None = None,
    dirs1_boot: dict[str, dict[str, int]] | None = None,
    y0_incl: dict | None = None,
    y1_incl: dict | None = None,
    top_languages: int = 15,
    top_dirs: int = 20,
) -> None:
    a = str(y0.get("period") or y0.get("year"))
    b = str(y1.get("period") or y1.get("year"))

    lines: list[str] = []
    lines.append(f"# Git comparison: {a} → {b}")
    lines.append("")
    lines.append(f"Repos analyzed: {int(y0.get('repos_total', 0)):,} ({a}), {int(y1.get('repos_total', 0)):,} ({b})")
    lines.append("")
    lines.append("## Totals (excluding bootstraps)")
    lines.append("")
    lines.append(f"| Metric | {a} | {b} | Δ | Δ% |")
    lines.append("|---|---:|---:|---:|---:|")

    def row(metric: str, key: str) -> None:
        old = int(y0[key])
        new = int(y1[key])
        lines.append(f"| {metric} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")

    row("Repos with commits", "repos_with_commits")
    row("Repos with my commits", "repos_with_my_commits")
    row("New projects (history)", "new_projects_by_history")
    row("New projects started by me", "new_projects_started_by_me")
    row("Commits (total)", "commits_total")
    row("Commits (me)", "commits_me")
    row("Commits (others)", "commits_others")
    row("Lines changed (total)", "changed_total")
    row("Lines changed (me)", "changed_me")
    row("Lines changed (others)", "changed_others")
    row("Insertions (total)", "insertions_total")
    row("Insertions (me)", "insertions_me")
    row("Insertions (others)", "insertions_others")
    row("Deletions (total)", "deletions_total")
    row("Deletions (me)", "deletions_me")
    row("Deletions (others)", "deletions_others")
    lines.append("")

    def top_union_keys(d0: dict[str, dict[str, int]], d1: dict[str, dict[str, int]], metric_key: str, limit: int) -> list[str]:
        by0 = sorted(d0.items(), key=lambda kv: (-int(kv[1].get(metric_key, 0)), kv[0].lower()))[:limit]
        by1 = sorted(d1.items(), key=lambda kv: (-int(kv[1].get(metric_key, 0)), kv[0].lower()))[:limit]
        candidates = {k for k, _ in by0} | {k for k, _ in by1}
        return sorted(
            candidates,
            key=lambda k: (-max(int(d0.get(k, {}).get(metric_key, 0)), int(d1.get(k, {}).get(metric_key, 0))), k.lower()),
        )

    def pct_value(old: int, new: int) -> float:
        if old == 0:
            return float("inf") if new != 0 else -float("inf")
        return ((new - old) / old) * 100.0

    def sort_keys_by_pct_change(d0: dict[str, dict[str, int]], d1: dict[str, dict[str, int]], metric_key: str, keys: list[str]) -> list[str]:
        return sorted(
            keys,
            key=lambda k: (
                -pct_value(int(d0.get(k, {}).get(metric_key, 0)), int(d1.get(k, {}).get(metric_key, 0))),
                -(int(d1.get(k, {}).get(metric_key, 0)) - int(d0.get(k, {}).get(metric_key, 0))),
                -max(int(d0.get(k, {}).get(metric_key, 0)), int(d1.get(k, {}).get(metric_key, 0))),
                k.lower(),
            ),
        )

    def boot_row(metric: str, key: str) -> None:
        assert y0_boot is not None and y1_boot is not None
        old = int(y0_boot.get(key, 0))
        new = int(y1_boot.get(key, 0))
        lines.append(f"| {metric} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")

    if y0_boot is not None and y1_boot is not None:
        lines.append("## Bootstraps (totals)")
        lines.append("")
        lines.append(f"| Metric | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        boot_row("Repos with commits", "repos_with_commits")
        boot_row("Repos with my commits", "repos_with_my_commits")
        boot_row("Commits (total)", "commits_total")
        boot_row("Commits (me)", "commits_me")
        boot_row("Lines changed (total)", "changed_total")
        boot_row("Lines changed (me)", "changed_me")
        boot_row("Insertions (total)", "insertions_total")
        boot_row("Deletions (total)", "deletions_total")
        lines.append("")

    if y0_incl is not None and y1_incl is not None:
        lines.append("## Totals (including bootstraps)")
        lines.append("")
        lines.append(f"| Metric | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")

        def incl_row(metric: str, key: str) -> None:
            old = int(y0_incl.get(key, 0))
            new = int(y1_incl.get(key, 0))
            lines.append(f"| {metric} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")

        incl_row("Repos with commits", "repos_with_commits")
        incl_row("Repos with my commits", "repos_with_my_commits")
        incl_row("New projects (history)", "new_projects_by_history")
        incl_row("New projects started by me", "new_projects_started_by_me")
        incl_row("Commits (total)", "commits_total")
        incl_row("Commits (me)", "commits_me")
        incl_row("Lines changed (total)", "changed_total")
        incl_row("Lines changed (me)", "changed_me")
        incl_row("Insertions (total)", "insertions_total")
        incl_row("Deletions (total)", "deletions_total")
        lines.append("")

    if languages0 is not None and languages1 is not None:
        lines.append("## Languages (changed lines, excluding bootstraps)")
        lines.append("")
        lines.append(f"| Language | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")

        # Select the rows to include by volume (max of the two periods), then sort that fixed set by Δ%.
        langs = top_union_keys(languages0, languages1, "changed", top_languages)[:top_languages]
        for lang in sort_keys_by_pct_change(languages0, languages1, "changed", langs):
            old = int(languages0.get(lang, {}).get("changed", 0))
            new = int(languages1.get(lang, {}).get("changed", 0))
            lines.append(f"| {lang} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

        lines.append("## Languages (my changed lines, excluding bootstraps)")
        lines.append("")
        lines.append(f"| Language | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        langs = top_union_keys(languages0, languages1, "changed_me", top_languages)[:top_languages]
        for lang in sort_keys_by_pct_change(languages0, languages1, "changed_me", langs):
            old = int(languages0.get(lang, {}).get("changed_me", 0))
            new = int(languages1.get(lang, {}).get("changed_me", 0))
            lines.append(f"| {lang} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    if dirs0 is not None and dirs1 is not None:
        lines.append("## Directories (changed lines, excluding bootstraps)")
        lines.append("")
        lines.append(f"| Directory | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        dirs = top_union_keys(dirs0, dirs1, "changed", top_dirs)[:top_dirs]
        for d in sort_keys_by_pct_change(dirs0, dirs1, "changed", dirs):
            old = int(dirs0.get(d, {}).get("changed", 0))
            new = int(dirs1.get(d, {}).get("changed", 0))
            lines.append(f"| {d} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

        lines.append("## Directories (my changed lines, excluding bootstraps)")
        lines.append("")
        lines.append(f"| Directory | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        dirs = top_union_keys(dirs0, dirs1, "changed_me", top_dirs)[:top_dirs]
        for d in sort_keys_by_pct_change(dirs0, dirs1, "changed_me", dirs):
            old = int(dirs0.get(d, {}).get("changed_me", 0))
            new = int(dirs1.get(d, {}).get("changed_me", 0))
            lines.append(f"| {d} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    if languages0_boot is not None and languages1_boot is not None:
        lines.append("## Languages (bootstraps, changed lines)")
        lines.append("")
        lines.append(f"| Language | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        langs = top_union_keys(languages0_boot, languages1_boot, "changed", top_languages)[:top_languages]
        for lang in sort_keys_by_pct_change(languages0_boot, languages1_boot, "changed", langs):
            old = int(languages0_boot.get(lang, {}).get("changed", 0))
            new = int(languages1_boot.get(lang, {}).get("changed", 0))
            lines.append(f"| {lang} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    if dirs0_boot is not None and dirs1_boot is not None:
        lines.append("## Directories (bootstraps, changed lines)")
        lines.append("")
        lines.append(f"| Directory | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        dirs = top_union_keys(dirs0_boot, dirs1_boot, "changed", top_dirs)[:top_dirs]
        for d in sort_keys_by_pct_change(dirs0_boot, dirs1_boot, "changed", dirs):
            old = int(dirs0_boot.get(d, {}).get("changed", 0))
            new = int(dirs1_boot.get(d, {}).get("changed", 0))
            lines.append(f"| {d} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

