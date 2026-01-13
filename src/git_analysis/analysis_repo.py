from __future__ import annotations

import datetime as dt
import subprocess
import threading
from collections import defaultdict
from pathlib import Path
from heapq import heapify, heapreplace, heappush

from .analysis_paths import dir_key_for_path, language_for_path, normalize_numstat_path, should_exclude_path
from .analysis_periods import Period
from .git import get_first_commit, get_last_commit
from .identity import MeMatcher, normalize_email
from .models import AuthorStats, BootstrapConfig, RepoResult, RepoYearStats


def _week_start_iso(commit_iso: str) -> str:
    s = (commit_iso or "").strip()
    if not s:
        return ""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    d_utc = d.astimezone(dt.timezone.utc)
    date_utc = d_utc.date()
    week_start = date_utc - dt.timedelta(days=date_utc.weekday())
    return f"{week_start.isoformat()}T00:00:00Z"


def parse_numstat_stream(
    repo: Path,
    period: Period,
    include_merges: bool,
    me: MeMatcher,
    bootstrap: BootstrapConfig,
    exclude_path_prefixes: list[str],
    exclude_path_globs: list[str],
    bootstrap_exclude_shas: set[str] | None = None,
    exclude_commits: set[str] | None = None,
) -> tuple[
    RepoYearStats,  # excl bootstraps
    RepoYearStats,  # bootstraps only
    dict[str, dict[str, int]],  # weekly excl: week_start -> {commits,insertions,deletions}
    dict[str, dict[str, int]],  # weekly bootstraps: week_start -> {commits,insertions,deletions}
    dict[str, dict[str, dict[str, int]]],  # weekly tech excl: week_start -> tech -> {commits,insertions,deletions}
    dict[str, dict[str, dict[str, int]]],  # weekly tech boot: week_start -> tech -> {commits,insertions,deletions}
    dict[str, dict[str, int]],  # me weekly excl: week_start -> {commits,insertions,deletions}
    dict[str, dict[str, int]],  # me weekly boot: week_start -> {commits,insertions,deletions}
    dict[str, dict[str, dict[str, int]]],  # me weekly tech excl: week_start -> tech -> {commits,insertions,deletions}
    dict[str, dict[str, dict[str, int]]],  # me weekly tech boot: week_start -> tech -> {commits,insertions,deletions}
    dict[str, AuthorStats],  # authors excl
    dict[str, AuthorStats],  # authors bootstraps
    dict[str, dict[str, int]],  # languages excl
    dict[str, dict[str, int]],  # languages bootstraps
    dict[str, dict[str, int]],  # dirs excl
    dict[str, dict[str, int]],  # dirs bootstraps
    dict[str, dict[str, int]],  # me monthly excl: month -> {commits,insertions,deletions}
    dict[str, dict[str, int]],  # me monthly bootstraps: month -> {commits,insertions,deletions}
    dict[str, dict[str, dict[str, int]]],  # me monthly tech excl: month -> tech -> {commits,insertions,deletions}
    dict[str, dict[str, dict[str, int]]],  # me monthly tech bootstraps: month -> tech -> {commits,insertions,deletions}
    dict[str, int],  # excluded path counters
    list[dict[str, object]],  # bootstrap commits
    list[dict[str, object]],  # top commits by size
    list[str],  # errors
]:
    start = f"{period.start_iso}T00:00:00Z"
    end = f"{period.end_iso}T00:00:00Z"

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
    weekly_excl: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    weekly_boot: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    weekly_tech_excl: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0}))
    weekly_tech_boot: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0}))
    me_weekly_excl: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    me_weekly_boot: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    me_weekly_tech_excl: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    )
    me_weekly_tech_boot: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    )
    authors_excl: dict[str, AuthorStats] = {}
    authors_boot: dict[str, AuthorStats] = {}
    languages_excl: dict[str, dict[str, int]] = defaultdict(
        lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0}
    )
    languages_boot: dict[str, dict[str, int]] = defaultdict(
        lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0}
    )
    dirs_excl: dict[str, dict[str, int]] = defaultdict(
        lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0}
    )
    dirs_boot: dict[str, dict[str, int]] = defaultdict(
        lambda: {"insertions": 0, "deletions": 0, "insertions_me": 0, "deletions_me": 0}
    )
    me_monthly_excl: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    me_monthly_boot: dict[str, dict[str, int]] = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    me_monthly_tech_excl: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    )
    me_monthly_tech_boot: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
    )
    excluded: dict[str, int] = {
        "excluded_files": 0,
        "excluded_insertions": 0,
        "excluded_deletions": 0,
        "excluded_changed": 0,
    }
    bootstrap_commits: list[dict[str, object]] = []
    top_commits_heap: list[tuple[int, str, str, dict[str, object]]] = []
    heapify(top_commits_heap)
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
    current_excluded_files = 0
    current_excluded_insertions = 0
    current_excluded_deletions = 0
    current_excluded_changed = 0

    def apply_commit() -> None:
        nonlocal current_sha, current_author_name, current_author_email, current_author_is_me
        nonlocal current_commit_iso, current_subject, current_insertions, current_deletions, current_files_touched
        nonlocal current_langs, current_dirs
        nonlocal current_excluded_files, current_excluded_insertions, current_excluded_deletions, current_excluded_changed

        if not current_sha:
            return

        excluded_commits = exclude_commits or set()
        if current_sha in excluded_commits:
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
            current_excluded_files = 0
            current_excluded_insertions = 0
            current_excluded_deletions = 0
            current_excluded_changed = 0
            return

        excluded["excluded_files"] += current_excluded_files
        excluded["excluded_insertions"] += current_excluded_insertions
        excluded["excluded_deletions"] += current_excluded_deletions
        excluded["excluded_changed"] += current_excluded_changed

        bootstrap_shas_excluded = bootstrap_exclude_shas or set()
        is_boot = bootstrap.is_bootstrap(current_insertions, current_deletions, current_files_touched) and current_sha not in bootstrap_shas_excluded
        stats_target = stats_boot if is_boot else stats_excl
        weekly_target = weekly_boot if is_boot else weekly_excl
        weekly_tech_target = weekly_tech_boot if is_boot else weekly_tech_excl
        me_weekly_target = me_weekly_boot if is_boot else me_weekly_excl
        me_weekly_tech_target = me_weekly_tech_boot if is_boot else me_weekly_tech_excl
        authors_target = authors_boot if is_boot else authors_excl
        langs_target = languages_boot if is_boot else languages_excl
        dirs_target = dirs_boot if is_boot else dirs_excl

        stats_target.commits_total += 1
        stats_target.insertions_total += current_insertions
        stats_target.deletions_total += current_deletions

        wk = _week_start_iso(current_commit_iso)
        if wk:
            weekly_target[wk]["commits"] += 1
            weekly_target[wk]["insertions"] += current_insertions
            weekly_target[wk]["deletions"] += current_deletions
            for tech, (ins, dele) in current_langs.items():
                if (ins + dele) <= 0:
                    continue
                weekly_tech_target[wk][tech]["commits"] += 1
                weekly_tech_target[wk][tech]["insertions"] += ins
                weekly_tech_target[wk][tech]["deletions"] += dele
            if current_author_is_me:
                me_weekly_target[wk]["commits"] += 1
                me_weekly_target[wk]["insertions"] += current_insertions
                me_weekly_target[wk]["deletions"] += current_deletions
                for tech, (ins, dele) in current_langs.items():
                    if (ins + dele) <= 0:
                        continue
                    me_weekly_tech_target[wk][tech]["commits"] += 1
                    me_weekly_tech_target[wk][tech]["insertions"] += ins
                    me_weekly_tech_target[wk][tech]["deletions"] += dele
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

        month_key = current_commit_iso[:7] if len(current_commit_iso) >= 7 and current_commit_iso[4:5] == "-" else ""
        if current_author_is_me and month_key:
            m_target = me_monthly_boot if is_boot else me_monthly_excl
            m_target[month_key]["commits"] += 1
            m_target[month_key]["insertions"] += current_insertions
            m_target[month_key]["deletions"] += current_deletions

            tech_target = me_monthly_tech_boot if is_boot else me_monthly_tech_excl
            for tech, (ins, dele) in current_langs.items():
                tech_target[month_key][tech]["commits"] += 1
                tech_target[month_key][tech]["insertions"] += ins
                tech_target[month_key][tech]["deletions"] += dele

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

        commit_row: dict[str, object] = {
            "sha": current_sha,
            "commit_iso": current_commit_iso,
            "author_name": current_author_name,
            "author_email": current_author_email,
            "is_me": bool(current_author_is_me),
            "is_bootstrap": bool(is_boot),
            "subject": current_subject,
            "files_touched": int(current_files_touched),
            "insertions": int(current_insertions),
            "deletions": int(current_deletions),
            "changed": int(current_insertions + current_deletions),
        }
        entry = (
            int(commit_row.get("changed", 0)),
            str(commit_row.get("sha", "")),
            str(commit_row.get("commit_iso", "")),
            commit_row,
        )
        if len(top_commits_heap) < 50:
            heappush(top_commits_heap, entry)
        else:
            if entry > top_commits_heap[0]:
                heapreplace(top_commits_heap, entry)

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
        current_excluded_files = 0
        current_excluded_insertions = 0
        current_excluded_deletions = 0
        current_excluded_changed = 0

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
            dict(weekly_excl),
            dict(weekly_boot),
            {wk: dict(techs) for wk, techs in weekly_tech_excl.items()},
            {wk: dict(techs) for wk, techs in weekly_tech_boot.items()},
            dict(me_weekly_excl),
            dict(me_weekly_boot),
            {wk: dict(techs) for wk, techs in me_weekly_tech_excl.items()},
            {wk: dict(techs) for wk, techs in me_weekly_tech_boot.items()},
            authors_excl,
            authors_boot,
            dict(languages_excl),
            dict(languages_boot),
            dict(dirs_excl),
            dict(dirs_boot),
            dict(me_monthly_excl),
            dict(me_monthly_boot),
            {m: dict(v) for m, v in me_monthly_tech_excl.items()},
            {m: dict(v) for m, v in me_monthly_tech_boot.items()},
            dict(excluded),
            bootstrap_commits,
            [],
            [f"failed to start git log: {e}"],
        )

    stderr_chunks: list[str] = []
    stderr_chars = 0
    max_stderr_chars = 50_000

    def drain_stderr() -> None:
        nonlocal stderr_chars
        if proc.stderr is None:
            return
        while True:
            chunk = proc.stderr.read(8192)
            if not chunk:
                return
            if stderr_chars >= max_stderr_chars:
                continue
            take = chunk[: max_stderr_chars - stderr_chars]
            stderr_chunks.append(take)
            stderr_chars += len(take)

    stderr_thread: threading.Thread | None = None
    if proc.stderr is not None:
        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        stderr_thread.start()

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
            current_excluded_files += 1
            current_excluded_insertions += added
            current_excluded_deletions += deleted
            current_excluded_changed += added + deleted
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

    code = proc.wait()
    if stderr_thread is not None:
        stderr_thread.join()
    stderr = "".join(stderr_chunks)
    if code != 0:
        errors.append(f"git log exited {code}: {stderr.strip()[:500]}")

    apply_commit()

    top_commits = [t[-1] for t in top_commits_heap]
    top_commits.sort(key=lambda d: (-int(d.get("changed", 0)), str(d.get("sha", ""))))

    return (
        stats_excl,
        stats_boot,
        dict(weekly_excl),
        dict(weekly_boot),
        {wk: dict(techs) for wk, techs in weekly_tech_excl.items()},
        {wk: dict(techs) for wk, techs in weekly_tech_boot.items()},
        dict(me_weekly_excl),
        dict(me_weekly_boot),
        {wk: dict(techs) for wk, techs in me_weekly_tech_excl.items()},
        {wk: dict(techs) for wk, techs in me_weekly_tech_boot.items()},
        authors_excl,
        authors_boot,
        dict(languages_excl),
        dict(languages_boot),
        dict(dirs_excl),
        dict(dirs_boot),
        dict(me_monthly_excl),
        dict(me_monthly_boot),
        {m: dict(v) for m, v in me_monthly_tech_excl.items()},
        {m: dict(v) for m, v in me_monthly_tech_boot.items()},
        dict(excluded),
        bootstrap_commits,
        top_commits,
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
    bootstrap_exclude_shas: set[str] | None = None,
    exclude_commits: set[str] | None = None,
) -> RepoResult:
    errors: list[str] = []

    first_iso, first_name, first_email = get_first_commit(repo)
    last_iso, _ = get_last_commit(repo)

    period_stats_excl: dict[str, RepoYearStats] = {}
    period_stats_boot: dict[str, RepoYearStats] = {}
    weekly_by_period_excl: dict[str, dict[str, dict[str, int]]] = {}
    weekly_by_period_boot: dict[str, dict[str, dict[str, int]]] = {}
    weekly_tech_by_period_excl: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    weekly_tech_by_period_boot: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    me_weekly_by_period_excl: dict[str, dict[str, dict[str, int]]] = {}
    me_weekly_by_period_boot: dict[str, dict[str, dict[str, int]]] = {}
    me_weekly_tech_by_period_excl: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    me_weekly_tech_by_period_boot: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    authors_by_period_excl: dict[str, dict[str, AuthorStats]] = {}
    authors_by_period_boot: dict[str, dict[str, AuthorStats]] = {}
    languages_by_period_excl: dict[str, dict[str, dict[str, int]]] = {}
    languages_by_period_boot: dict[str, dict[str, dict[str, int]]] = {}
    dirs_by_period_excl: dict[str, dict[str, dict[str, int]]] = {}
    dirs_by_period_boot: dict[str, dict[str, dict[str, int]]] = {}
    me_monthly_by_period_excl: dict[str, dict[str, dict[str, int]]] = {}
    me_monthly_by_period_boot: dict[str, dict[str, dict[str, int]]] = {}
    me_monthly_tech_by_period_excl: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    me_monthly_tech_by_period_boot: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    excluded_by_period: dict[str, dict[str, int]] = {}
    bootstrap_commits_by_period: dict[str, list[dict[str, object]]] = {}
    top_commits_by_period: dict[str, list[dict[str, object]]] = {}

    for period in periods:
        (
            stats_excl_boot,
            stats_boot_only,
            weekly_excl_boot,
            weekly_boot_only,
            weekly_tech_excl_boot,
            weekly_tech_boot_only,
            me_weekly_excl_boot,
            me_weekly_boot_only,
            me_weekly_tech_excl_boot,
            me_weekly_tech_boot_only,
            authors_excl_boot,
            authors_boot_only,
            langs_excl_boot,
            langs_boot_only,
            dirs_excl_boot,
            dirs_boot_only,
            me_monthly_excl_boot,
            me_monthly_boot_only,
            me_monthly_tech_excl_boot,
            me_monthly_tech_boot_only,
            excluded,
            boot_commits,
            top_commits,
            errs,
        ) = parse_numstat_stream(
            repo=repo,
            period=period,
            include_merges=include_merges,
            me=me,
            bootstrap=bootstrap,
            exclude_path_prefixes=exclude_path_prefixes,
            exclude_path_globs=exclude_path_globs,
            bootstrap_exclude_shas=bootstrap_exclude_shas,
            exclude_commits=exclude_commits,
        )
        period_stats_excl[period.label] = stats_excl_boot
        period_stats_boot[period.label] = stats_boot_only
        weekly_by_period_excl[period.label] = weekly_excl_boot
        weekly_by_period_boot[period.label] = weekly_boot_only
        weekly_tech_by_period_excl[period.label] = weekly_tech_excl_boot
        weekly_tech_by_period_boot[period.label] = weekly_tech_boot_only
        me_weekly_by_period_excl[period.label] = me_weekly_excl_boot
        me_weekly_by_period_boot[period.label] = me_weekly_boot_only
        me_weekly_tech_by_period_excl[period.label] = me_weekly_tech_excl_boot
        me_weekly_tech_by_period_boot[period.label] = me_weekly_tech_boot_only
        authors_by_period_excl[period.label] = authors_excl_boot
        authors_by_period_boot[period.label] = authors_boot_only
        languages_by_period_excl[period.label] = langs_excl_boot
        languages_by_period_boot[period.label] = langs_boot_only
        dirs_by_period_excl[period.label] = dirs_excl_boot
        dirs_by_period_boot[period.label] = dirs_boot_only
        me_monthly_by_period_excl[period.label] = me_monthly_excl_boot
        me_monthly_by_period_boot[period.label] = me_monthly_boot_only
        me_monthly_tech_by_period_excl[period.label] = me_monthly_tech_excl_boot
        me_monthly_tech_by_period_boot[period.label] = me_monthly_tech_boot_only
        excluded_by_period[period.label] = excluded
        bootstrap_commits_by_period[period.label] = boot_commits
        top_commits_by_period[period.label] = top_commits
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
        weekly_by_period_excl_bootstraps=weekly_by_period_excl,
        weekly_by_period_bootstraps=weekly_by_period_boot,
        weekly_tech_by_period_excl_bootstraps=weekly_tech_by_period_excl,
        weekly_tech_by_period_bootstraps=weekly_tech_by_period_boot,
        me_weekly_by_period_excl_bootstraps=me_weekly_by_period_excl,
        me_weekly_by_period_bootstraps=me_weekly_by_period_boot,
        me_weekly_tech_by_period_excl_bootstraps=me_weekly_tech_by_period_excl,
        me_weekly_tech_by_period_bootstraps=me_weekly_tech_by_period_boot,
        authors_by_period_excl_bootstraps=authors_by_period_excl,
        authors_by_period_bootstraps=authors_by_period_boot,
        languages_by_period_excl_bootstraps=languages_by_period_excl,
        languages_by_period_bootstraps=languages_by_period_boot,
        dirs_by_period_excl_bootstraps=dirs_by_period_excl,
        dirs_by_period_bootstraps=dirs_by_period_boot,
        me_monthly_by_period_excl_bootstraps=me_monthly_by_period_excl,
        me_monthly_by_period_bootstraps=me_monthly_by_period_boot,
        me_monthly_tech_by_period_excl_bootstraps=me_monthly_tech_by_period_excl,
        me_monthly_tech_by_period_bootstraps=me_monthly_tech_by_period_boot,
        excluded_by_period=excluded_by_period,
        bootstrap_commits_by_period=bootstrap_commits_by_period,
        top_commits_by_period=top_commits_by_period,
        errors=errors,
    )
