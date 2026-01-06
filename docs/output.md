# Output structure

Reports are written under `reports/<run-type>/<timestamp>/`. `reports/latest.txt` points to the most recent run directory.

Within a run directory:

## Root (markup)
- `year_in_review_<period>.txt`
- `year_in_review_<p0>_vs_<p1>.txt` (only when comparing exactly 2 periods)
- `comparison_<p0>_vs_<p1>.md` (only when comparing exactly 2 periods)

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

