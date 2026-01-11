## Report

- `reports/years_2024_2025_2026/2026-01-11_12-05-40`
- Run config: `bootstrap_changed_threshold=50000`, `bootstrap_files_threshold=200`, `bootstrap_addition_ratio=0.9`

## Main “fishy” outliers (not detected as bootstraps with the old rules)

These dominated weekly activity while being mostly snapshot/data dumps (HTML/JSON), but missed bootstrap detection due to `files_touched < 200` or a non-one-sided ratio.

### 2024-01-15 week

- `github.com/east-interactive/yeast-analyst` `168a0f63` “parser & updater wip” (`~597k` insertions; many `app/files/import/html/*.html` snapshots)

### 2024-01-22 week

- `github.com/east-interactive/yeast-analyst` `80c2614e` “more data and fixes” (`~1.0M` insertions; many `app/files/import/html/*.html` snapshots)
- `github.com/east-interactive/yeast-analyst` `7c461c4f` “more data” (`~132k` insertions; same snapshot directory)

### 2024-03-25 week

- `github.com/east-interactive/yeast-analyst` `df9b5c1a` “wip - with sample data” (`~463k` changed; large `src/app/files/dictionaries/*` snapshots)

### 2024-03-11 week

- `github.com/east-interactive/appzio` `e97e3c91` “all files in place” (`~299k` changed; huge multi-file import/move; not one-sided enough for the old `addition_ratio`)

## Filtering recommendation

- Prefer excluding these from the main totals:
  - Either by adding repo-specific `exclude_path_globs` for snapshot directories (`**/files/import/**`, `**/files/dictionaries/**`, etc.)
  - Or by improving bootstrap detection for extreme outliers (huge one-sided commits and huge multi-file sweeps).
