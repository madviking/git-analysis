#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BootstrapCfg:
    changed_threshold: int
    files_threshold: int
    addition_ratio: float

    def is_bootstrap(self, insertions: int, deletions: int, files_touched: int) -> bool:
        changed = insertions + deletions
        if changed < self.changed_threshold:
            return False
        if changed <= 0:
            return False
        dominant = max(insertions, deletions)
        ratio = dominant / changed

        # Keep in sync with `src/git_analysis/models.py:BootstrapConfig.is_bootstrap`.
        if files_touched >= self.files_threshold and ratio >= self.addition_ratio:
            return True
        if ratio >= self.addition_ratio and changed >= (self.changed_threshold * 8):
            return True
        if files_touched >= (self.files_threshold * 5) and changed >= (self.changed_threshold * 4):
            return True
        return False


def _load_run_meta(report_dir: Path) -> dict:
    return json.loads((report_dir / "json" / "run_meta.json").read_text(encoding="utf-8"))


def _load_repos(report_dir: Path) -> list[tuple[str, str]]:
    repos: list[tuple[str, str]] = []
    with (report_dir / "csv" / "repo_activity.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            repos.append((row["repo_path"], row.get("remote_canonical") or ""))
    return repos


def _should_exclude(path: str, prefixes: list[str], globs: list[str]) -> bool:
    return any(path.startswith(pref) for pref in prefixes) or any(fnmatch.fnmatch(path, g) for g in globs)


def _week_range(week_start: str) -> tuple[str, str]:
    d0 = dt.date.fromisoformat(week_start)
    d1 = d0 + dt.timedelta(days=7)
    return f"{d0.isoformat()}T00:00:00Z", f"{d1.isoformat()}T00:00:00Z"


def _parse_numstat_for_week(
    *,
    repo_path: str,
    remote: str,
    since_iso: str,
    before_iso: str,
    include_merges: bool,
    exclude_prefixes: list[str],
    exclude_globs: list[str],
    bootstrap: BootstrapCfg,
) -> list[dict[str, object]]:
    pretty = "@@@%H\t%aI\t%an\t%ae\t%s"
    cmd = [
        "git",
        "-C",
        repo_path,
        "log",
        "--all",
        f"--since={since_iso}",
        f"--before={before_iso}",
        "--date=iso-strict",
        f"--pretty=format:{pretty}",
        "--numstat",
    ]
    if not include_merges:
        cmd.insert(5, "--no-merges")

    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        return []

    out: list[dict[str, object]] = []
    current_sha = ""
    current_iso = ""
    current_subject = ""
    current_author_name = ""
    current_author_email = ""
    current_insertions = 0
    current_deletions = 0
    current_files_touched = 0

    def flush() -> None:
        nonlocal current_sha, current_iso, current_subject, current_author_name, current_author_email
        nonlocal current_insertions, current_deletions, current_files_touched
        if not current_sha:
            return
        changed = current_insertions + current_deletions
        out.append(
            {
                "repo_path": repo_path,
                "remote": remote,
                "sha": current_sha,
                "commit_iso": current_iso,
                "author_name": current_author_name,
                "author_email": current_author_email,
                "subject": current_subject,
                "insertions": int(current_insertions),
                "deletions": int(current_deletions),
                "files_touched": int(current_files_touched),
                "changed": int(changed),
                "bootstrap": bool(bootstrap.is_bootstrap(current_insertions, current_deletions, current_files_touched)),
            }
        )
        current_sha = ""
        current_iso = ""
        current_subject = ""
        current_author_name = ""
        current_author_email = ""
        current_insertions = 0
        current_deletions = 0
        current_files_touched = 0

    for raw_line in proc.stdout.splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("@@@"):
            flush()
            parts = line[3:].split("\t", 4)
            current_sha = parts[0] if len(parts) > 0 else ""
            current_iso = parts[1] if len(parts) > 1 else ""
            current_author_name = parts[2] if len(parts) > 2 else ""
            current_author_email = parts[3] if len(parts) > 3 else ""
            current_subject = parts[4] if len(parts) > 4 else ""
            continue

        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        added_s, deleted_s = parts[0], parts[1]
        file_path = parts[2] if len(parts) >= 3 else ""
        if added_s == "-" or deleted_s == "-":
            added = 0
            deleted = 0
        else:
            try:
                added = int(added_s)
                deleted = int(deleted_s)
            except ValueError:
                continue

        if file_path and _should_exclude(file_path, exclude_prefixes, exclude_globs):
            continue

        current_insertions += added
        current_deletions += deleted
        current_files_touched += 1

    flush()
    return out


def cmd_top_weeks(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir)
    p = report_dir / "timeseries" / f"year_{args.year}_weekly.json"
    if not p.exists():
        raise SystemExit(f"missing timeseries file: {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = d["series"][args.series]
    rows_sorted = sorted(rows, key=lambda r: int(r.get(args.metric, 0)), reverse=True)[: args.n]
    for row in rows_sorted:
        ws = row.get("week_start", "")[:10]
        print(
            f"{ws}\tchanged={row.get('changed')}\tins={row.get('insertions')}\t"
            f"del={row.get('deletions')}\tcommits={row.get('commits')}"
        )
    return 0


def cmd_explain_week(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir)
    run_meta = _load_run_meta(report_dir)
    repos = _load_repos(report_dir)
    since_iso, before_iso = _week_range(args.week_start)

    boot = run_meta["bootstrap_config"]
    bootstrap = BootstrapCfg(
        changed_threshold=int(boot["changed_threshold"]),
        files_threshold=int(boot["files_threshold"]),
        addition_ratio=float(boot["addition_ratio"]),
    )
    exclude_prefixes = list(run_meta.get("exclude_path_prefixes") or [])
    exclude_globs = list(run_meta.get("exclude_path_globs") or [])
    include_merges = bool(run_meta.get("include_merges"))

    rows: list[dict[str, object]] = []
    for repo_path, remote in repos:
        rows.extend(
            _parse_numstat_for_week(
                repo_path=repo_path,
                remote=remote,
                since_iso=since_iso,
                before_iso=before_iso,
                include_merges=include_merges,
                exclude_prefixes=exclude_prefixes,
                exclude_globs=exclude_globs,
                bootstrap=bootstrap,
            )
        )

    def match_view(row: dict[str, object]) -> bool:
        is_boot = bool(row.get("bootstrap"))
        if args.view == "bootstraps":
            return is_boot
        if args.view == "non_bootstraps":
            return not is_boot
        return True

    rows = [r for r in rows if match_view(r)]
    rows.sort(key=lambda r: (-int(r.get("changed", 0)), str(r.get("remote", "")), str(r.get("sha", ""))))

    shown = 0
    for r in rows:
        changed = int(r.get("changed", 0))
        if changed <= 0:
            continue
        ins = int(r.get("insertions", 0))
        dele = int(r.get("deletions", 0))
        ratio = (max(ins, dele) / changed) if changed else 0.0
        print(
            f"{str(r.get('commit_iso', ''))[:10]}\t{r.get('remote', '')}\t{str(r.get('sha', ''))[:8]}\t"
            f"ch={changed}\tins={ins}\tdel={dele}\tfiles={int(r.get('files_touched', 0))}\t"
            f"ratio={ratio:.2f}\tboot={int(bool(r.get('bootstrap')))}\t{r.get('subject', '')}\t{r.get('repo_path', '')}"
        )
        shown += 1
        if shown >= args.limit:
            break

    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Explain activity spikes in a git-analysis report.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_top = sub.add_parser("top-weeks", help="Print the peak weeks from timeseries JSON.")
    p_top.add_argument("--report-dir", required=True)
    p_top.add_argument("--year", type=int, required=True)
    p_top.add_argument("--series", choices=["excl_bootstraps", "bootstraps", "including_bootstraps"], default="excl_bootstraps")
    p_top.add_argument("--metric", choices=["changed", "insertions", "deletions", "commits"], default="changed")
    p_top.add_argument("--n", type=int, default=10)
    p_top.set_defaults(func=cmd_top_weeks)

    p_explain = sub.add_parser("explain-week", help="Scan local repos and show top commits for a given week.")
    p_explain.add_argument("--report-dir", required=True)
    p_explain.add_argument("--week-start", required=True, help="YYYY-MM-DD (Monday, week start)")
    p_explain.add_argument("--view", choices=["non_bootstraps", "bootstraps", "all"], default="non_bootstraps")
    p_explain.add_argument("--limit", type=int, default=25)
    p_explain.set_defaults(func=cmd_explain_week)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
