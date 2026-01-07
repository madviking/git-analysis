# Project Plan — Backend Support (LLM Git Inflection v1)

This is the execution plan for adding “upload package” + backend-support features to the `madviking/git-analysis` toolkit. It is derived from the original spec and tracks progress.

## Decisions / Constraints
- Datastore is **MySQL** (toolkit remains datastore-agnostic).
- Metrics resolution is **weekly** (required).
- No OAuth; identity is **user-provided**.
- “Verified” badge only possible when user opts into exposing **public repo URLs** (host-specific; GitHub first).
- Uploads are **replace** semantics (newest upload becomes active snapshot).

## Goals / Non-goals
- Goals: deterministic/auditable JSON output; weekly time series; user-controlled privacy; minimal ops complexity.
- Non-goals: prevent fabrication; OAuth/auto-verification; GitHub-only analysis (verification can be host-specific).
- Only author's own stats get sent to backend, no statistics for other authors

---

## Milestone 0 — Maintainability (start here)
- [x] Split `analyze.py` into modules (keep files <500 LOC where practical).
- [x] Add pytest-based unit tests and a minimal test suite.

**Progress notes**
- Refactor completed: `src/git_analysis/analyze.py` is now a thin re-export; new modules live under `src/git_analysis/analysis_*.py`.
- Tests added under `tests/` and run via `uv sync --group dev && .venv/bin/python -m pytest`.

---

## Milestone 1 — Output organization (reports folder structure)
Target organization (under each `reports/<run-type>/<timestamp>/`):
- Markup files at the root (e.g. `.md`, `.txt`)
- `json/` for JSON aggregates and metadata
- `csv/` for CSV exports
- `timeseries/` for time series JSON
- `debug/` for selection/debug artifacts

Work items:
- [x] Define the exact mapping of existing outputs to subfolders.
- [x] Update writers to emit to the new structure (and keep `reports/latest.txt` behavior).
- [x] Update `git-analysis-validate` expectations (if needed).
- [x] Update `README.md` “Output files” section.

**Mapping (current)**
- Root (markup):
  - `year_in_review_<YYYY>.txt` / `period_in_review_<period>.txt`
  - `year_in_review_<YYYY0>_vs_<YYYY1>.txt` / `period_in_review_<p0>_vs_<p1>.txt` (when comparing)
  - `comparison_<p0>_vs_<p1>.txt` (when comparing)
  - `llm_inflection_stats.txt` (when `upload_config.llm_coding.dominant_at` is set)
- `markup/`:
  - `year_in_review_*.md`
  - `period_in_review_*.md`
  - `comparison_<p0>_vs_<p1>.md` (when comparing)
  - `llm_inflection_stats.md` (when `upload_config.llm_coding.dominant_at` is set)
- `json/`:
  - `year_<period>_summary.json`
  - `year_<period>_excluded.json`
  - `run_meta.json`
  - `upload_package_v1.json` (only when publishing)
- `csv/`:
  - `year_<period>_repos.csv`
  - `year_<period>_authors.csv`
  - `year_<period>_languages.csv`
  - `year_<period>_dirs.csv`
  - `year_<period>_bootstraps_*.csv`
  - `repo_activity.csv`
- `timeseries/`:
  - `year_<period>_weekly.json` (weekly totals)
  - `year_<period>_me_timeseries.json` (only when `--detailed`)
  - `me_timeseries.json` (only when `--detailed`)
- `debug/`:
  - `repo_selection.csv`
  - `repo_selection_summary.json`

---

## Milestone 2 — CLI improvements (comparison UX)
Work items:
- [x] Implement the requested “improved comparison” input format.
  - Current: `--halves 2025` or `--periods 2025H1 2025H2`
  - Implemented: `parse_period()` accepts both `YYYYH1` and `H1YYYY` (same for `H2`).
  - Implemented: `--periods` accepts comma-separated values (e.g. `--periods H12025,H12026`).
  - Implemented: `--halves` accepts a year (`2025`) or one/two explicit half specs (e.g. `--halves H12025,H12026`).
- [x] Add tests for the new parsing behavior.
- [x] Update `README.md` examples.

---

