# git-analysis

Yearly Git statistics (2024/2025 by default) across many local repositories under a directory tree.

The script is **read-only**: it uses only the Python standard library and shells out to `git` via subprocess.

## What it produces

For each analyzed year:
- Totals: commits, insertions, deletions, changed lines (total / “me” / others)
- Per-repo CSV
- Per-author CSV
- Per-language CSV (based on file extension)
- (Optional) Monthly JSON time series for “me” (`--detailed`)
- ASCII “Year in Review” report (`.txt`)

When exactly two years are requested, it also produces a side-by-side comparison including **Δ and Δ%** (and language tables).

All output files go to `git-analysis/reports/`.

## Requirements

- Python 3.11+
- Git available on PATH
- (Recommended) `uv` for `./cli.sh`

## Quick start

```bash
cd git-analysis
brew install uv  # or follow https://docs.astral.sh/uv/
cp config.example.json config.json
./cli.sh --root .. --years 2024 2025
```
Reports are written under `reports/<run-type>/<timestamp>/` and `reports/latest.txt` points to the most recent run directory.

## Development

Run tests:

```bash
uv sync --group dev
.venv/bin/python -m pytest
```

## Configuration (`config.json`)

Start from `config.example.json`.

### Identify “me”

- `me_emails`: list of emails considered “me” (recommended)
- `me_names`: list of author names considered “me” (optional)
- `me_email_globs`: optional globs matched against author emails (after lowercasing), e.g. `["*@users.noreply.github.com"]`
- `me_name_globs`: optional globs matched against author names (case-insensitive)
- `me_github_usernames`: GitHub username(s) used to match `*@users.noreply.github.com` emails, e.g. `["trailo"]`

If `config.json` is missing, the script tries to infer `user.email` and `user.name` from global git config.

### Choose which repos are included

- `include_remote_prefixes`: only include repos whose `remote.origin.url` matches one of these prefixes.
  - Handles both `https://github.com/org/repo` and `git@github.com:org/repo` styles.
- `remote_name_priority`: when multiple remotes exist (common for forks), prefer these remotes for identifying/deduping the repo (default `["origin","upstream"]`).
- `remote_filter_mode`:
  - `"any"` (default): include a repo if **any** remote matches `include_remote_prefixes` (helps when `origin` is a fork but `upstream` is the org repo).
  - `"primary"`: include a repo only if the **selected** remote matches.
- `exclude_forks`: heuristic exclusion for forks (default `false` unless you set it).
- `fork_remote_names`: which remote names indicate a fork parent (default `["upstream"]`); if present and it points to a different repo than `origin`, the repo is treated as a fork.

### Exclude vendored / generated files (recommended)

These affect **line counts** and **language breakdowns**.

- `exclude_path_prefixes`: quick prefix-based skips (e.g. `vendor/`, `node_modules/`)
- `exclude_path_globs`: glob-based skips (e.g. `**/vendor/**`, `**/*.min.js`)

### Bootstraps / imports (recommended)

Large “bootstrap/import” commits (e.g. scaffolding a new framework project) can dominate year-over-year totals. The analyzer can detect these commits by their shape (huge churn, many files, mostly additions) and exclude them from the main stats by default.

Config:
- `bootstrap_changed_threshold`: minimum changed lines to be considered a bootstrap (default `50000`)
- `bootstrap_files_threshold`: minimum files touched to be considered a bootstrap (default `200`)
- `bootstrap_addition_ratio`: minimum `insertions/(insertions+deletions)` (default `0.9`)

CLI:
- `--include-bootstraps`: include detected bootstrap commits in the main stats (they are always reported separately too).

### Speed / traversal controls

- `exclude_dirnames`: directory names skipped during discovery (only affects scanning, not git history)

## CLI options

Common:
- `--root PATH`: directory to scan for repos (default `..`)
- `--years 2024 2025`: which years to compute
- `--periods 2025H1 2025H2`: analyze arbitrary periods (supports `YYYY`, `YYYYH1`, `YYYYH2`)
- `--halves 2025`: shortcut for `2025H1` vs `2025H2`
- `--jobs N`: parallel workers for `git` calls
- `--max-repos N`: analyze only the first N unique repos (good for trial runs)

