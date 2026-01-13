# Upload Payload (`upload_package_v1`)

This document defines the JSON payload uploaded to the backend (`POST /api/v1/uploads`).

The payload is:
- Deterministic JSON bytes (canonical JSON) for hashing and transport.
- **Me-only** (`data_scope: "me"`): upload includes only the user's own activity.
- **Repo-free**: no repo identifiers/URLs are included.
- **Bootstrap-excluding**: all uploaded time series exclude bootstraps/import commits.
- **Whole-year only**: uploads are always full calendar years (Jan 1 .. Jan 1); analysis reports may use different periods.

## Top-level object

- `schema_version` (string): `"upload_package_v1"`
- `generated_at` (string): UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`)
- `toolkit_version` (string): git-analysis version
- `data_scope` (string): `"me"`
- `repos_total` (int): number of repos analyzed in this run (after filtering/dedupe)
- `weekly_nonzero_commits_weeks` (int): number of weekly rows (across all uploaded periods) with `commits > 0`
- `weekly_nonzero_changed_weeks` (int): number of weekly rows (across all uploaded periods) with `changed > 0`
- `publisher` (object):
  - `kind` (string): `"pseudonym"` | `"user_provided"`
  - `value` (string): pseudonym or user-provided identity
  - `public_key` (string): OpenSSH Ed25519 public key line (`ssh-ed25519 <base64>`)
- `periods` (array): uploaded periods (always year periods)
  - each: `{ "label": "2025", "start": "2025-01-01", "end": "2026-01-01" }`
- `llm_coding` (object, optional): user-provided metadata from the wizard
- `year_totals` (array): one entry per uploaded year/period label
- `weekly` (object): weekly time series per year/period label

Not present:
- `repos` (removed)
- `privacy` (removed)

## `year_totals[]`

Each entry:
- `year` (int|string): numeric year for `YYYY` labels, otherwise the period label
- `repos_total` (int): total repos analyzed (same as top-level `repos_total`)
- `repos_active` (int): repos with at least one **me** commit in the period
- `repos_new` (int): repos whose **first commit in history** falls within the period
- `totals` (object): **me-only**, bootstrap-excluding totals
  - `commits` (int)
  - `insertions` (int)
  - `deletions` (int)
  - `changed` (int): `insertions + deletions`

## `weekly`

`weekly.definition`:
- `bucket`: `"week_start_monday_00_00_00Z"`
- `timestamp_source`: `"author_time_%aI_converted_to_utc"`
- `technology_kind`: `"language_for_path"`

`weekly.series_by_period`:
- object mapping period label (e.g. `"2025"`) → array of weekly rows.

### Weekly row

Each weekly row:
- `week_start` (string): `YYYY-MM-DDT00:00:00Z` (Monday, UTC)
- `commits` (int): **me-only**
- `insertions` (int): **me-only**
- `deletions` (int): **me-only**
- `changed` (int)
- `repo_activity_top1_share_changed` (float): fraction of `changed` attributable to the single most-active repo that week (0..1; `0.0` when `changed == 0`)
- `repo_activity_top3_share_changed` (float): fraction of `changed` attributable to the top 3 repos that week (0..1; `0.0` when `changed == 0`)
- `repos_active` (int): number of repos with ≥1 **me** commit in this week
- `repos_new` (int): number of repos whose first historical commit falls in this week
- `technologies` (array): per-language breakdown for this week (optional empty)
  - each: `{ "technology": "Python", "commits": 1, "insertions": 10, "deletions": 3, "changed": 13 }`
