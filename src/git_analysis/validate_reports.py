#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sum_language_totals(languages: dict) -> tuple[int, int, int]:
    ins = 0
    dele = 0
    changed = 0
    for _, st in (languages or {}).items():
        ins += int(st.get("insertions", 0))
        dele += int(st.get("deletions", 0))
        changed += int(st.get("changed", 0))
    return ins, dele, changed


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser(description="Sanity-check git-analysis report outputs.")
    ap.add_argument("--reports", type=Path, default=Path("reports"), help="Reports directory.")
    ap.add_argument("--years", type=int, nargs="*", default=[], help="Optional years to check (default: infer).")
    ap.add_argument("--periods", type=str, nargs="*", default=[], help="Optional period labels to check (default: infer).")
    args = ap.parse_args(argv)

    reports = args.reports
    if not reports.exists():
        raise SystemExit(f"Reports dir not found: {reports}")

    summaries = sorted((reports / "json").glob("year_*_summary.json")) if (reports / "json").exists() else sorted(reports.glob("year_*_summary.json"))
    if not summaries:
        latest = reports / "latest.txt"
        if latest.exists():
            rel = latest.read_text(encoding="utf-8").strip()
            if rel:
                candidate = (reports / rel).resolve()
                if candidate.exists():
                    reports = candidate
                    summaries = (
                        sorted((reports / "json").glob("year_*_summary.json"))
                        if (reports / "json").exists()
                        else sorted(reports.glob("year_*_summary.json"))
                    )
    if not summaries:
        raise SystemExit(f"No summary JSON files in: {reports}")

    labels: list[str] = []
    for p in summaries:
        stem = p.stem
        if not stem.startswith("year_") or not stem.endswith("_summary"):
            continue
        label = stem[len("year_") : -len("_summary")]
        if label:
            labels.append(label)
    labels = sorted(set(labels))
    if args.years:
        wanted = {str(y) for y in args.years}
        labels = [l for l in labels if l in wanted]
    if args.periods:
        wanted = {str(p) for p in args.periods}
        labels = [l for l in labels if l in wanted]

    ok = True
    for label in labels:
        base = reports / "json" if (reports / "json").exists() else reports
        summary_path = base / f"year_{label}_summary.json"
        if not summary_path.exists():
            print(f"[WARN] missing {summary_path}")
            ok = False
            continue

        summary = load_json(summary_path)
        agg = summary.get("aggregate", {}) or {}
        languages = summary.get("languages", {}) or {}

        ins_l, del_l, ch_l = sum_language_totals(languages)
        ins = int(agg.get("insertions_total", 0))
        dele = int(agg.get("deletions_total", 0))
        changed = int(agg.get("changed_total", 0))

        print(f"== {label} ==")
        print(f"- aggregate insertions/deletions/changed: {ins}/{dele}/{changed}")
        print(f"- languages insertions/deletions/changed: {ins_l}/{del_l}/{ch_l}")

        if (ins_l, del_l, ch_l) != (ins, dele, changed):
            ok = False
            print(f"  [WARN] mismatch: Δins={ins_l-ins:+}, Δdel={del_l-dele:+}, Δchanged={ch_l-changed:+}")

        print("")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
