from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .analysis_periods import Period, run_type_from_args, slugify
from .analysis_reports import write_reports
from .analysis_repo import analyze_repo
from .analysis_selection import discover_and_select_repos
from .analysis_write import ensure_dir
from .config import infer_me, load_config
from .identity import MeMatcher, normalize_email, normalize_github_username, normalize_name
from .models import BootstrapConfig, RepoResult


def run_analysis(*, args: argparse.Namespace, periods: list[Period]) -> int:
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

    try:
        (reports_root / "latest.txt").write_text(str(report_dir.relative_to(reports_root)) + "\n", encoding="utf-8")
    except Exception:
        pass

    candidates, repos_to_analyze, selection_rows = discover_and_select_repos(
        scan_root,
        exclude_dirnames,
        include_remote_prefixes=include_remote_prefixes,
        remote_name_priority=remote_name_priority,
        remote_filter_mode=remote_filter_mode,
        exclude_forks=exclude_forks,
        fork_remote_names=fork_remote_names,
        dedupe=str(args.dedupe),
    )

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

    write_reports(
        report_dir=report_dir,
        scan_root=scan_root,
        run_type=run_type,
        periods=periods,
        results=results,
        selection_rows=selection_rows,
        repo_count_candidates=len(candidates),
        dedupe=str(args.dedupe),
        max_repos=int(args.max_repos),
        include_merges=bool(args.include_merges),
        include_bootstraps=include_bootstraps,
        bootstrap_cfg=bootstrap_cfg,
        include_remote_prefixes=include_remote_prefixes,
        remote_name_priority=remote_name_priority,
        remote_filter_mode=remote_filter_mode,
        exclude_forks=exclude_forks,
        fork_remote_names=fork_remote_names,
        exclude_path_prefixes=exclude_path_prefixes,
        exclude_path_globs=exclude_path_globs,
        me=me,
        top_authors=int(args.top_authors),
        detailed=bool(args.detailed),
        ascii_top_n=10,
    )

    print(f"Done. Reports in: {report_dir}")
    return 0

