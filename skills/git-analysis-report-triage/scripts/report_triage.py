#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _report_dir(p: str) -> Path:
    report_dir = Path(p)
    if not report_dir.exists():
        raise SystemExit(f"report dir not found: {report_dir}")
    if not (report_dir / "json" / "run_meta.json").exists():
        raise SystemExit(f"not a report dir (missing json/run_meta.json): {report_dir}")
    return report_dir


def cmd_summarize(args: argparse.Namespace) -> int:
    report_dir = _report_dir(args.report_dir)
    run_meta = _load_json(report_dir / "json" / "run_meta.json")

    print(f"report_dir\t{report_dir}")
    for k in ["generated_at", "run_type", "root", "dedupe", "repo_count_candidates", "repo_count_unique"]:
        if k in run_meta:
            print(f"{k}\t{run_meta[k]}")
    for k in ["include_merges", "include_bootstraps", "max_repos", "detailed"]:
        if k in run_meta:
            print(f"{k}\t{int(bool(run_meta[k])) if isinstance(run_meta[k], bool) else run_meta[k]}")

    boot = run_meta.get("bootstrap_config") or {}
    if boot:
        print(
            "bootstrap_config\t"
            f"changed_threshold={boot.get('changed_threshold')} "
            f"files_threshold={boot.get('files_threshold')} "
            f"addition_ratio={boot.get('addition_ratio')}"
        )

    inc = run_meta.get("include_remote_prefixes") or []
    if inc:
        print(f"include_remote_prefixes\t{len(inc)}")

    prefixes = run_meta.get("exclude_path_prefixes") or []
    globs = run_meta.get("exclude_path_globs") or []
    print(f"exclude_path_prefixes\t{len(prefixes)}")
    print(f"exclude_path_globs\t{len(globs)}")

    periods = run_meta.get("periods") or []
    if periods:
        labels = [p.get("label", "") for p in periods]
        print(f"periods\t{','.join(labels)}")

    return 0


def cmd_top_weeks(args: argparse.Namespace) -> int:
    report_dir = _report_dir(args.report_dir)
    p = report_dir / "timeseries" / f"year_{args.year}_weekly.json"
    d = _load_json(p)
    rows = d["series"][args.series]
    rows_sorted = sorted(rows, key=lambda r: int(r.get(args.metric, 0)), reverse=True)[: args.n]
    for row in rows_sorted:
        ws = row.get("week_start", "")[:10]
        print(f"{ws}\tchanged={row.get('changed')}\tins={row.get('insertions')}\tdel={row.get('deletions')}\tcommits={row.get('commits')}")
    return 0


def cmd_repo_skew(args: argparse.Namespace) -> int:
    report_dir = _report_dir(args.report_dir)
    p = report_dir / "csv" / "repo_activity.csv"
    metric_col = f"{args.metric}_{args.view}_{args.year}"
    rows: list[dict[str, str]] = []
    with p.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    def val(r: dict[str, str]) -> int:
        try:
            return int(r.get(metric_col) or 0)
        except ValueError:
            return 0

    rows_sorted = sorted(rows, key=val, reverse=True)[: args.top]
    for row in rows_sorted:
        v = val(row)
        if v <= 0:
            continue
        remote = row.get("remote_canonical") or ""
        repo_path = row.get("repo_path") or ""
        print(f"{v}\t{remote}\t{repo_path}")
    return 0


def cmd_top_bootstraps(args: argparse.Namespace) -> int:
    report_dir = _report_dir(args.report_dir)
    p = report_dir / "debug" / f"bootstraps_commits_{args.period}.json"
    d = _load_json(p)
    commits = list(d.get("commits") or [])
    commits_sorted = sorted(commits, key=lambda c: int(c.get("changed", 0)), reverse=True)[: args.top]
    for c in commits_sorted:
        iso = str(c.get("commit_iso", ""))[:10]
        remote = c.get("remote_canonical", "")
        sha = str(c.get("sha", ""))[:8]
        changed = int(c.get("changed", 0))
        ins = int(c.get("insertions", 0))
        dele = int(c.get("deletions", 0))
        files = int(c.get("files_touched", 0))
        subject = c.get("subject", "")
        print(f"{iso}\t{remote}\t{sha}\tch={changed}\tins={ins}\tdel={dele}\tfiles={files}\t{subject}")
    return 0


def cmd_selection_summary(args: argparse.Namespace) -> int:
    report_dir = _report_dir(args.report_dir)
    p = report_dir / "debug" / "repo_selection.csv"
    rows: list[dict[str, str]] = []
    with p.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    by_status: dict[str, int] = {}
    for r in rows:
        s = (r.get("status") or "").strip() or "?"
        by_status[s] = by_status.get(s, 0) + 1

    for k in sorted(by_status.keys()):
        print(f"status:{k}\t{by_status[k]}")

    replaced = [r for r in rows if (r.get("note") or "").startswith("replaced_clone:")]
    if replaced:
        print(f"replaced_clone\t{len(replaced)}")
        for r in replaced[: args.limit]:
            remote = r.get("remote_canonical") or ""
            repo_path = r.get("repo_path") or ""
            note = r.get("note") or ""
            print(f"replaced\t{remote}\t{repo_path}\t{note}")

    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Triage a git-analysis report directory.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sum = sub.add_parser("summarize")
    p_sum.add_argument("--report-dir", required=True)
    p_sum.set_defaults(func=cmd_summarize)

    p_weeks = sub.add_parser("top-weeks")
    p_weeks.add_argument("--report-dir", required=True)
    p_weeks.add_argument("--year", type=int, required=True)
    p_weeks.add_argument("--series", choices=["excl_bootstraps", "bootstraps", "including_bootstraps"], default="excl_bootstraps")
    p_weeks.add_argument("--metric", choices=["changed", "insertions", "deletions", "commits"], default="changed")
    p_weeks.add_argument("--n", type=int, default=10)
    p_weeks.set_defaults(func=cmd_top_weeks)

    p_repo = sub.add_parser("repo-skew")
    p_repo.add_argument("--report-dir", required=True)
    p_repo.add_argument("--year", type=int, required=True)
    p_repo.add_argument("--view", choices=["excl_bootstraps", "bootstraps", "including_bootstraps"], default="excl_bootstraps")
    p_repo.add_argument("--metric", choices=["changed", "commits"], default="changed")
    p_repo.add_argument("--top", type=int, default=15)
    p_repo.set_defaults(func=cmd_repo_skew)

    p_boot = sub.add_parser("top-bootstraps")
    p_boot.add_argument("--report-dir", required=True)
    p_boot.add_argument("--period", required=True, help="e.g. 2024, 2025, 2025H1")
    p_boot.add_argument("--top", type=int, default=25)
    p_boot.set_defaults(func=cmd_top_bootstraps)

    p_sel = sub.add_parser("selection-summary")
    p_sel.add_argument("--report-dir", required=True)
    p_sel.add_argument("--limit", type=int, default=10)
    p_sel.set_defaults(func=cmd_selection_summary)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