## Milestone 3 — Repo support (host-agnostic + privacy-aware identifiers)
Work items:
- [x] Ensure per-repo collection includes (at least): `repo_key`, `remote_canonical` (optional), and optionally local `path`.
- [x] Define stable `repo_key` (recommended: `sha256(remote_canonical)` else `sha256(abs_path)`).
- [x] Ensure repo inclusion works across hosts (GitHub/GitLab/Bitbucket/self-hosted/local-only).

**Implementation notes**
- `repo_key` is `sha256(dedupe_key)` where `dedupe_key` is `remote_canonical` for `--dedupe remote` (when available), otherwise the repo’s absolute path.

---

## Milestone 4 — Weekly metrics output (required)
Week definition:
- Bucket by week start `00:00:00Z` Monday (ISO semantics).
- Use author time (`%aI`) converted to UTC before bucketing (deterministic).

Work items:
- [x] Add weekly aggregation across all scanned repos.
- [x] Required counters: `commits`, `insertions`, `deletions`, `changed`.
- [x] Recommended counters (if we keep “me” + bootstraps): bootstraps splits are included (`excl_bootstraps` / `bootstraps` / `including_bootstraps`).
- [x] Persist weekly time series into the output package structure (`timeseries/`).
- [x] Add unit tests for week bucketing and UTC normalization.

---

## Milestone 5 — Publish wizard (required UX)
At run start, prompt:
1) “Publish results to the public site?” (yes/no)
2) Display identity (public): pseudonym (default) or GitHub username (optional; not verified)
3) Repo URL privacy mode: `none` | `public_only` | `all`

Work items:
- [x] Add interactive prompts (and non-interactive overrides for automation).
- [x] Add privacy rules enforcement for which repo URLs appear in the upload package.
- [x] Define “verification_opt_in” behavior and constraints.

**Notes**
- Publishing prompt is always shown; saved values are reused as defaults.
- CLI flags (defaults/overrides): `--publish {no,yes,ask}`, `--publisher`, `--repo-url-privacy`, `--publisher-token-path`, `--upload-url` (overrides `upload_config.api_url`).
- Wizard answers are persisted in `config.json` under `upload_config.*`.
- `verification_opt_in` is set automatically when `repo-url-privacy` is `public_only` or `all`.

---

## Milestone 6 — Upload package format (v1)
Work items:
- [x] Define the exact JSON schema for `upload_package_v1` (lock fields + types).
- [x] Include: `schema_version`, `generated_at`, toolkit version, `publisher`, `privacy`, `repos`, `weekly`.
- [x] Ensure deterministic JSON bytes for hashing (stable ordering, encoding).

**Schema (current)**
- Top-level: `schema_version`, `generated_at`, `toolkit_version`, `publisher`, `privacy`, `periods`, `repos`, `weekly`
- Deterministic bytes: canonical JSON (`sort_keys=true`, `separators=(",", ":")`, UTF-8)

---

## Milestone 7 — Publisher identity + replace semantics (no OAuth)
Work items:
- [x] Generate and store a local `publisher_token` (shared secret) on first publish.
- [x] Send token via header (e.g. `X-Publisher-Token`); backend stores only a hash.
- [x] Define local storage location + failure behavior if missing/unreadable.

**Defaults**
- Token path default: `~/.config/git-analysis/publisher_token` (override with `--publisher-token-path`).

---

## Milestone 8 — Payload preview (mandatory)
Work items:
- [x] Pretty-print the payload preview with token redaction (`publisher_token_hint` only).
- [x] Compute and display payload SHA-256 (uncompressed JSON bytes).
- [x] Show repo URL mode and which repos would be exposed publicly.
- [x] Require explicit confirmation before upload.

---

## Milestone 9 — Upload transport (backend coordination)
Work items:
- [x] Gzip-compress JSON and `POST /api/v1/uploads`.
- [x] Send headers: `Content-Encoding: gzip`, `X-Publisher-Token`, `X-Payload-SHA256`.
- [x] Handle responses: `201`, `400`, optional `409`.

**Server destination**
- Base URL is stored in `config.json` as `upload_config.api_url` and the client uploads to `${api_url}/api/v1/uploads`.

---

## Milestone 10 — Failure modes (required)
Work items:
- [x] Fail loudly on network failure, non-2xx response, or local token issues when publishing.
- [x] No silent retries; surface actionable error messages.
