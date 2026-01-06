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

## Repo discovery and filtering
- `include_remote_prefixes`: include a repo if its remote URL canonical form matches one of these prefixes
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

## Publishing defaults
Publishing uses an interactive wizard. The wizard persists defaults under:

```json
{
  "publish": {
    "default_publish": false,
    "publisher": "",
    "repo_url_privacy": "none",
    "publisher_token_path": "~/.config/git-analysis/publisher_token"
  }
}
```

Notes:
- `default_publish` only controls the default shown in the prompt; the user is still prompted every run.
- `publisher` is not verified (no OAuth).
- If `publisher` is blank, the public identity is a derived pseudonym.
- `publisher_token_path` is a local secret used for replace semantics; keep it private.

## Server configuration (`server.json`)
The upload destination is stored in `server.json` (next to `config.json` if present, otherwise in the current working directory):

```json
{
  "api_url": "http://localhost:3220"
}
```

The client POSTs to `api_url + "/api/v1/uploads"`.

