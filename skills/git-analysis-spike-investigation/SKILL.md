---
name: git-analysis-spike-investigation
description: Investigate activity spikes in a git-analysis report by locating the exact commits that caused them and deciding whether to exclude them (bootstrap/outlier/path exclusions).
---

# Git Analysis Spike Investigation

Use this when a `reports/...` activity graph shows suspicious spikes and you want to identify the exact commits and decide whether they should be filtered.

## Inputs

- A report directory, e.g. `reports/years_2024_2025_2026/2026-01-11_12-05-40`
- Local clones still present at the `repo_path` values recorded in `csv/repo_activity.csv`

## Workflow

1. Find peak weeks in the report:
   - `python skills/git-analysis-spike-investigation/scripts/explain_spikes.py top-weeks --report-dir <REPORT_DIR> --year 2024 --series excl_bootstraps --n 10`
2. Explain a specific week (lists top commits by changed lines, after exclusions):
   - `python skills/git-analysis-spike-investigation/scripts/explain_spikes.py explain-week --report-dir <REPORT_DIR> --week-start 2024-01-22 --view non_bootstraps --limit 25`
3. Inspect a suspicious commit in the source repo:
   - `git -C <repo_path> show --numstat --format='%H %aI %s' <sha> | head -n 60`

- For the investigated report in this thread, see `skills/git-analysis-spike-investigation/references/fishy_2026-01-11_report.md`.

## Filtering decision guide

- **Likely exclude (filter out)**:
  - Large snapshot imports (e.g. many HTML/JSON dumps under a `files/` or `import/` directory).
  - “All files in place” style imports/moves touching thousands of files.
  - Large generated artifacts that aren’t already covered by `exclude_path_globs` (lockfiles, API dumps, generated schemas).
- **Likely keep**:
  - Large but intentional refactors where churn is real engineering work (esp. multi-week patterns).
  - Large docs overhauls if you want docs counted.

### Ways to exclude

- Prefer **path exclusions** when the churn comes from a specific directory (update the config’s `exclude_path_globs` / `exclude_path_prefixes`).
- Prefer **bootstrap detection** tweaks when the churn is a commit-shape outlier (huge sweep, huge one-sided).
- Use `bootstrap_exclude_shas` only for one-off exceptions.
