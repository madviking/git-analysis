from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .analysis_periods import Period, llm_inflection_periods, parse_date_precision_to_date, run_type_from_args, slugify
from .analysis_reports import write_llm_inflection_stats, write_reports
from .analysis_repo import analyze_repo
from .analysis_selection import discover_and_select_repos
from .analysis_write import ensure_dir
from .config import ensure_config_file, infer_me, load_config
from .identity import MeMatcher, normalize_email, normalize_github_username, normalize_name
from .models import BootstrapConfig, RepoResult
from .publish import PublishInputs, collect_publish_inputs, default_publisher_token_path, publish_with_wizard


def _print_header(*, root: Path, periods: list[Period], jobs: int, dedupe: str, include_merges: bool, include_bootstraps: bool) -> None:
    lines = [
        "┌──────────────────────────────────────────────────────────────┐",
        "│                         git-analysis                          │",
        "└──────────────────────────────────────────────────────────────┘",
        "",
        "What to expect:",
        f"- Scan root: {root}",
        f"- Periods: {', '.join(p.label for p in periods)}",
        f"- Jobs: {jobs}  Dedupe: {dedupe}  Merges: {'on' if include_merges else 'off'}  Bootstraps: {'on' if include_bootstraps else 'off'}",
        "- Output: reports/<run-type>/<timestamp>/ (csv/, json/, timeseries/, markup/)",
        "- Upload: if configured, you'll be prompted to upload; edit config.json (upload_config.*) to change upload settings",
        "",
    ]
    print("\n".join(lines))


def run_analysis(*, args: argparse.Namespace, periods: list[Period]) -> int:
    _print_header(
        root=args.root.resolve(),
        periods=periods,
        jobs=int(args.jobs),
        dedupe=str(args.dedupe),
        include_merges=bool(args.include_merges),
        include_bootstraps=bool(args.include_bootstraps),
    )

    if args.config and not args.config.exists():
        candidate_template = args.config.resolve().parent / "config-template.json"
        config = ensure_config_file(
            config_path=args.config,
            template_path=candidate_template if candidate_template.exists() else Path("config-template.json").resolve(),
            scan_root=args.root.resolve(),
        )
    else:
        config = load_config(args.config)

    upload_block_reasons: list[str] = []
    if bool(args.include_merges):
        upload_block_reasons.append("--include-merges")
    if bool(args.include_bootstraps):
        upload_block_reasons.append("--include-bootstraps")
    if str(args.dedupe) != "remote":
        upload_block_reasons.append(f"--dedupe {args.dedupe}")

    if upload_block_reasons:
        print("Note: publishing disabled for this run (unsupported flags: " + ", ".join(upload_block_reasons) + ").")
        publish_inputs = PublishInputs(
            publish=False,
            display_name="",
            publisher_token_path=default_publisher_token_path(),
            upload_years=[],
        )
    else:
        publish_inputs = collect_publish_inputs(args=args, config_path=args.config, config=config, report_periods=periods)
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
    bootstrap_exclude_shas = {str(s).strip() for s in (config.get("bootstrap_exclude_shas") or []) if str(s).strip()}
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

    print(f"Scanning for git repos under: {scan_root} (this can take a while)...")
    candidates, repos_to_analyze, selection_rows = discover_and_select_repos(
        scan_root,
        exclude_dirnames,
        include_remote_prefixes=include_remote_prefixes,
        remote_name_priority=remote_name_priority,
        remote_filter_mode=remote_filter_mode,
        exclude_forks=exclude_forks,
        fork_remote_names=fork_remote_names,
        excluded_repos=list(config.get("excluded_repos", []) or []),
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

    report_periods = list(periods)
    upload_periods: list[Period] = []
    if publish_inputs.publish:
        # Uploads are always whole years; analysis may include other report periods.
        year_labels = sorted(set(int(y) for y in (publish_inputs.upload_years or []) if int(y) > 0))
        upload_periods = [Period(label=str(y), start=dt.date(y, 1, 1), end=dt.date(y + 1, 1, 1)) for y in year_labels]

    analysis_periods: list[Period] = list(report_periods)
    if upload_periods:
        existing_labels = {p.label for p in analysis_periods}
        for p in upload_periods:
            if p.label not in existing_labels:
                analysis_periods.append(p)
                existing_labels.add(p.label)

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
                    analysis_periods,
                    args.include_merges,
                    me,
                    bootstrap_cfg,
                    exclude_path_prefixes,
                    exclude_path_globs,
                    bootstrap_exclude_shas,
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
        periods=report_periods,
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

    upload_cfg = dict((config.get("upload_config") or {}) if isinstance(config.get("upload_config"), dict) else {})
    llm_coding = upload_cfg.get("llm_coding") if isinstance(upload_cfg.get("llm_coding"), dict) else {}
    dominant_at = parse_date_precision_to_date(llm_coding.get("dominant_at") if isinstance(llm_coding, dict) else None)
    if dominant_at is not None:
        try:
            p_before, p_after = llm_inflection_periods(dominant_at=dominant_at)
        except Exception:
            p_before = None
            p_after = None
        if p_before is not None and p_after is not None:
            print(f"Computing LLM inflection comparison ({p_before.start_iso}..{p_before.end_iso} vs {p_after.start_iso}..{p_after.end_iso})...")
            inflection_results: list[RepoResult] = []
            with ThreadPoolExecutor(max_workers=args.jobs) as ex:
                futs2 = []
                for key, repo, remote_name, remote, remote_canonical, dups in repos_to_analyze:
                    futs2.append(
                        ex.submit(
                            analyze_repo,
                            repo,
                            key,
                            remote_name,
                            remote,
                            remote_canonical,
                            dups,
                            [p_before, p_after],
                            args.include_merges,
                            me,
                            bootstrap_cfg,
                            exclude_path_prefixes,
                            exclude_path_globs,
                            bootstrap_exclude_shas,
                        )
                    )
                for fut in as_completed(futs2):
                    inflection_results.append(fut.result())
            inflection_results.sort(key=lambda r: r.path)
            write_llm_inflection_stats(
                report_dir=report_dir,
                period_before=p_before,
                period_after=p_after,
                results=inflection_results,
                me=me,
                include_bootstraps=include_bootstraps,
            )

    try:
        publish_with_wizard(
            report_dir=report_dir,
            upload_periods=upload_periods or report_periods,
            results=results,
            inputs=publish_inputs,
            config_path=args.config,
            args=args,
        )
    except RuntimeError as e:
        msg = str(e).strip()
        print("")
        print("Upload failed.")
        if msg:
            print(msg)
        if "privacy.mode" in msg:
            print("Hint: your server appears to expect an older upload schema; update the backend to accept the current payload format.")
        payload_path = report_dir / "json" / "upload_package_v1.json"
        if payload_path.exists():
            print(f"Payload saved at: {payload_path}")
            print(f"Retry after fixing the server: ./cli.sh upload --report-dir {report_dir} --yes")
        print(f"Done. Reports in: {report_dir}")
        return 2

    print(f"Done. Reports in: {report_dir}")
    return 0
