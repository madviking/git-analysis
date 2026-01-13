# Accuracy and troubleshooting

## Important notes (accuracy)

- **Branches/remotes**: stats are computed over *all refs* (`git log --all`), so local branches and remote-tracking branches in that clone are included.
- **Repo identity / forks**: repo identity is based on a selected remote URL (see `remote_name_priority` in `config.json`); this helps treat forks and upstream remotes consistently.
- **Duplicate clones**: with `--dedupe remote`, the tool prefers the clone with the **newest reachable commit** to reduce undercounting caused by stale clones.
- **Submodules**: submodules are separate repos and are included/excluded like any other repo based on their `remote.origin.url`.
- **Language breakdown**: language is inferred from paths in `git log --numstat` (extension + a few special filenames), so it’s approximate.

## Troubleshooting

- Totals look too low: you may be analyzing a stale clone; rerun with default dedupe behavior or use `--dedupe path` to compare.
- Totals look too high: add/expand `exclude_path_prefixes` and `exclude_path_globs` to avoid counting vendored/minified/generated code.
- YoY looks “impossible” (e.g. huge drop): confirm you didn’t run with `--max-repos`, then inspect the debug reports below to see which repos were included/excluded.
- Upload fails with `CERTIFICATE_VERIFY_FAILED`: try `--ca-bundle /path/to/ca.pem` (or `upload_config.ca_bundle_path`). On macOS with python.org Python, `Install Certificates.command` can also fix the global Python CA bundle.

## Debug reports (what’s missing?)

These files help explain why a repo did or didn’t make it into the analysis:

- `debug/repo_selection.csv`: one row per discovered candidate repo with `status` and `reason` (e.g. `remote_filter_no_match`, `no_remotes`, `duplicate`)
- `debug/repo_selection_summary.json`: counts by status/reason
- `csv/repo_activity.csv`: per-repo activity across the requested periods (excl bootstraps / bootstraps / incl bootstraps)
- `csv/year_<period>_dirs.csv`: directory-level churn (top-level directory like `src`, `tests`, `docs`, `(root)`)
- `json/year_<period>_excluded.json`: how many lines/files were skipped by `exclude_path_prefixes`/`exclude_path_globs`

## Validate reports

Quick consistency check (language totals vs aggregate totals):

```bash
python -m git_analysis.validate_reports --reports reports --years 2024 2025
```

