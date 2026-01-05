#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import fnmatch
import json
import os
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import infer_me, load_config
from .git import (
    canonicalize_remote,
    detect_fork,
    discover_git_roots,
    get_first_commit,
    get_last_commit,
    get_remote_origin,
    get_remote_urls,
    get_repo_toplevel,
    remotes_included,
    remote_included,
    run_git,
    select_remote,
)
from .identity import (
    MeMatcher,
    github_username_from_email,
    normalize_email,
    normalize_github_username,
    normalize_name,
)
from .models import AuthorStats, BootstrapConfig, RepoResult, RepoYearStats


@dataclasses.dataclass(frozen=True)
class Period:
    label: str
    start: dt.date  # inclusive
    end: dt.date  # exclusive

    @property
    def start_iso(self) -> str:
        return self.start.isoformat()

    @property
    def end_iso(self) -> str:
        return self.end.isoformat()


def parse_period(spec: str) -> Period:
    s = (spec or "").strip()
    if len(s) == 4 and s.isdigit():
        year = int(s)
        return Period(label=s, start=dt.date(year, 1, 1), end=dt.date(year + 1, 1, 1))
    if len(s) == 6 and s[:4].isdigit() and s[4:].upper() in ("H1", "H2"):
        year = int(s[:4])
        half = s[4:].upper()
        if half == "H1":
            return Period(label=f"{year}H1", start=dt.date(year, 1, 1), end=dt.date(year, 7, 1))
        return Period(label=f"{year}H2", start=dt.date(year, 7, 1), end=dt.date(year + 1, 1, 1))
    raise ValueError(f"Invalid period: {spec!r} (expected YYYY, YYYYH1, or YYYYH2)")


def slugify(s: str) -> str:
    s = (s or "").strip()
    out: list[str] = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif ch in (" ", ".", ":", "/", "\\"):
            out.append("-")
        else:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "run"


def run_type_from_args(args: argparse.Namespace, periods: list[Period]) -> str:
    labels = [p.label for p in periods]
    if getattr(args, "halves", 0):
        return f"halves_{int(args.halves)}"
    if getattr(args, "periods", None):
        if len(labels) == 2:
            return f"compare_{labels[0]}_vs_{labels[1]}"
        return "periods_" + "_".join(labels)
    # default: years
    if len(labels) == 2:
        return f"compare_{labels[0]}_vs_{labels[1]}"
    return "years_" + "_".join(labels)


def should_exclude_path(path: str, exclude_prefixes: list[str], exclude_globs: list[str]) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    for pref in exclude_prefixes:
        pr = (pref or "").replace("\\", "/").lstrip("./")
        if not pr:
            continue
        if not pr.endswith("/"):
            pr = pr + "/"
        if p.startswith(pr) or f"/{pr}" in p:
            return True
    for pat in exclude_globs:
        if pat and fnmatch.fnmatch(p, pat):
            return True
    return False


def normalize_numstat_path(path: str) -> str:
    p = path.strip()
    # `git log --numstat` may render renames like: src/{old => new}/file.py or src/{old.py => new.py}
    if " => " in p:
        p = p.replace("{", "").replace("}", "")
        p = p.split(" => ")[-1]
    return p.strip()


def language_for_path(path: str) -> str:
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    if base == "Dockerfile" or base.lower().startswith("dockerfile."):
        return "Dockerfile"
    if base == "Makefile" or base == "makefile":
        return "Makefile"

    ext = Path(base).suffix.lower()
    by_ext = {
        ".py": "Python",
        ".ipynb": "Jupyter",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".java": "Java",
        ".kt": "Kotlin",
        ".swift": "Swift",
        ".go": "Go",
        ".rs": "Rust",
        ".php": "PHP",
        ".rb": "Ruby",
        ".cs": "C#",
        ".c": "C",
        ".h": "C/C++ Headers",
        ".cpp": "C++",
        ".hpp": "C++",
        ".mm": "Objective-C++",
        ".m": "Objective-C",
        ".scala": "Scala",
        ".sql": "SQL",
        ".tf": "Terraform",
        ".yml": "YAML",
        ".yaml": "YAML",
        ".json": "JSON",
        ".toml": "TOML",
        ".ini": "INI",
        ".md": "Markdown",
        ".rst": "reStructuredText",
        ".html": "HTML",
        ".htm": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".sass": "Sass",
        ".less": "Less",
        ".sh": "Shell",
        ".bash": "Shell",
        ".zsh": "Shell",
        ".ps1": "PowerShell",
        ".bat": "Batch",
        ".dockerignore": "Docker",
        ".gradle": "Gradle",
        ".xml": "XML",
        ".proto": "Protobuf",
    }
    if ext in by_ext:
        return by_ext[ext]
    return "Other"


