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
Used to detect very large one-sided bulk commits (imports or mass deletions):
- `bootstrap_changed_threshold`
- `bootstrap_files_threshold`
- `bootstrap_addition_ratio` (minimum `max(insertions,deletions)/(insertions+deletions)`)
- `bootstrap_exclude_shas`: list of commit SHAs to force-treat as non-bootstrap (even if they match thresholds)

Note: extremely large outliers (very large one-sided commits, or very large multi-file sweeps) are also treated as bootstraps.

## Excluding specific commits
- `exclude_commits`: list of commit SHAs to exclude entirely from stats (and from `csv/top_commits.csv`)

## Publishing defaults
Publishing uses an interactive wizard. The wizard persists defaults under:

```json
{
  "upload_config": {
    "automatic_upload": "confirm",
    "api_url": "",
    "ca_bundle_path": "",
    "default_publish": false,
    "upload_years": [2024, 2025],
    "llm_coding": {
      "started_at": null,
      "dominant_at": null,
      "primary_tool_initial": "none",
      "primary_tool_current": "none"
    },
    "display_name": "",
    "publisher_token_path": "~/.config/git-analysis/publisher_token",
    "publisher_key_path": "~/.config/git-analysis/publisher_ed25519"
  }
}
```

Notes:
- `default_publish` only controls the default shown in the prompt; the user is still prompted every run.
- The full publish setup wizard runs only when `upload_config` is not yet configured; afterwards you can edit `config.json` directly to change `upload_config.*`.
- `display_name` is a user preference for your public profile name; it can be updated at any time via `./cli.sh display-name`.
- `publisher_token_path` is a local secret used for replace semantics; keep it private.
- `publisher_key_path` is your publisher Ed25519 keypair path (OpenSSH private key; public key is stored at `publisher_key_path + ".pub"`). The **public** key is included in uploads and can be used for GitHub username verification (`./cli.sh github-verify`, requires `openssl`).
- `upload_years` controls which full years are included in uploads; uploads always include 2025 even if not listed.

## Upload server URL
The upload destination is stored in `config.json` under `upload_config.api_url`.
The client POSTs to `upload_config.api_url + "/api/v1/uploads"` (unless `--upload-url` is provided).

## HTTPS CA bundle (TLS verification)
If your upload server uses HTTPS and you see `CERTIFICATE_VERIFY_FAILED`, the client could not find a usable CA trust store.

The tool will try to discover a CA bundle automatically (including generating one from the macOS system Keychain when needed), so this should not normally require manual setup.

Options:
- Set `upload_config.ca_bundle_path` to a CA bundle file (or directory) to use for HTTPS verification.
- Or pass `--ca-bundle /path/to/ca.pem` for a one-off override.
