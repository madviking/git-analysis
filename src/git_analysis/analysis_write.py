from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .analysis_aggregate import repo_period_stats
from .identity import MeMatcher
from .models import AuthorStats, RepoResult, RepoYearStats


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")


def write_repo_selection_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for r in rows:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_repo_selection_summary(path: Path, rows: list[dict[str, str]]) -> None:
    counts_by_status: dict[str, int] = defaultdict(int)
    counts_by_reason: dict[str, int] = defaultdict(int)
    included_keys: set[str] = set()
    for r in rows:
        status = r.get("status", "") or ""
        counts_by_status[status] += 1
        reason = r.get("reason", "") or ""
        if reason:
            counts_by_reason[reason] += 1
        if status == "included":
            k = r.get("dedupe_key", "") or ""
            if k:
                included_keys.add(k)

    summary = {
        "counts_by_status": dict(sorted(counts_by_status.items(), key=lambda kv: (-kv[1], kv[0]))),
        "counts_by_reason": dict(sorted(counts_by_reason.items(), key=lambda kv: (-kv[1], kv[0]))),
        "included_unique_keys": len(included_keys),
    }
    write_json(path, summary)


def write_repos_csv(path: Path, repos: list[RepoResult], period_label: str, me: MeMatcher) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "repo_key",
                "repo_path",
                "remote_name",
                "remote_origin",
                "remote_canonical",
                "duplicate_paths",
                "first_commit_iso",
                "first_commit_by_me",
                "last_commit_iso",
                "commits_total_excl_bootstraps",
                "commits_total_bootstraps",
                "commits_total_including_bootstraps",
                "changed_total_excl_bootstraps",
                "changed_total_bootstraps",
                "changed_total_including_bootstraps",
                "commits_me_excl_bootstraps",
                "commits_me_bootstraps",
                "commits_me_including_bootstraps",
                "changed_me_excl_bootstraps",
                "changed_me_bootstraps",
                "changed_me_including_bootstraps",
            ]
        )
        for r in repos:
            ys_excl = r.period_stats_excl_bootstraps.get(period_label, RepoYearStats())
            ys_boot = r.period_stats_bootstraps.get(period_label, RepoYearStats())
            ys_incl = repo_period_stats(r, period_label, include_bootstraps=True)
            first_by_me = False
            if r.first_commit_author_name and r.first_commit_author_email:
                first_by_me = me.matches(r.first_commit_author_name, r.first_commit_author_email)
            writer.writerow(
                [
                    r.key,
                    r.path,
                    r.remote_name,
                    r.remote,
                    r.remote_canonical,
                    ";".join(r.duplicates),
                    r.first_commit_iso or "",
                    str(first_by_me),
                    r.last_commit_iso or "",
                    ys_excl.commits_total,
                    ys_boot.commits_total,
                    ys_incl.commits_total,
                    ys_excl.changed_total,
                    ys_boot.changed_total,
                    ys_incl.changed_total,
                    ys_excl.commits_me,
                    ys_boot.commits_me,
                    ys_incl.commits_me,
                    ys_excl.changed_me,
                    ys_boot.changed_me,
                    ys_incl.changed_me,
                ]
            )


def write_authors_csv(
    path: Path,
    author_stats: dict[str, AuthorStats],
    me: MeMatcher,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["author_email", "author_name", "is_me", "commits", "insertions", "deletions", "changed"])
        for email_key, st in sorted(author_stats.items(), key=lambda kv: (-kv[1].commits, kv[0])):
            writer.writerow(
                [
                    st.email,
                    st.name,
                    str(me.matches(st.name, st.email)),
                    st.commits,
                    st.insertions,
                    st.deletions,
                    st.changed,
                ]
            )


def write_languages_csv(path: Path, languages: dict[str, dict[str, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "language",
                "insertions_total",
                "deletions_total",
                "changed_total",
                "insertions_me",
                "deletions_me",
                "changed_me",
                "insertions_others",
                "deletions_others",
                "changed_others",
            ]
        )
        for lang, st in sorted(languages.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower())):
            writer.writerow(
                [
                    lang,
                    int(st.get("insertions", 0)),
                    int(st.get("deletions", 0)),
                    int(st.get("changed", 0)),
                    int(st.get("insertions_me", 0)),
                    int(st.get("deletions_me", 0)),
                    int(st.get("changed_me", 0)),
                    int(st.get("insertions_others", 0)),
                    int(st.get("deletions_others", 0)),
                    int(st.get("changed_others", 0)),
                ]
            )


def write_dirs_csv(path: Path, dirs: dict[str, dict[str, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "dir",
                "insertions_total",
                "deletions_total",
                "changed_total",
                "insertions_me",
                "deletions_me",
                "changed_me",
                "insertions_others",
                "deletions_others",
                "changed_others",
            ]
        )
        for d, st in sorted(dirs.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower())):
            writer.writerow(
                [
                    d,
                    int(st.get("insertions", 0)),
                    int(st.get("deletions", 0)),
                    int(st.get("changed", 0)),
                    int(st.get("insertions_me", 0)),
                    int(st.get("deletions_me", 0)),
                    int(st.get("changed_me", 0)),
                    int(st.get("insertions_others", 0)),
                    int(st.get("deletions_others", 0)),
                    int(st.get("changed_others", 0)),
                ]
            )


