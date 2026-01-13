# GitHub Username Verification (Flow + Error Cases)

This document describes the *user-facing* flow for verifying a GitHub username with the upload backend, without OAuth.

Verification proves:
1) You control the publisher Ed25519 private key (by signing a server-provided challenge).
2) GitHub reports the matching public key on `https://api.github.com/users/{username}/keys`.

Important: the toolkit never uploads your private key. The backend receives only the GitHub username, a short-lived challenge, and a signature; it already knows your public key from prior uploads.

## Preconditions

- You must upload at least once (the backend needs a profile row).
- You must add your publisher public key to GitHub:
  - GitHub → Settings → SSH and GPG keys → New SSH key

## CLI usage

Verify a username explicitly:

```bash
./cli.sh github-verify --username <github-username>
```

If your `config.json` has `me_github_usernames`, you can omit `--username` and the CLI uses the first entry:

```bash
./cli.sh github-verify
```

If you choose a GitHub username as your publish display name, the normal publish flow will also offer to verify it after upload (opt-in).

## Flow overview

1) Toolkit requests a short-lived challenge from the backend:
   - `POST /api/v1/me/github/verify/challenge`
   - Body: `{ "github_username": "<name>" }`
2) Toolkit signs `message_to_sign` with the publisher Ed25519 private key and base64-encodes the 64-byte signature.
3) Toolkit confirms verification:
   - `POST /api/v1/me/github/verify/confirm`
   - Body: `{ "github_username": "<name>", "challenge": "...", "signature": "..." }`

On success, the backend stores `profiles.github_username` + `profiles.github_verified_at` and marks the profile `verified=true`.

## Common error cases

- `HTTP 404 profile not found`
  - Meaning: you haven’t uploaded yet.
  - Fix: run a normal analysis and upload once, then re-run `github-verify`.

- `HTTP 400 key not found on GitHub`
  - Meaning: GitHub doesn’t show your publisher public key on the target account.
  - Fix: add the exact `ssh-ed25519 ...` line printed by the CLI to GitHub → Settings → SSH and GPG keys → **New SSH key** (not GPG), choose **Authentication key** (not Signing key), then retry.
  - Sanity check: `https://api.github.com/users/<username>/keys` should list your key. If you added it as a *Signing key*, it won’t appear there and verification will keep failing.

- `HTTP 400 invalid signature` / `challenge expired`
  - Meaning: the signature doesn’t match, or the challenge timed out.
  - Fix: retry; if it persists, ensure your `upload_config.publisher_key_path` points to the correct keypair.

- `HTTP 502 github verification failed`
  - Meaning: transient GitHub API failure (or rate limiting on the backend).
  - Fix: retry after a short delay.