Behavior:
- `--dedupe remote|path`: dedupe repos by canonical `remote.origin.url` (default) or treat each clone separately
- `--include-merges`: include merge commits (default excludes merges)
- `--include-bootstraps`: include detected bootstrap/import commits in the main stats (default excludes)
- `--detailed`: write extra JSON for graphing (“me” monthly totals + per-technology)

ASCII output:
- ASCII “Year in Review” reports are always generated to `reports/` (no flags required).
- Use `--halves 2025` (or `--periods 2025H1 2025H2`) to compare first vs second half of a year.

## Output files

- `reports/year_YYYY_summary.json`: aggregates + top authors + config used for that run
- `reports/year_YYYY_repos.csv`: per-repo totals (includes selected `remote_name`, `remote_canonical`, duplicates, first/last commit timestamps)
- `reports/year_YYYY_authors.csv`: per-author totals
- `reports/year_YYYY_languages.csv`: per-language totals (by file extension)
- `reports/year_YYYY_bootstraps_commits.csv`: detected bootstrap commits (per-commit totals)
- `reports/year_YYYY_bootstraps_authors.csv`: author totals for bootstrap commits only
- `reports/year_YYYY_bootstraps_languages.csv`: language totals for bootstrap commits only
- `reports/year_YYYY_bootstraps_dirs.csv`: directory totals for bootstrap commits only
- `reports/comparison_YYYY_vs_YYYY.md`: side-by-side report with Δ and Δ% (only when 2 years are provided)
- `reports/year_in_review_YYYY.txt`: ASCII “Year in Review” for that year
- `reports/year_in_review_YYYY_vs_YYYY.txt`: ASCII year-over-year “Year in Review” (only when 2 years are provided)
- `reports/repo_selection.csv`: debug list of discovered repos and why included/skipped/duplicated
- `reports/repo_activity.csv`: per-repo activity across the requested years (excl bootstraps / bootstraps / incl bootstraps)
- `reports/run_meta.json`: metadata about the run
- `reports/year_<period>_me_timeseries.json`: (when `--detailed`) “me” monthly totals + per-technology (language) rows
- `reports/me_timeseries.json`: (when `--detailed`) all requested periods in one JSON

## Important notes (accuracy)

- **Branches/remotes**: stats are computed over *all refs* (`git log --all`), so local branches and remote-tracking branches in that clone are included.
- **Repo identity / forks**: repo identity is based on a selected remote URL (see `remote_name_priority`); this helps treat forks and upstream remotes consistently.
- **Duplicate clones**: with `--dedupe remote`, the script prefers the clone with the **newest reachable commit** to reduce undercounting caused by stale clones.
- **Submodules**: submodules are separate repos and are included/excluded like any other repo based on their `remote.origin.url`.
- **Language breakdown**: language is inferred from the path in `git log --numstat` (extension + a few special filenames), so it’s approximate.

## Troubleshooting

- Totals look too low: you may be analyzing a stale clone; rerun with the updated dedupe behavior (default) or use `--dedupe path` to compare.
- Totals look too high: add/expand `exclude_path_prefixes` and `exclude_path_globs` to avoid counting vendored/minified/generated code.
- YoY looks “impossible” (e.g. huge drop): confirm you didn’t run with `--max-repos`, then inspect the debug reports below to see which repos were included/excluded.

## Debug reports (what’s missing?)

These files help explain why a repo did or didn’t make it into the analysis:

- `reports/repo_selection.csv`: one row per discovered candidate repo with `status` and `reason` (e.g. `remote_filter_no_match`, `no_remotes`, `duplicate`)
- `reports/repo_selection_summary.json`: counts by status/reason
- `reports/repo_activity.csv`: per-repo activity across the requested years (excl bootstraps / bootstraps / incl bootstraps)
- `reports/year_YYYY_dirs.csv`: directory-level churn (top-level directory like `src`, `tests`, `docs`, `(root)`)
- `reports/year_YYYY_excluded.json`: how many lines/files were skipped by `exclude_path_prefixes`/`exclude_path_globs`

## Validate reports

Quick consistency check (language totals vs aggregate totals):

```bash
python -m git_analysis.validate_reports --reports reports --years 2024 2025
```
