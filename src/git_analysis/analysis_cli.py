from __future__ import annotations

import argparse
import os
from pathlib import Path

from .analysis_periods import Period, parse_period
from .analysis_run import run_analysis


def _build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Write additional JSON time series for 'me' (monthly totals + per-technology).",
    )
    return parser


def _parse_periods(args: argparse.Namespace) -> list[Period]:
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
    return periods


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    periods = _parse_periods(args)
    return run_analysis(args=args, periods=periods)

