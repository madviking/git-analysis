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
./cli.sh --root .. --years 2024 2025
```
Reports are written under `reports/<run-type>/<timestamp>/` and `reports/latest.txt` points to the most recent run directory.

## Documentation

Start here: `docs/index.md`.

## Publishing (upload wizard)

Every run prompts whether to publish results. The first time you publish, the wizard collects/saves upload defaults to `config.json` under `upload_config.*`.
Once `upload_config` is set up, the wizard no longer asks you to click through all selections; update settings by editing `config.json`.

Publishing is what enables public stats pages (LLM tools proficiency summary, leaderboards/top lists, and commit/churn graphs).

Server destination is configured in `config.json` under `upload_config.api_url` (or override with `--upload-url`).

## Development

Run tests:

```bash
uv sync --group dev
.venv/bin/python -m pytest
```

## Configuration (`config.json`)

Start from `config-template.json` or let the tool generate `config.json` if missing.

### Identify “me”

- `me_emails`: list of emails considered “me” (recommended)
- `me_names`: list of author names considered “me” (optional)
- `me_email_globs`: optional globs matched against author emails (after lowercasing), e.g. `["*@users.noreply.github.com"]`
- `me_name_globs`: optional globs matched against author names (case-insensitive)
- `me_github_usernames`: GitHub username(s) used to match `*@users.noreply.github.com` emails, e.g. `["trailo"]`

If `config.json` is missing, the script tries to infer `user.email` and `user.name` from global git config.
If `config.json` is missing, it is created from `config-template.json`, pre-filled with inferred identity + scanned repo remotes, then you’re prompted to review/edit before analysis continues.

### Choose which repos are included

- `include_remote_prefixes`: only include repos whose `remote.origin.url` matches one of these prefixes.
  - Handles both `https://github.com/org/repo` and `git@github.com:org/repo` styles.
- `excluded_repos`: glob patterns to skip specific repo paths under `--root` (e.g. `["**/archive/**", "**/mirror/**"]`).
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
- `--periods 2025H1 2025H2`: analyze arbitrary periods (supports `YYYY`, `YYYYH1`/`H1YYYY`, `YYYYH2`/`H2YYYY`)
- `--halves 2025`: shortcut for `2025H1` vs `2025H2` (also supports `--halves H12025,H12026`)
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

Reports are written under `reports/<run-type>/<timestamp>/` and `reports/latest.txt` points to the most recent run directory.

Within a run directory:
- Root: `year_in_review_<YYYY>.txt` / `period_in_review_<period>.txt`, `year_in_review_<YYYY0>_vs_<YYYY1>.txt` / `period_in_review_<p0>_vs_<p1>.txt`, `comparison_<p0>_vs_<p1>.txt`, `llm_inflection_stats.txt` (when configured)
- `markup/`: `year_in_review_*.md`, `period_in_review_*.md`, `comparison_<p0>_vs_<p1>.md`, `llm_inflection_stats.md` (when configured)
- `json/`: `year_<period>_summary.json`, `year_<period>_excluded.json`, `run_meta.json`
- `csv/`: `year_<period>_repos.csv`, `year_<period>_authors.csv`, `year_<period>_languages.csv`, `year_<period>_dirs.csv`, `year_<period>_bootstraps_*.csv`, `repo_activity.csv`
- `timeseries/`: `year_<period>_weekly.json`, plus (when `--detailed`) `year_<period>_me_timeseries.json` and `me_timeseries.json`
- `debug/`: `repo_selection.csv`, `repo_selection_summary.json`

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

- `debug/repo_selection.csv`: one row per discovered candidate repo with `status` and `reason` (e.g. `remote_filter_no_match`, `no_remotes`, `duplicate`)
- `debug/repo_selection_summary.json`: counts by status/reason
- `csv/repo_activity.csv`: per-repo activity across the requested years (excl bootstraps / bootstraps / incl bootstraps)
- `csv/year_YYYY_dirs.csv`: directory-level churn (top-level directory like `src`, `tests`, `docs`, `(root)`)
- `json/year_YYYY_excluded.json`: how many lines/files were skipped by `exclude_path_prefixes`/`exclude_path_globs`

## Validate reports

Quick consistency check (language totals vs aggregate totals):

```bash
python -m git_analysis.validate_reports --reports reports --years 2024 2025
```
