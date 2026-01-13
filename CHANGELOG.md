# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows SemVer where applicable.

## [Unreleased]

### Fixed
- Prevent `git log` deadlocks by draining stderr while streaming stdout (fixes analysis runs hanging near completion).
- Period boundaries now include commits on the start date (previously some start-day commits were incorrectly excluded).
- Bootstrap detection now also excludes deletion-dominant bulk commits (e.g. removing a large generated directory) when they meet the configured thresholds.
- Bootstrap detection now also catches extreme outliers (very large one-sided commits, or very large multi-file sweeps) even when they miss the standard “shape” thresholds.
- Graceful upload failures: HTTP errors no longer show Python tracebacks; payload path and retry hint are printed instead.
- Upload preview no longer prints the full JSON payload; it prints a summary and a file path, then prompts for confirmation.
- Upload now treats `HTTP 409` duplicate-payload responses as a successful no-op (idempotent retry).
- HTTPS uploads now auto-discover a CA trust store (including a macOS Keychain-derived cache when needed); private CAs can be supplied via `upload_config.ca_bundle_path` / `--ca-bundle`.
- GitHub verification 404 errors now provide a clearer hint when `upload_config.api_url` points at a web UI (HTML 404) instead of the API backend.
- GitHub verification now retries a localhost `api_url` with `port-1` when the configured `api_url` returns an HTML 404 (common UI/API split in local dev).
- GitHub verification now prints step-by-step instructions (SSH key, not GPG; Authentication key) when the backend reports the publisher key is not found on the GitHub user.
- GitHub verification instructions now explicitly note that the backend checks `https://api.github.com/users/<username>/keys` (so GitHub “Signing keys” won’t satisfy verification).

### Added
- Auto-bootstrap config creation from `config-template.json` when `--config` is missing, with inferred identity and scanned repo remote prefixes, then prompt to review/edit before continuing.
- `excluded_repos` (glob patterns) to skip specific repos by path during discovery/selection.
- LLM tooling metadata collection in the publish wizard (inflection points + standardized tool enums) and include it in `upload_package_v1` as `llm_coding`.
- Startup header prints a short run plan (config/root/periods/output/publish) before analysis starts.
- `llm_inflection_stats` comparison report based on `upload_config.llm_coding.dominant_at`.
- Weekly time series now includes per-week technology (language) breakdowns (`technologies` per week).
- Support updating the public profile display name via `POST /api/v1/me/display-name` (CLI: `./cli.sh display-name`, including `--pseudonym`).
- GitHub username verification (no OAuth) via `POST /api/v1/me/github/verify/challenge` + `.../confirm` (CLI: `./cli.sh github-verify`).
- Publish flow now optionally offers GitHub username verification after upload when your publish display name is a GitHub username (opt-in prompt).
- `docs/github-username-verification.md` and `docs/upload_package_v1_v7.json` for GitHub verification and upload-package reference.
- CLI prints each API request before sending it (URL + payload path for uploads, inline JSON for small requests).
- CLI explains publisher token creation (random local secret; not derived from SSH keys/private keys).
- Document `.venv/` usage for contributors/agents in `AGENTS.md`.
- `exclude_commits` config for excluding specific commit SHAs from stats, plus `csv/top_commits.csv` to help find large commits by churn.
- Codex skills for report triage and spike investigation under `skills/`.
- Upload payload weekly rows now include repo-concentration shares (`repo_activity_top1_share_changed`, `repo_activity_top3_share_changed`), plus upload-level nonzero-week counts (`weekly_nonzero_commits_weeks`, `weekly_nonzero_changed_weeks`).

### Changed
- Upload/publish defaults now persist under `config.json` → `upload_config.*` (backward-compatible read of legacy `publish` block remains).
- Upload destination now comes from `upload_config.api_url` (or `--upload-url`); legacy `server.json`/`server-config.json` are no longer used.
- Upload payload now contains only “me” stats, excludes bootstraps, excludes all repo identifiers/URLs, adds repo counts (`repos_total`, `repos_active`, `repos_new`) in `year_totals` and each weekly row, and prompts for which full years to upload (2025 always included).
- Upload payload `publisher` now includes `public_key` (OpenSSH `ssh-ed25519 <base64>`) for GitHub verification.
- `github-verify` no longer requires `--username`; it defaults to the first `me_github_usernames[]` entry in `config.json` when present.
- Rendered percentages no longer include decimals (e.g. `+33%` instead of `+33.3%`).
- Report `.txt`/`.md` outputs abbreviate large numbers (e.g. `1K`, `2.5M`) including large percentage deltas.
- Expanded default exclusion lists in `config-template.json` for common build/cache directories and generated paths.
- When `upload_config` is already set up, the publish wizard skips re-prompting for setup values and reminds you to edit `config.json` instead.
- Comparison markdown is written to `reports/.../markup/` (root keeps `comparison_*.txt`).
- Unless `--include-bootstraps` is set, comparison reports only show the bootstrap-excluding view (no separate bootstraps/including tables).
- “In review” report naming now reflects non-year periods (e.g. `period_in_review_2025H1_vs_2025H2.*` instead of `year_in_review_...`).
- README now links directly to `docs/` pages (configuration, output, publishing, payload, development).
- README includes Web UI screenshots for uploaded stats.

## [0.1.0]

- Initial release.
