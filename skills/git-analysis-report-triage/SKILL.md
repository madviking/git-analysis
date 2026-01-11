---
name: git-analysis-report-triage
description: Triage a git-analysis report directory: quickly summarize run settings, spot repo/weekly skews, inspect bootstraps, and decide next debugging steps.
---

# Git Analysis Report Triage

Use this when you have a `reports/.../<timestamp>/` directory and need to quickly understand “what happened” (repo selection, bootstraps, excluded paths, and skew).

## Quick Start

- Summary of the run:
  - `python skills/git-analysis-report-triage/scripts/report_triage.py summarize --report-dir <REPORT_DIR>`
- Biggest weeks (from timeseries JSON):
  - `python skills/git-analysis-report-triage/scripts/report_triage.py top-weeks --report-dir <REPORT_DIR> --year 2025 --series excl_bootstraps --n 10`
- Biggest repos by churn:
  - `python skills/git-analysis-report-triage/scripts/report_triage.py repo-skew --report-dir <REPORT_DIR> --year 2025 --view excl_bootstraps --metric changed --top 15`
- Biggest bootstrap commits:
  - `python skills/git-analysis-report-triage/scripts/report_triage.py top-bootstraps --report-dir <REPORT_DIR> --period 2025 --top 25`
- Repo selection sanity check (dedupe/skip/duplicate):
  - `python skills/git-analysis-report-triage/scripts/report_triage.py selection-summary --report-dir <REPORT_DIR>`

## What To Do Next

- If the skew is “data dumps / snapshots”: prefer adding `exclude_path_globs` for those directories.
- If it’s “single extreme commit”: consider bootstrap detection or `bootstrap_exclude_shas` (one-off).
- If you need the exact commit list behind a weekly spike: use the separate spike skill:
  - `skills/git-analysis-spike-investigation/SKILL.md`
