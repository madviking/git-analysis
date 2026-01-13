# CLI

Run via `./cli.sh ...` (recommended) or `python -m git_analysis ...`.

## Common
- `--root PATH`: directory to scan for repos (default `..`)
- `--years 2024 2025`: analyze full calendar years
- `--periods 2025H1 2025H2`: analyze arbitrary named periods (`YYYY`, `YYYYH1`/`H1YYYY`, `YYYYH2`/`H2YYYY`)
- `--halves 2025`: shortcut for `2025H1` vs `2025H2` (also supports `--halves H12025,H12026`)
- `--jobs N`: parallel workers for `git` calls
- `--max-repos N`: analyze only the first N unique repos (useful for trial runs)

## Behavior
- `--dedupe remote|path`: dedupe repos by canonical remote URL (default) or treat each clone separately
- `--include-merges`: include merge commits (default excludes merges)
- `--include-bootstraps`: include detected bootstrap/import commits in the main stats (default excludes)
- `--detailed`: write extra JSON for graphing (“me” monthly totals + per-technology)

## Examples

Two years (and get a comparison report):

```bash
./cli.sh --root .. --years 2024 2025
```

First vs second half of a year:

```bash
./cli.sh --root .. --halves 2025
```

Custom periods:

```bash
./cli.sh --root .. --periods 2025H2 2026H1
```

More output for graphing:

```bash
./cli.sh --root .. --years 2024 2025 --detailed
```

