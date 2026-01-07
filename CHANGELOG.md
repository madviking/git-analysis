# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows SemVer where applicable.

## [Unreleased]

### Fixed
- Prevent `git log` deadlocks by draining stderr while streaming stdout (fixes analysis runs hanging near completion).

### Added
- Auto-bootstrap config creation from `config-template.json` when `--config` is missing, with inferred identity and scanned repo remote prefixes, then prompt to review/edit before continuing.
- `excluded_repos` (glob patterns) to skip specific repos by path during discovery/selection.
- LLM tooling metadata collection in the publish wizard (inflection points + standardized tool enums) and include it in `upload_package_v1` as `llm_coding`.
- Startup ASCII header describing what the run will do and where outputs are written.
- `llm_inflection_stats` comparison report based on `upload_config.llm_coding.dominant_at`.

### Changed
- Upload/publish defaults now persist under `config.json` → `upload_config.*` (backward-compatible read of legacy `publish` block remains).
- Upload destination now comes from `upload_config.api_url` (or `--upload-url`); legacy `server.json`/`server-config.json` are no longer used.
- Rendered percentages no longer include decimals (e.g. `+33%` instead of `+33.3%`).
- Expanded default exclusion lists in `config-template.json` for common build/cache directories and generated paths.
- When `upload_config` is already set up, the publish wizard skips re-prompting for setup values and reminds you to edit `config.json` instead.
- Comparison markdown is written to `reports/.../markup/` (root keeps `comparison_*.txt`).
- Unless `--include-bootstraps` is set, comparison reports only show the bootstrap-excluding view (no separate bootstraps/including tables).
- “In review” report naming now reflects non-year periods (e.g. `period_in_review_2025H1_vs_2025H2.*` instead of `year_in_review_...`).

## [0.1.0]

- Initial release.
