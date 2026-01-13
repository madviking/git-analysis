# Toolkit Data Collection Brief — Adoption Rating (v1)

Audience: the `madviking/git-analysis` (data collector) team.

Purpose: identify **optional, additive** data we can collect locally while scanning repos to make the **LLM Adoption Rating** and the **embed delta** less confounded and more credible, without changing our privacy stance (repo-free uploads, no repo identifiers/URLs).

This document is intentionally written as a “brief” that can be handed to a separate team.

---

## Background (current state)

The web service computes an LLM Adoption Rating anchored on a user-reported 90% point (`llm_coding.dominant_at`) and observed changes in weekly Git activity.

Current upload data includes (already supported by backend):
- Weekly aggregates: `commits`, `insertions`, `deletions`, `changed`, `repos_active`, `repos_new`
- Weekly technology distribution: list of `{technology, commits, insertions, deletions, changed}`
- Notes: toolkit already filters many artifacts/framework outputs and “bootstrap type” commits.

Even with current filtering, two major confounders remain:
1) **Artifact churn and generated files** can still dominate “changed lines” despite best-effort rules.
2) **Breadth and persistence** are hard to attribute without “surface area” measures (files touched, spread across repos) and without knowing whether activity is concentrated in one repo/week.

---

## Guiding constraints

### Privacy
- Payload must remain **repo-free**: no repo names, URLs, or stable identifiers.
- Do not upload commit messages or file paths.

### Backward compatibility
- Additive fields only; old backend versions should ignore unknown fields.

### Cost
- Prefer metrics that can be computed from diff stats already being collected (avoid heavy AST parsing).

---

## Proposed additions (recommended)

### 1) “Changed lines excluding generated/artifacts” (high impact)

Add weekly fields that represent line changes after applying stricter generated/artifact filters.

Rationale:
- Our delta metric and rating currently rely on `changed`, which can be biased by lockfiles, minified bundles, build outputs, vendored code, and huge JSON dumps.
- Even if the toolkit already filters “heavily”, having an explicit `changed_excluding_generated` gives us:
  - better robustness
  - auditability (we can show both numbers)
  - easier iteration on filters without breaking older analytics

Suggested weekly fields:
- `changed_excluding_generated`
- `insertions_excluding_generated`
- `deletions_excluding_generated`

Implementation guidance (toolkit-side):
- Apply heuristics based on paths and extensions (without uploading the paths):
  - `dist/`, `build/`, `.next/`, `vendor/`, `node_modules/` (if included), `coverage/`
  - `*.min.js`, `*.map`
  - lockfiles: `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `Cargo.lock`, `Gemfile.lock`, etc.
- Keep the rule set in one place in the toolkit and version it (include a filter version string in the payload if feasible).

---

### 2) Weekly “surface area” metrics (files touched) (high impact)

Add weekly fields describing how broad the changes are, independent of LOC.

Rationale:
- LLM adoption often increases throughput and breadth: more small edits across many files.
- LOC is noisy; “files touched” is often more stable and interpretable.

Suggested weekly fields:
- `files_changed_total` (sum of files changed across commits, or unique files touched in the week)
- `unique_files_touched` (preferred: unique count)
- `new_files` (count)
- `deleted_files` (count)
- `renamed_files` (count)

Notes:
- These can be computed locally without uploading file names.
- If unique counting is expensive, `files_changed_total` alone still helps.

---

### 3) Repo concentration without repo identifiers (medium/high impact)

We need to know whether post-dominance activity is broad across repos or concentrated in one.

Rationale:
- A single active project can create a big jump that looks like “LLM adoption” but is just project-specific.
- We can’t send repo identifiers, but we can send *concentration stats*.

Suggested weekly fields (repo-free):
- `repo_activity_top1_share_changed`: fraction of changed lines in the top repo that week (0..1)
- `repo_activity_top3_share_changed`: fraction of changed lines in the top 3 repos that week (0..1)
- `repos_active` already exists; these concentration stats complement it.

Tooling approach:
- Compute per-repo changed totals locally, then only emit the shares, not the repo IDs.

---

### 4) “Non-zero activity weeks” metadata (low/medium impact)

Provide summary metadata that helps confidence calculations without scanning everything on the server.

Suggested upload-level fields:
- `weekly_nonzero_commits_weeks`
- `weekly_nonzero_changed_weeks`

Optional:
- `active_week_thresholds`: the p25 used locally (for debugging consistency between toolkit and backend, if we ever align them)

---

## Optional additions (nice-to-have / sensitive)

### A) AI tool evidence from git trailers (sensitive, optional)

Some tools add trailers like `Co-authored-by: GitHub Copilot`.

If and only if we can do this safely:
- Do not upload raw commit messages.
- Only upload **counts** per week, e.g.:
  - `commits_with_ai_trailer_count`
  - `ai_trailer_kind_counts` (small fixed set; no free text)

This would make “LLM adoption” less inferential, but it is sensitive and might be skipped entirely.

---

## Proposed payload shape (additive example)

This is illustrative only; exact integration should follow `docs/openapi.yaml` once we decide to accept these fields.

Per week object:
```json
{
  "week_start": "2025-06-09T00:00:00Z",
  "commits": 61,
  "insertions": 57587,
  "deletions": 21354,
  "changed": 78941,
  "changed_excluding_generated": 51234,
  "insertions_excluding_generated": 40111,
  "deletions_excluding_generated": 11123,
  "unique_files_touched": 84,
  "new_files": 5,
  "deleted_files": 1,
  "renamed_files": 2,
  "repo_activity_top1_share_changed": 0.62,
  "repo_activity_top3_share_changed": 0.88,
  "repos_active": 4,
  "repos_new": 0,
  "technologies": [ { "technology": "TypeScript", "changed": 1200, "commits": 7 } ]
}
```

---

## Acceptance criteria (for the collector team)

- Adds the recommended fields with deterministic computation.
- Keeps uploads repo-free and does not leak file paths or commit messages.
- Keeps the schema backward compatible (fields optional; old backend can ignore).
- Provides a clear local “what got excluded” filter definition in the toolkit docs, ideally with a version identifier.

---

## Implementation checklist (handoff)

### Done
- [x] Document the brief (`docs/TOOLKIT_ADOPTION_RATING_DATA_BRIEF.md`)

### Not done yet
- [ ] Decide which of the proposed fields we actually want in `upload_package_v1` (and whether to bump schema version)
- [ ] Update `docs/openapi.yaml` and backend ingest validators to accept the new fields (additive)
- [ ] Implement toolkit collection + filtering changes
- [ ] Add/extend integration tests using updated upload fixtures

