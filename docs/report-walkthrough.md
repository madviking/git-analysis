# Report walkthrough

Each run writes a timestamped report folder under `reports/<run-type>/<timestamp>/` and updates `reports/latest.txt` to point at the newest run.

This document describes what the files are and how to use them, based on a real run output (columns and file names may evolve, but the overall layout is stable).

## Root files (human-readable summaries)

These are meant to be opened directly in a terminal/editor.

- `year_in_review_<YYYY>.txt` / `period_in_review_<period>.txt`
  - One summary per analyzed period.
  - Includes run metadata (repo counts, filters, bootstrap policy), totals, and “top” tables for languages, directories, repos, and authors.
- `year_in_review_<YYYY0>_vs_<YYYY1>.txt` / `period_in_review_<p0>_vs_<p1>.txt`
  - Only when comparing exactly two periods.
  - Side-by-side totals with Δ and Δ%.
- `comparison_<p0>_vs_<p1>.txt`
  - Only when comparing exactly two periods.
  - Expanded comparison tables.
- `llm_inflection_stats.txt`
  - Only when `upload_config.llm_coding.dominant_at` is configured.
  - Compares “pre” vs “post” LLM-dominant periods.

## `markup/` (Markdown versions of the summaries)

If you prefer Markdown (e.g. for pasting into docs), use:

- `markup/year_in_review_*.md`
- `markup/period_in_review_*.md`
- `markup/comparison_<p0>_vs_<p1>.md` (only when comparing exactly two periods)
- `markup/llm_inflection_stats.md` (when configured)

## `csv/` (tables for analysis in spreadsheets)

These CSVs are intended for slicing/sorting in Excel/Sheets or programmatic analysis.

- `csv/year_<period>_repos.csv`
  - Per-repo totals for the period (commits and churn), plus useful metadata (canonical remote, first/last commit timestamps, and dedupe info).
- `csv/year_<period>_authors.csv`
  - Per-author totals for the period.
  - Includes `is_me` so you can split “me” vs “others”.
- `csv/year_<period>_languages.csv`
  - Per-language totals for the period, split into totals / me / others.
- `csv/year_<period>_dirs.csv`
  - Directory-level churn totals for the period (top-level directory buckets like `src`, `tests`, `docs`, `(root)`).
- `csv/year_<period>_bootstraps_*.csv`
  - Bootstrap/import commits reported separately.
  - When bootstraps are excluded (default), these do not contribute to the main “excl_bootstraps” totals.
- `csv/repo_activity.csv`
  - One row per repo with per-period totals, useful for spotting “which repo dominated which year”.
- `csv/top_commits.csv`
  - Top 50 commits by churn across all analyzed repos/periods.
  - Includes bootstrap flag and basic commit metadata.

## `json/` (structured machine-readable outputs)

- `json/run_meta.json`
  - Captures the effective configuration for the run (periods, filters, excludes, dedupe mode, bootstrap thresholds, etc).
- `json/year_<period>_summary.json`
  - Period totals and breakdowns in a stable JSON shape (used by report renderers and publishers).
- `json/year_<period>_excluded.json`
  - Counts of excluded paths/lines (from `exclude_path_prefixes`/`exclude_path_globs`).
- `json/upload_package_v1.json` (only when publishing)
  - The gzipped canonical JSON payload that gets uploaded to the web backend.

## `timeseries/` (weekly totals for graphing)

- `timeseries/year_<period>_weekly.json`
  - Weekly time series totals (required).
  - Each weekly row also includes `technologies`: per-language stats for that week.
- `timeseries/year_<period>_me_timeseries.json` (only when `--detailed`)
- `timeseries/me_timeseries.json` (only when `--detailed`)

## `debug/` (why a repo was/wasn’t included)

- `debug/repo_selection.csv`: one row per discovered repo candidate and the include/exclude reason
- `debug/repo_selection_summary.json`: counts by include/exclude reason
- `debug/bootstraps_commits_<period>.json`: raw bootstrap detection details per period