def dir_key_for_path(path: str, depth: int = 1) -> str:
    p = path.replace("\\", "/").lstrip("./")
    if not p or "/" not in p:
        return "(root)"
    parts = [x for x in p.split("/") if x]
    if not parts:
        return "(root)"
    d = "/".join(parts[: max(1, depth)])
    return d


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


def merge_author_stats(dst: dict[str, AuthorStats], src: dict[str, AuthorStats]) -> None:
    for email_key, st in src.items():
        cur = dst.get(email_key)
        if cur is None:
            dst[email_key] = AuthorStats(name=st.name, email=st.email, commits=st.commits, insertions=st.insertions, deletions=st.deletions)
            continue
        if not cur.name and st.name:
            cur.name = st.name
        if not cur.email and st.email:
            cur.email = st.email
        cur.commits += st.commits
        cur.insertions += st.insertions
        cur.deletions += st.deletions


def parse_numstat_stream(
    repo: Path,
    period: Period,
    include_merges: bool,
    me: MeMatcher,
    bootstrap: BootstrapConfig,
    exclude_path_prefixes: list[str],
    exclude_path_globs: list[str],
) -> tuple[
    RepoYearStats,  # excl bootstraps
    RepoYearStats,  # bootstraps only
    dict[str, AuthorStats],  # authors excl
    dict[str, AuthorStats],  # authors bootstraps
    dict[str, dict[str, int]],  # languages excl
    dict[str, dict[str, int]],  # languages bootstraps
    dict[str, dict[str, int]],  # dirs excl
    dict[str, dict[str, int]],  # dirs bootstraps
    dict[str, int],  # excluded path counters
    list[dict[str, object]],  # bootstrap commits
    list[str],  # errors
]:
    start = period.start_iso
    end = period.end_iso

    pretty = "@@@%H\t%an\t%ae\t%aI\t%s"
    cmd = [
        "git",
        "log",
        "--all",
        f"--since={start}",
        f"--before={end}",
        "--date=iso-strict",
        f"--pretty=format:{pretty}",
        "--numstat",
    ]
    if not include_merges:
        cmd.insert(2, "--no-merges")

    stats_excl = RepoYearStats()
    stats_boot = RepoYearStats()
    authors_excl: dict[str, AuthorStats] = {}
    authors_boot: dict[str, AuthorStats] = {}
    languages_excl: dict[str, dict[str, int]] = defaultdict(lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0})
    languages_boot: dict[str, dict[str, int]] = defaultdict(lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0})
    dirs_excl: dict[str, dict[str, int]] = defaultdict(lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0})
    dirs_boot: dict[str, dict[str, int]] = defaultdict(lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0})
    excluded: dict[str, int] = {
        "excluded_files": 0,
        "excluded_insertions": 0,
        "excluded_deletions": 0,
        "excluded_changed": 0,
    }
    bootstrap_commits: list[dict[str, object]] = []
    errors: list[str] = []

    current_sha = ""
    current_author_name = ""
    current_author_email = ""
    current_author_is_me = False
    current_commit_iso = ""
    current_subject = ""
    current_insertions = 0
    current_deletions = 0
    current_files_touched = 0
    current_langs: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    current_dirs: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    def apply_commit() -> None:
        nonlocal current_sha, current_author_name, current_author_email, current_author_is_me
        nonlocal current_commit_iso, current_subject, current_insertions, current_deletions, current_files_touched
        nonlocal current_langs, current_dirs

        if not current_sha:
            return

        is_boot = bootstrap.is_bootstrap(current_insertions, current_deletions, current_files_touched)
        stats_target = stats_boot if is_boot else stats_excl
        authors_target = authors_boot if is_boot else authors_excl
        langs_target = languages_boot if is_boot else languages_excl
        dirs_target = dirs_boot if is_boot else dirs_excl

        stats_target.commits_total += 1
        stats_target.insertions_total += current_insertions
        stats_target.deletions_total += current_deletions
        if current_author_is_me:
            stats_target.commits_me += 1
            stats_target.insertions_me += current_insertions
            stats_target.deletions_me += current_deletions

        email_key = normalize_email(current_author_email) if current_author_email else ""
        if email_key:
            author = authors_target.get(email_key)
            if author is None:
                author = AuthorStats(name=current_author_name, email=current_author_email)
                authors_target[email_key] = author
            author.commits += 1
            author.insertions += current_insertions
            author.deletions += current_deletions

        for lang, (ins, dele) in current_langs.items():
            langs_target[lang]["insertions"] += ins
            langs_target[lang]["deletions"] += dele
            if current_author_is_me:
                langs_target[lang]["insertions_me"] += ins
                langs_target[lang]["deletions_me"] += dele

        for d, (ins, dele) in current_dirs.items():
            dirs_target[d]["insertions"] += ins
            dirs_target[d]["deletions"] += dele
            if current_author_is_me:
                dirs_target[d]["insertions_me"] += ins
                dirs_target[d]["deletions_me"] += dele

        if is_boot:
            bootstrap_commits.append(
                {
                    "sha": current_sha,
                    "commit_iso": current_commit_iso,
                    "author_name": current_author_name,
                    "author_email": current_author_email,
                    "is_me": bool(current_author_is_me),
                    "subject": current_subject,
                    "files_touched": int(current_files_touched),
                    "insertions": int(current_insertions),
                    "deletions": int(current_deletions),
                    "changed": int(current_insertions + current_deletions),
                }
            )

        current_sha = ""
        current_author_name = ""
        current_author_email = ""
        current_author_is_me = False
        current_commit_iso = ""
        current_subject = ""
        current_insertions = 0
        current_deletions = 0
        current_files_touched = 0
        current_langs = defaultdict(lambda: (0, 0))
        current_dirs = defaultdict(lambda: (0, 0))

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        return (
            stats_excl,
            stats_boot,
            authors_excl,
            authors_boot,
            dict(languages_excl),
            dict(languages_boot),
            dict(dirs_excl),
            dict(dirs_boot),
            dict(excluded),
            bootstrap_commits,
            [f"failed to start git log: {e}"],
        )

    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("@@@"):
            apply_commit()
            parts = line[3:].split("\t", 4)
            current_sha = parts[0] if len(parts) > 0 else ""
            current_author_name = parts[1] if len(parts) > 1 else ""
            current_author_email = parts[2] if len(parts) > 2 else ""
            current_commit_iso = parts[3] if len(parts) > 3 else ""
            current_subject = parts[4] if len(parts) > 4 else ""
            current_author_is_me = me.matches(current_author_name, current_author_email)
            continue

        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        added_s, deleted_s = parts[0], parts[1]
        file_path = normalize_numstat_path(parts[2]) if len(parts) >= 3 else ""
        if added_s == "-" or deleted_s == "-":
            added = 0
            deleted = 0
        else:
            try:
                added = int(added_s)
                deleted = int(deleted_s)
            except ValueError:
                continue

        if file_path and should_exclude_path(file_path, exclude_path_prefixes, exclude_path_globs):
            excluded["excluded_files"] += 1
            excluded["excluded_insertions"] += added
            excluded["excluded_deletions"] += deleted
            excluded["excluded_changed"] += added + deleted
            continue

        if file_path:
            lang = language_for_path(file_path)
            ins0, del0 = current_langs[lang]
            current_langs[lang] = (ins0 + added, del0 + deleted)

            dk = dir_key_for_path(file_path, depth=1)
            ins1, del1 = current_dirs[dk]
            current_dirs[dk] = (ins1 + added, del1 + deleted)

        current_insertions += added
        current_deletions += deleted
        current_files_touched += 1

    stderr = ""
    if proc.stderr is not None:
        stderr = proc.stderr.read()

    code = proc.wait()
    if code != 0:
        errors.append(f"git log exited {code}: {stderr.strip()[:500]}")

    apply_commit()

    return (
        stats_excl,
        stats_boot,
        authors_excl,
        authors_boot,
        dict(languages_excl),
        dict(languages_boot),
        dict(dirs_excl),
        dict(dirs_boot),
        dict(excluded),
        bootstrap_commits,
        errors,
    )


