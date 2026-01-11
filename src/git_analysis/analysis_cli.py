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
    parser.add_argument(
        "--halves",
        type=str,
        default="",
        help="Compare two half-year periods (e.g. --halves 2025 or --halves H12025,H22025).",
    )
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
    parser.add_argument("--publish", choices=["no", "yes", "ask"], default="no", help="Optionally publish an upload package.")
    parser.add_argument(
        "--upload-url",
        type=str,
        default="",
        help="Override `upload_config.api_url` (or provide full /api/v1/uploads URL).",
    )
    parser.add_argument(
        "--ca-bundle",
        type=str,
        default="",
        help="Path to a CA bundle file/dir for HTTPS verification (overrides `upload_config.ca_bundle_path`).",
    )
    parser.add_argument("--publisher", type=str, default="", help="Public identity string (optional; not verified).")
    parser.add_argument("--publisher-token-path", type=Path, default=None, help="Path to persist the local publisher token.")
    return parser


def _split_csv_args(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        for part in str(v).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _parse_periods(args: argparse.Namespace) -> list[Period]:
    if args.periods:
        periods = [parse_period(s) for s in _split_csv_args(args.periods)]
    elif str(args.halves).strip():
        halves = str(args.halves).strip()
        if halves.isdigit():
            y = int(halves)
            periods = [parse_period(f"{y}H1"), parse_period(f"{y}H2")]
        else:
            toks = _split_csv_args([halves])
            if len(toks) == 2:
                periods = [parse_period(toks[0]), parse_period(toks[1])]
            elif len(toks) == 1:
                p = parse_period(toks[0])
                if p.label.endswith("H1") or p.label.endswith("H2"):
                    y = int(p.label[:4])
                    periods = [parse_period(f"{y}H1"), parse_period(f"{y}H2")]
                else:
                    raise SystemExit(f"--halves expects a year or half-year period, got: {halves!r}")
            else:
                raise SystemExit(f"--halves expects 1 or 2 values, got: {halves!r}")
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
