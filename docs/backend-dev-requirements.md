# Backend Requirements Update (Toolkit → Backend)

This document summarizes additions/changes in the `git-analysis` toolkit that require backend support beyond what’s described in `docs/backend-support.md`.

## 1) Upload payload: new `llm_coding` field

`upload_package_v1.json` now includes an optional top-level `llm_coding` object (user-provided metadata collected via the publish wizard).

Proposed structure:

```json
{
  "llm_coding": {
    "started_at": { "value": "2023-06", "precision": "month" },
    "dominant_at": { "value": "2024-02-15", "precision": "day" },
    "primary_tool_initial": "github_copilot",
    "primary_tool_current": "cursor"
  }
}
```

Notes:
- `started_at` and `dominant_at` are optional (can be `null`).
- `precision` is one of: `year` | `month` | `day`.
- The backend should accept unknown additional keys in the payload (forward-compatible).

### 1.1 Tool enum (standardized)
`primary_tool_initial` and `primary_tool_current` are selected from a fixed set of IDs:
- `none`
- `github_copilot`
- `cursor`
- `windsurf`
- `chatgpt`
- `claude`
- `jetbrains_ai`
- `aws_codewhisperer`
- `sourcegraph_cody`
- `continue`
- `tabnine`
- `other`

Backend storage should treat these as categorical enum-like values (string).

## 2) Config persistence: upload settings live under `upload_config`

The publish wizard persists defaults in `config.json` under `upload_config.*` (previously documented as `publish.*`):
- `upload_config.default_publish`
- `upload_config.publisher`
- `upload_config.repo_url_privacy`
- `upload_config.publisher_token_path`
- `upload_config.api_url` (server base URL)
- `upload_config.automatic_upload` (`confirm` | `always` | `never`, with tolerant parsing of yes/no-like values)
- `upload_config.llm_coding` (new)

## 3) Repo selection: `excluded_repos`

Toolkit now supports `config.json["excluded_repos"]` (list of glob patterns) to skip specific repos by path under `--root`.
This impacts which repos make it into the upload package (and the weekly aggregates), but does not change schema.