def analyze_repo(
    repo: Path,
    key: str,
    remote_name: str,
    remote: str,
    remote_canonical: str,
    duplicates: list[str],
    periods: list[Period],
    include_merges: bool,
    me: MeMatcher,
    bootstrap: BootstrapConfig,
    exclude_path_prefixes: list[str],
    exclude_path_globs: list[str],
) -> RepoResult:
    errors: list[str] = []

    first_iso, first_name, first_email = get_first_commit(repo)
    last_iso, _ = get_last_commit(repo)

    period_stats_excl: dict[str, RepoYearStats] = {}
    period_stats_boot: dict[str, RepoYearStats] = {}
    authors_by_period_excl: dict[str, dict[str, AuthorStats]] = {}
    authors_by_period_boot: dict[str, dict[str, AuthorStats]] = {}
    languages_by_period_excl: dict[str, dict[str, dict[str, int]]] = {}
    languages_by_period_boot: dict[str, dict[str, dict[str, int]]] = {}
    dirs_by_period_excl: dict[str, dict[str, dict[str, int]]] = {}
    dirs_by_period_boot: dict[str, dict[str, dict[str, int]]] = {}
    excluded_by_period: dict[str, dict[str, int]] = {}
    bootstrap_commits_by_period: dict[str, list[dict[str, object]]] = {}

    for period in periods:
        (
            stats_excl_boot,
            stats_boot_only,
            authors_excl_boot,
            authors_boot_only,
            langs_excl_boot,
            langs_boot_only,
            dirs_excl_boot,
            dirs_boot_only,
            excluded,
            boot_commits,
            errs,
        ) = parse_numstat_stream(
            repo=repo,
            period=period,
            include_merges=include_merges,
            me=me,
            bootstrap=bootstrap,
            exclude_path_prefixes=exclude_path_prefixes,
            exclude_path_globs=exclude_path_globs,
        )
        period_stats_excl[period.label] = stats_excl_boot
        period_stats_boot[period.label] = stats_boot_only
        authors_by_period_excl[period.label] = authors_excl_boot
        authors_by_period_boot[period.label] = authors_boot_only
        languages_by_period_excl[period.label] = langs_excl_boot
        languages_by_period_boot[period.label] = langs_boot_only
        dirs_by_period_excl[period.label] = dirs_excl_boot
        dirs_by_period_boot[period.label] = dirs_boot_only
        excluded_by_period[period.label] = excluded
        bootstrap_commits_by_period[period.label] = boot_commits
        errors.extend(errs)

    return RepoResult(
        key=key,
        path=str(repo),
        remote_name=remote_name,
        remote=remote,
        remote_canonical=remote_canonical,
        duplicates=duplicates,
        first_commit_iso=first_iso,
        first_commit_author_name=first_name,
        first_commit_author_email=first_email,
        last_commit_iso=last_iso,
        period_stats_excl_bootstraps=period_stats_excl,
        period_stats_bootstraps=period_stats_boot,
        authors_by_period_excl_bootstraps=authors_by_period_excl,
        authors_by_period_bootstraps=authors_by_period_boot,
        languages_by_period_excl_bootstraps=languages_by_period_excl,
        languages_by_period_bootstraps=languages_by_period_boot,
        dirs_by_period_excl_bootstraps=dirs_by_period_excl,
        dirs_by_period_bootstraps=dirs_by_period_boot,
        excluded_by_period=excluded_by_period,
        bootstrap_commits_by_period=bootstrap_commits_by_period,
        errors=errors,
    )


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
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0})
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
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0})
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
    lines.append(f"Repos analyzed: {fmt_int(int(year_agg.get('repos_total', 0)))} (dedupe={dedupe}, merges={'yes' if include_merges else 'no'}, refs=all)")
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
        lines.append(f"{trunc(lang, 18):18} {fmt_int(old):>12} -> {fmt_int(new):>12}   {delta_s:>12}   {pct_change(old, new):>8}")

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

        # Use union of top languages from both years (by total changed).
        by_changed0 = sorted(languages0.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        by_changed1 = sorted(languages1.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        candidate_langs: list[str] = []
        for lang, _ in (by_changed0[:top_languages] + by_changed1[:top_languages]):
            if lang not in candidate_langs:
                candidate_langs.append(lang)
        for lang in candidate_langs[:top_languages]:
            old = int(languages0.get(lang, {}).get("changed", 0))
            new = int(languages1.get(lang, {}).get("changed", 0))
            lines.append(f"| {lang} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

        lines.append("## Languages (my changed lines, excluding bootstraps)")
        lines.append("")
        lines.append(f"| Language | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        by_me0 = sorted(languages0.items(), key=lambda kv: (-int(kv[1].get("changed_me", 0)), kv[0].lower()))
        by_me1 = sorted(languages1.items(), key=lambda kv: (-int(kv[1].get("changed_me", 0)), kv[0].lower()))
        candidate_langs = []
        for lang, _ in (by_me0[:top_languages] + by_me1[:top_languages]):
            if lang not in candidate_langs:
                candidate_langs.append(lang)
        for lang in candidate_langs[:top_languages]:
            old = int(languages0.get(lang, {}).get("changed_me", 0))
            new = int(languages1.get(lang, {}).get("changed_me", 0))
            lines.append(f"| {lang} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    if dirs0 is not None and dirs1 is not None:
        lines.append("## Directories (changed lines, excluding bootstraps)")
        lines.append("")
        lines.append(f"| Directory | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        by_changed0 = sorted(dirs0.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        by_changed1 = sorted(dirs1.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        candidate_dirs: list[str] = []
        for d, _ in (by_changed0[:top_dirs] + by_changed1[:top_dirs]):
            if d not in candidate_dirs:
                candidate_dirs.append(d)
        for d in candidate_dirs[:top_dirs]:
            old = int(dirs0.get(d, {}).get("changed", 0))
            new = int(dirs1.get(d, {}).get("changed", 0))
            lines.append(f"| {d} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

        lines.append("## Directories (my changed lines, excluding bootstraps)")
        lines.append("")
        lines.append(f"| Directory | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        by_me0 = sorted(dirs0.items(), key=lambda kv: (-int(kv[1].get("changed_me", 0)), kv[0].lower()))
        by_me1 = sorted(dirs1.items(), key=lambda kv: (-int(kv[1].get("changed_me", 0)), kv[0].lower()))
        candidate_dirs = []
        for d, _ in (by_me0[:top_dirs] + by_me1[:top_dirs]):
            if d not in candidate_dirs:
                candidate_dirs.append(d)
        for d in candidate_dirs[:top_dirs]:
            old = int(dirs0.get(d, {}).get("changed_me", 0))
            new = int(dirs1.get(d, {}).get("changed_me", 0))
            lines.append(f"| {d} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    if languages0_boot is not None and languages1_boot is not None:
        lines.append("## Languages (bootstraps, changed lines)")
        lines.append("")
        lines.append(f"| Language | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        by_changed0 = sorted(languages0_boot.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        by_changed1 = sorted(languages1_boot.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        candidate_langs: list[str] = []
        for lang, _ in (by_changed0[:top_languages] + by_changed1[:top_languages]):
            if lang not in candidate_langs:
                candidate_langs.append(lang)
        for lang in candidate_langs[:top_languages]:
            old = int(languages0_boot.get(lang, {}).get("changed", 0))
            new = int(languages1_boot.get(lang, {}).get("changed", 0))
            lines.append(f"| {lang} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    if dirs0_boot is not None and dirs1_boot is not None:
        lines.append("## Directories (bootstraps, changed lines)")
        lines.append("")
        lines.append(f"| Directory | {a} | {b} | Δ | Δ% |")
        lines.append("|---|---:|---:|---:|---:|")
        by_changed0 = sorted(dirs0_boot.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        by_changed1 = sorted(dirs1_boot.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))
        candidate_dirs: list[str] = []
        for d, _ in (by_changed0[:top_dirs] + by_changed1[:top_dirs]):
            if d not in candidate_dirs:
                candidate_dirs.append(d)
        for d in candidate_dirs[:top_dirs]:
            old = int(dirs0_boot.get(d, {}).get("changed", 0))
            new = int(dirs1_boot.get(d, {}).get("changed", 0))
            lines.append(f"| {d} | {old:,} | {new:,} | {new-old:+,} | {pct_change(old, new)} |")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Aggregate yearly git stats across many repos.")
    parser.add_argument("--root", type=Path, default=Path(".."), help="Root directory to scan for git repos.")
    parser.add_argument("--years", type=int, nargs="+", default=[2024, 2025], help="Years to analyze.")
    parser.add_argument("--periods", type=str, nargs="+", default=None, help="Periods to analyze (YYYY, YYYYH1, YYYYH2).")
    parser.add_argument("--halves", type=int, default=0, help="Shortcut for comparing H1 vs H2 of a year (e.g. --halves 2025).")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="Path to config.json.")
    parser.add_argument("--include-merges", action="store_true", help="Include merge commits in stats.")
    parser.add_argument("--dedupe", choices=["remote", "path"], default="remote", help="Dedupe repos by remote or by path.")
    parser.add_argument("--max-repos", type=int, default=0, help="Limit number of unique repos analyzed (0 = no limit).")
    parser.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 4))), help="Parallel git jobs.")
    parser.add_argument("--top-authors", type=int, default=25, help="Top authors to include in JSON summary.")
    parser.add_argument("--include-bootstraps", action="store_true", help="Include detected bootstrap/import commits in main stats.")
    args = parser.parse_args(argv)

    if args.periods:
        periods = [parse_period(s) for s in args.periods]
    elif int(args.halves) > 0:
        y = int(args.halves)
        periods = [parse_period(f"{y}H1"), parse_period(f"{y}H2")]
    else:
        years = sorted(set(int(y) for y in args.years))
        periods = [parse_period(str(y)) for y in years]

    seen_labels: set[str] = set()
    for p in periods:
        if p.label in seen_labels:
            raise SystemExit(f"Duplicate period label: {p.label}")
        seen_labels.add(p.label)

    config = load_config(args.config)
    me_emails_cfg = list(config.get("me_emails", []) or [])
    me_names_cfg = list(config.get("me_names", []) or [])
    me_email_globs_cfg = list(config.get("me_email_globs", []) or [])
    me_name_globs_cfg = list(config.get("me_name_globs", []) or [])
    me_github_usernames_cfg = list(config.get("me_github_usernames", []) or [])
    if not me_github_usernames_cfg and config.get("github_username"):
        me_github_usernames_cfg = [str(config.get("github_username"))]

    inferred_emails, inferred_names = infer_me()
    me_emails = {normalize_email(e) for e in (me_emails_cfg or inferred_emails) if e.strip()}
    me_names = {normalize_name(n) for n in (me_names_cfg or inferred_names) if n.strip()}
    me_email_globs = tuple(normalize_email(p) for p in me_email_globs_cfg if str(p).strip())
    me_name_globs = tuple(normalize_name(p) for p in me_name_globs_cfg if str(p).strip())
    me_github_usernames = {normalize_github_username(u) for u in me_github_usernames_cfg if str(u).strip()}
    me = MeMatcher(
        frozenset(me_emails),
        frozenset(me_names),
        email_globs=me_email_globs,
        name_globs=me_name_globs,
        github_usernames=frozenset(me_github_usernames),
    )

    exclude_dirnames = set(config.get("exclude_dirnames", [])) if config.get("exclude_dirnames") else set()
    if not exclude_dirnames:
        exclude_dirnames = {
            ".git",
            ".venv",
            "git-analysis",
            "reports",
            "node_modules",
            "vendor",
            "dist",
            "build",
            "target",
            ".idea",
            ".pytest_cache",
            "__pycache__",
        }

    include_remote_prefixes = list(config.get("include_remote_prefixes", []) or [])
    remote_name_priority = list(config.get("remote_name_priority", []) or ["origin", "upstream"])
    remote_filter_mode = str(config.get("remote_filter_mode", "any") or "any").strip().lower()
    if remote_filter_mode not in ("any", "primary"):
        remote_filter_mode = "any"
    exclude_forks = bool(config.get("exclude_forks", False))
    fork_remote_names = list(config.get("fork_remote_names", []) or ["upstream"])
    exclude_path_prefixes = list(config.get("exclude_path_prefixes", []) or [])
    exclude_path_globs = list(config.get("exclude_path_globs", []) or [])

    bootstrap_cfg = BootstrapConfig(
        changed_threshold=int(config.get("bootstrap_changed_threshold", 50_000)),
        files_threshold=int(config.get("bootstrap_files_threshold", 200)),
        addition_ratio=float(config.get("bootstrap_addition_ratio", 0.90)),
    )
    include_bootstraps = bool(args.include_bootstraps)

    scan_root = args.root.resolve()
    reports_root = Path("reports").resolve()
    ensure_dir(reports_root)

    run_type = slugify(run_type_from_args(args, periods))
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_dir = reports_root / run_type / timestamp
    ensure_dir(report_dir)

    # Convenience pointer for scripts/validation.
    try:
        (reports_root / "latest.txt").write_text(str(report_dir.relative_to(reports_root)) + "\n", encoding="utf-8")
    except Exception:
        pass

    candidates = discover_git_roots(scan_root, exclude_dirnames)

    # Canonicalize and dedupe
    by_key: dict[str, dict] = {}
    selection_rows: list[dict[str, str]] = []
    for cand in candidates:
        top = get_repo_toplevel(cand)
        if top is None:
            selection_rows.append(
                {"candidate_path": str(cand), "status": "skipped", "reason": "not_a_git_repo_after_rev_parse"}
            )
            continue
        remotes = get_remote_urls(top)
        if not remotes:
            selection_rows.append({"candidate_path": str(cand), "repo_path": str(top), "status": "skipped", "reason": "no_remotes"})
            continue
        if exclude_forks:
            is_fork, fork_parent = detect_fork(remotes, fork_remote_names=fork_remote_names)
            if is_fork:
                selection_rows.append(
                    {
                        "candidate_path": str(cand),
                        "repo_path": str(top),
                        "status": "skipped",
                        "reason": "excluded_fork",
                        "fork_parent": fork_parent,
                        "remotes": ";".join(sorted(f"{k}={canonicalize_remote(v)}" for k, v in remotes.items())),
                    }
                )
                continue
        if not remotes_included(remotes, include_remote_prefixes, remote_filter_mode):
            selection_rows.append(
                {
                    "candidate_path": str(cand),
                    "repo_path": str(top),
                    "status": "skipped",
                    "reason": "remote_filter_no_match",
                    "remotes": ";".join(sorted(f"{k}={canonicalize_remote(v)}" for k, v in remotes.items())),
                }
            )
            continue
        remote_name, remote, remote_canonical = select_remote(
            remotes, include_prefixes=include_remote_prefixes, priority=remote_name_priority
        )
        if include_remote_prefixes and remote_filter_mode == "primary" and not remote_included(remote, include_remote_prefixes):
            selection_rows.append(
                {
                    "candidate_path": str(cand),
                    "repo_path": str(top),
                    "status": "skipped",
                    "reason": "primary_remote_not_included",
                    "remote_name": remote_name,
                    "remote_canonical": remote_canonical,
                }
            )
            continue

        if args.dedupe == "remote" and remote_canonical:
            key = remote_canonical
        else:
            key = str(top)

        entry = by_key.get(key)
        if entry is None:
            last_iso, last_ts = get_last_commit(top)
            by_key[key] = {
                "repo": top,
                "remote_name": remote_name,
                "remote": remote,
                "remote_canonical": remote_canonical,
                "dups": [],
                "last_ts": last_ts,
                "last_iso": last_iso,
            }
            selection_rows.append(
                {
                    "candidate_path": str(cand),
                    "repo_path": str(top),
                    "status": "included",
                    "dedupe_key": key,
                    "remote_name": remote_name,
                    "remote_canonical": remote_canonical,
                }
            )
        else:
            dup_path = str(top)
            # Prefer the freshest clone for a deduped remote to avoid undercounting due to stale clones.
            _, cand_ts = get_last_commit(top)
            entry_ts = entry.get("last_ts")
            if entry_ts is None:
                _, entry_ts = get_last_commit(entry["repo"])
                entry["last_ts"] = entry_ts
            prefer_new = cand_ts is not None and (entry_ts is None or cand_ts > entry_ts)
            if prefer_new:
                prev_path = str(entry["repo"])
                if prev_path != dup_path and prev_path not in entry["dups"]:
                    entry["dups"].append(prev_path)
                entry["repo"] = top
                entry["remote_name"] = remote_name
                entry["remote"] = remote
                entry["remote_canonical"] = remote_canonical
                entry["last_ts"] = cand_ts
                selection_rows.append(
                    {
                        "candidate_path": str(cand),
                        "repo_path": str(top),
                        "status": "included",
                        "dedupe_key": key,
                        "remote_name": remote_name,
                        "remote_canonical": remote_canonical,
                        "note": f"replaced_clone:{prev_path}",
                    }
                )
            else:
                if dup_path != str(entry["repo"]) and dup_path not in entry["dups"]:
                    entry["dups"].append(dup_path)
                selection_rows.append(
                    {
                        "candidate_path": str(cand),
                        "repo_path": str(top),
                        "status": "duplicate",
                        "dedupe_key": key,
                        "remote_name": remote_name,
                        "remote_canonical": remote_canonical,
                        "note": f"kept_clone:{entry['repo']}",
                    }
                )

    repos_to_analyze = [
        (k, v["repo"], v.get("remote_name", ""), v["remote"], v.get("remote_canonical", ""), v["dups"])
        for k, v in by_key.items()
    ]
    repos_to_analyze.sort(key=lambda x: x[1].as_posix())
    if args.max_repos and args.max_repos > 0:
        repos_to_analyze = repos_to_analyze[: args.max_repos]
        print(f"Note: --max-repos={args.max_repos} limits analysis to the first {len(repos_to_analyze)} repos after filtering/dedupe.")

    if not repos_to_analyze:
        print(f"No git repositories found under: {scan_root}", file=sys.stderr)
        return 2

    print(f"Found {len(candidates)} repo roots; analyzing {len(repos_to_analyze)} unique repos (dedupe={args.dedupe}).")
    if not me.emails and not me.names and not me.email_globs and not me.name_globs and not me.github_usernames:
        print("Warning: could not infer 'me' identity; set config.json to get per-user stats.")

    results: list[RepoResult] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = []
        for key, repo, remote_name, remote, remote_canonical, dups in repos_to_analyze:
            futs.append(
                ex.submit(
                    analyze_repo,
                    repo,
                    key,
                    remote_name,
                    remote,
                    remote_canonical,
                    dups,
                    periods,
                    args.include_merges,
                    me,
                    bootstrap_cfg,
                    exclude_path_prefixes,
                    exclude_path_globs,
                )
            )

        for i, fut in enumerate(as_completed(futs), start=1):
            r = fut.result()
            results.append(r)
            if i % 10 == 0 or i == len(futs):
                print(f"Analyzed {i}/{len(futs)} repos...")

    results.sort(key=lambda r: r.path)

    # Write per-year outputs
    generated_at = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    write_repo_selection_csv(report_dir / "repo_selection.csv", selection_rows)
    write_repo_selection_summary(report_dir / "repo_selection_summary.json", selection_rows)
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
    ascii_top_n = 10
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

        top_authors = sorted(authors_agg.values(), key=lambda s: (-s.commits, -s.changed, s.email.lower()))[: args.top_authors]
        top_dirs = dict(
            sorted(dirs_agg.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))[:50]
        )
        summary = {
            "generated_at": generated_at,
            "root": str(scan_root),
            "period": label,
            "start": period.start_iso,
            "end": period.end_iso,
            "dedupe": args.dedupe,
            "max_repos": int(args.max_repos),
            "include_merges": bool(args.include_merges),
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
            "dirs_bootstraps_top": dict(
                sorted(dirs_boot.items(), key=lambda kv: (-int(kv[1].get("changed", 0)), kv[0].lower()))[:50]
            ),
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
                for a in top_authors
            ],
            "errors": [e for r in results for e in r.errors],
        }
        if label.isdigit() and len(label) == 4:
            summary["year"] = int(label)

        write_json(report_dir / f"year_{label}_summary.json", summary)
        write_repos_csv(report_dir / f"year_{label}_repos.csv", results, label, me)
        write_authors_csv(report_dir / f"year_{label}_authors.csv", authors_agg, me)
        write_languages_csv(report_dir / f"year_{label}_languages.csv", languages_agg)
        write_dirs_csv(report_dir / f"year_{label}_dirs.csv", dirs_agg)
        write_json(report_dir / f"year_{label}_excluded.json", excluded_agg)
        write_bootstrap_commits_csv(report_dir / f"year_{label}_bootstraps_commits.csv", results, label)
        write_authors_csv(report_dir / f"year_{label}_bootstraps_authors.csv", authors_boot, me)
        write_languages_csv(report_dir / f"year_{label}_bootstraps_languages.csv", languages_boot)
        write_dirs_csv(report_dir / f"year_{label}_bootstraps_dirs.csv", dirs_boot)

        (report_dir / f"year_in_review_{label}.txt").write_text(
            render_year_in_review(
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
                dedupe=args.dedupe,
                include_merges=bool(args.include_merges),
                include_bootstraps=include_bootstraps,
                bootstrap_cfg=bootstrap_cfg,
                top_n=ascii_top_n,
                me=me,
            ),
            encoding="utf-8",
        )

    write_repo_activity_csv(report_dir / "repo_activity.csv", results, [p.label for p in periods])

    # Comparison markdown (if exactly two periods)
    if len(periods) == 2:
        p0 = periods[0]
        p1 = periods[1]
        y0_excl = period_aggs_excl[p0.label]
        y1_excl = period_aggs_excl[p1.label]
        l0_excl = period_langs_excl[p0.label]
        l1_excl = period_langs_excl[p1.label]
        d0_excl = period_dirs_excl[p0.label]
        d1_excl = period_dirs_excl[p1.label]
        y0_boot = period_aggs_boot[p0.label]
        y1_boot = period_aggs_boot[p1.label]
        l0_boot = period_langs_boot[p0.label]
        l1_boot = period_langs_boot[p1.label]
        d0_boot = period_dirs_boot[p0.label]
        d1_boot = period_dirs_boot[p1.label]
        y0_incl = period_aggs_incl[p0.label]
        y1_incl = period_aggs_incl[p1.label]

        write_comparison_md(
            report_dir / f"comparison_{p0.label}_vs_{p1.label}.md",
            y0_excl,
            y1_excl,
            l0_excl,
            l1_excl,
            d0_excl,
            d1_excl,
            y0_boot,
            y1_boot,
            l0_boot,
            l1_boot,
            d0_boot,
            d1_boot,
            y0_incl,
            y1_incl,
        )
        (report_dir / f"year_in_review_{p0.label}_vs_{p1.label}.txt").write_text(
            render_yoy_year_in_review(
                period0=p0,
                period1=p1,
                agg0=y0_excl,
                agg1=y1_excl,
                langs0=l0_excl,
                langs1=l1_excl,
                top_n=ascii_top_n,
            ),
            encoding="utf-8",
        )

    # Small meta summary
    meta = {
        "generated_at": generated_at,
        "root": str(scan_root),
        "reports_dir": str(report_dir),
        "run_type": run_type,
        "periods": [{"label": p.label, "start": p.start_iso, "end": p.end_iso} for p in periods],
        "repo_count_candidates": len(candidates),
        "repo_count_unique": len(results),
        "dedupe": args.dedupe,
        "max_repos": int(args.max_repos),
        "include_merges": bool(args.include_merges),
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
        "errors_count": sum(len(r.errors) for r in results),
    }
    write_json(report_dir / "run_meta.json", meta)

    print(f"Done. Reports in: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