def write_bootstrap_commits_csv(path: Path, repos: list[RepoResult], period_label: str) -> None:
    rows: list[dict[str, object]] = []
    for r in repos:
        for c in r.bootstrap_commits_by_period.get(period_label, []):
            row = dict(c)
            row["repo_path"] = r.path
            row["repo_key"] = r.key
            row["remote_canonical"] = r.remote_canonical
            row["remote_name"] = r.remote_name
            row["remote_origin"] = r.remote
            rows.append(row)

    rows.sort(key=lambda d: (-int(d.get("changed", 0)), str(d.get("repo_key", "")), str(d.get("sha", ""))))

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "repo_key",
                "repo_path",
                "remote_canonical",
                "sha",
                "commit_iso",
                "author_name",
                "author_email",
                "is_me",
                "files_touched",
                "insertions",
                "deletions",
                "changed",
                "subject",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.get("repo_key", ""),
                    r.get("repo_path", ""),
                    r.get("remote_canonical", ""),
                    r.get("sha", ""),
                    r.get("commit_iso", ""),
                    r.get("author_name", ""),
                    r.get("author_email", ""),
                    str(bool(r.get("is_me", False))),
                    int(r.get("files_touched", 0)),
                    int(r.get("insertions", 0)),
                    int(r.get("deletions", 0)),
                    int(r.get("changed", 0)),
                    r.get("subject", ""),
                ]
            )


def write_top_commits_csv(path: Path, repos: list[RepoResult], period_labels: list[str], *, limit: int = 50) -> None:
    wanted = list(dict.fromkeys([str(p) for p in (period_labels or []) if str(p).strip()]))
    rows: list[dict[str, object]] = []
    for label in wanted:
        for r in repos:
            for c in r.top_commits_by_period.get(label, []):
                row = dict(c)
                row["period"] = label
                row["repo_path"] = r.path
                row["repo_key"] = r.key
                row["remote_canonical"] = r.remote_canonical
                row["remote_name"] = r.remote_name
                row["remote_origin"] = r.remote
                rows.append(row)

    rows.sort(
        key=lambda d: (
            -int(d.get("changed", 0)),
            str(d.get("repo_key", "")),
            str(d.get("sha", "")),
        )
    )
    if limit > 0:
        rows = rows[:limit]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "period",
                "repo_key",
                "repo_path",
                "remote_canonical",
                "sha",
                "commit_iso",
                "author_name",
                "author_email",
                "is_me",
                "is_bootstrap",
                "files_touched",
                "insertions",
                "deletions",
                "changed",
                "subject",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.get("period", ""),
                    r.get("repo_key", ""),
                    r.get("repo_path", ""),
                    r.get("remote_canonical", ""),
                    r.get("sha", ""),
                    r.get("commit_iso", ""),
                    r.get("author_name", ""),
                    r.get("author_email", ""),
                    str(bool(r.get("is_me", False))),
                    str(bool(r.get("is_bootstrap", False))),
                    int(r.get("files_touched", 0)),
                    int(r.get("insertions", 0)),
                    int(r.get("deletions", 0)),
                    int(r.get("changed", 0)),
                    r.get("subject", ""),
                ]
            )


def write_repo_activity_csv(path: Path, repos: list[RepoResult], period_labels: list[str]) -> None:
    seen: set[str] = set()
    labels: list[str] = []
    for p in period_labels:
        if p not in seen:
            seen.add(p)
            labels.append(p)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = ["repo_path", "repo_key", "remote_canonical", "remote_name", "remote_origin"]
        for label in labels:
            header.extend(
                [
                    f"commits_excl_bootstraps_{label}",
                    f"commits_bootstraps_{label}",
                    f"commits_including_bootstraps_{label}",
                    f"changed_excl_bootstraps_{label}",
                    f"changed_bootstraps_{label}",
                    f"changed_including_bootstraps_{label}",
                ]
            )
        writer.writerow(header)
        for r in repos:
            row = [r.path, r.key, r.remote_canonical, r.remote_name, r.remote]
            for label in labels:
                ys_excl = r.period_stats_excl_bootstraps.get(label, RepoYearStats())
                ys_boot = r.period_stats_bootstraps.get(label, RepoYearStats())
                ys_incl = repo_period_stats(r, label, include_bootstraps=True)
                row.extend(
                    [
                        ys_excl.commits_total,
                        ys_boot.commits_total,
                        ys_incl.commits_total,
                        ys_excl.changed_total,
                        ys_boot.changed_total,
                        ys_incl.changed_total,
                    ]
                )
            writer.writerow(row)
