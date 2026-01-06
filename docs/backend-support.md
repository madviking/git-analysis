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
- [ ] Define the exact mapping of existing outputs to subfolders.
- [ ] Update writers to emit to the new structure (and keep `reports/latest.txt` behavior).
- [ ] Update `git-analysis-validate` expectations (if needed).
- [ ] Update `README.md` “Output files” section.

---

## Milestone 2 — CLI improvements (comparison UX)
Work items:
- [ ] Implement the requested “improved comparison” input format.
  - Current: `--halves 2025` or `--periods 2025H1 2025H2`
  - Requested example: `--halves H12025,H12026` (confirm final syntax and whether it’s a new flag or enhanced parsing).
- [ ] Add tests for the new parsing behavior.
- [ ] Update `README.md` examples.

---

## Milestone 3 — Repo support (host-agnostic + privacy-aware identifiers)
Work items:
- [ ] Ensure per-repo collection includes (at least): `repo_key`, `remote_canonical` (optional), and optionally local `path`.
- [ ] Define stable `repo_key` (recommended: `sha256(remote_canonical)` else `sha256(abs_path)`).
- [ ] Ensure repo inclusion works across hosts (GitHub/GitLab/Bitbucket/self-hosted/local-only).

---

## Milestone 4 — Weekly metrics output (required)
Week definition:
- Bucket by week start `00:00:00Z` Monday (ISO semantics).
- Use author time (`%aI`) converted to UTC before bucketing (deterministic).

Work items:
- [ ] Add weekly aggregation across all scanned repos.
- [ ] Required counters: `commits`, `insertions`, `deletions`, `changed`.
- [ ] Recommended counters (if we keep “me” + bootstraps): `*_me` and bootstraps splits (keep schema simple for v1).
- [ ] Persist weekly time series into the output package structure (`timeseries/`).
- [ ] Add unit tests for week bucketing and UTC normalization.

---

## Milestone 5 — Publish wizard (required UX)
At run start, prompt:
1) “Publish results to the public site?” (yes/no)
2) Display identity (public): pseudonym (default) or GitHub username (optional; not verified)
3) Repo URL privacy mode: `none` | `public_only` | `all`

Work items:
- [ ] Add interactive prompts (and non-interactive overrides for automation).
- [ ] Add privacy rules enforcement for which repo URLs appear in the upload package.
- [ ] Define “verification_opt_in” behavior and constraints.

---

## Milestone 6 — Upload package format (v1)
Work items:
- [ ] Define the exact JSON schema for `upload_package_v1` (lock fields + types).
- [ ] Include: `schema_version`, `generated_at`, toolkit version, `publisher`, `privacy`, `repos`, `weekly`.
- [ ] Ensure deterministic JSON bytes for hashing (stable ordering, encoding).

---

## Milestone 7 — Publisher identity + replace semantics (no OAuth)
Work items:
- [ ] Generate and store a local `publisher_token` (shared secret) on first publish.
- [ ] Send token via header (e.g. `X-Publisher-Token`); backend stores only a hash.
- [ ] Define local storage location + failure behavior if missing/unreadable.

---

## Milestone 8 — Payload preview (mandatory)
Work items:
- [ ] Pretty-print the payload preview with token redaction (`publisher_token_hint` only).
- [ ] Compute and display payload SHA-256 (uncompressed JSON bytes).
- [ ] Show repo URL mode and which repos would be exposed publicly.
- [ ] Require explicit confirmation before upload.

---

## Milestone 9 — Upload transport (backend coordination)
Work items:
- [ ] Gzip-compress JSON and `POST /api/v1/uploads`.
- [ ] Send headers: `Content-Encoding: gzip`, `X-Publisher-Token`, `X-Payload-SHA256`.
- [ ] Handle responses: `201`, `400`, optional `409`.

---

## Milestone 10 — Failure modes (required)
Work items:
- [ ] Fail loudly on network failure, non-2xx response, or local token issues when publishing.
- [ ] No silent retries; surface actionable error messages.
