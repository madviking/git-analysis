# Configuration

`git-analysis` reads settings from `config.json` (defaults to `./config.json`, override via `--config`).

## Identity ("me")
These are used to compute `"me"` vs `"others"` splits:
- `me_emails`: list of emails considered “me”
- `me_names`: list of author names considered “me”
- `me_email_globs`: optional email globs matched after lowercasing
- `me_name_globs`: optional name globs matched case-insensitively
- `me_github_usernames`: GitHub username(s) used to match `*@users.noreply.github.com` patterns

If `config.json` is missing, the tool attempts to infer `user.email` and `user.name` from global git config.
If `config.json` is missing, the tool creates it from `config-template.json`, fills obvious blanks (identity + scanned repo remotes), prompts you to review/edit it, then re-reads it before continuing the analysis.

## Repo discovery and filtering
- `include_remote_prefixes`: include a repo if its remote URL canonical form matches one of these prefixes
- `excluded_repos`: glob patterns to skip specific repo paths under `--root`
- `remote_name_priority`: which remote names to prefer when multiple exist (e.g. forks)
- `remote_filter_mode`: `"any"` or `"primary"`
- `exclude_forks`: exclude repos detected as forks
- `fork_remote_names`: which remote names indicate a fork parent (e.g. `["upstream"]`)
- `exclude_dirnames`: directory names skipped during discovery

## Excluding generated/vendored paths
These only affect line/language totals (not discovery):
- `exclude_path_prefixes`: prefix-based skips
- `exclude_path_globs`: glob-based skips

## Bootstraps/imports
Used to detect very large initial imports:
- `bootstrap_changed_threshold`
- `bootstrap_files_threshold`
- `bootstrap_addition_ratio`
- `bootstrap_exclude_shas`: list of commit SHAs to force-treat as non-bootstrap (even if they match thresholds)

## Publishing defaults
Publishing uses an interactive wizard. The wizard persists defaults under:

```json
{
  "upload_config": {
    "automatic_upload": "confirm",
    "api_url": "",
    "default_publish": false,
    "llm_coding": {
      "started_at": null,
      "dominant_at": null,
      "primary_tool_initial": "none",
      "primary_tool_current": "none"
    },
    "publisher": "",
    "repo_url_privacy": "none",
    "publisher_token_path": "~/.config/git-analysis/publisher_token"
  }
}
```

Notes:
- `default_publish` only controls the default shown in the prompt; the user is still prompted every run.
- The full publish setup wizard runs only when `upload_config` is not yet configured; afterwards you can edit `config.json` directly to change `upload_config.*`.
- `publisher` is not verified (no OAuth).
- If `publisher` is blank, the public identity is a derived pseudonym.
- `publisher_token_path` is a local secret used for replace semantics; keep it private.

## Upload server URL
The upload destination is stored in `config.json` under `upload_config.api_url`.
The client POSTs to `upload_config.api_url + "/api/v1/uploads"` (unless `--upload-url` is provided).
