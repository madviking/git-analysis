# Output structure

Reports are written under `reports/<run-type>/<timestamp>/`. `reports/latest.txt` points to the most recent run directory.

Within a run directory:

## Root (markup)
- `year_in_review_<YYYY>.txt` (when the period label is a year)
- `period_in_review_<period>.txt` (when the period label is not a year, e.g. `2025H2`)
- `year_in_review_<YYYY0>_vs_<YYYY1>.txt` (only when comparing exactly 2 year periods)
- `period_in_review_<p0>_vs_<p1>.txt` (only when comparing exactly 2 non-year periods)
- `comparison_<p0>_vs_<p1>.txt` (only when comparing exactly 2 periods)
- `llm_inflection_stats.txt` (only when `upload_config.llm_coding.dominant_at` is set)

## `markup/`
- `year_in_review_*.md`
- `period_in_review_*.md`
- `comparison_<p0>_vs_<p1>.md` (only when comparing exactly 2 periods)
- `llm_inflection_stats.md` (only when `upload_config.llm_coding.dominant_at` is set)

## `json/`
- `year_<period>_summary.json`
- `year_<period>_excluded.json`
- `run_meta.json`
- `upload_package_v1.json` (only when publishing)

## `csv/`
- `year_<period>_repos.csv`
- `year_<period>_authors.csv`
- `year_<period>_languages.csv`
- `year_<period>_dirs.csv`
- `year_<period>_bootstraps_commits.csv`
- `year_<period>_bootstraps_authors.csv`
- `year_<period>_bootstraps_languages.csv`
- `year_<period>_bootstraps_dirs.csv`
- `repo_activity.csv`

## `timeseries/`
- `year_<period>_weekly.json` (weekly totals, required)
- `year_<period>_me_timeseries.json` (only when `--detailed`)
- `me_timeseries.json` (only when `--detailed`)

## `debug/`
- `repo_selection.csv`
- `repo_selection_summary.json`
