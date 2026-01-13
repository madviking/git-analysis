# Toolkit Brief: Verified GitHub Username

## What we have today (v7 upload package)

- `docs/upload_package_v1_v7.json` includes `publisher.public_key` (OpenSSH `ssh-ed25519 ...`).
- The upload package does **not** include a GitHub username or a “verified” claim; verification is a separate API flow.

## What “verified GitHub username” means

A profile is considered GitHub-verified when the backend can prove that:

1) The toolkit controls the publisher Ed25519 private key (signs a short-lived challenge).
2) GitHub shows the matching public key on `https://api.github.com/users/{username}/keys`.

No OAuth is used.

## Toolkit changes needed

1) **Persist a publisher Ed25519 keypair**
   - Generate once per publisher and store locally (same lifecycle as the publisher token).
   - Never upload the private key.

2) **Always include the public key in uploads**
   - Every upload must include `publisher.public_key` in OpenSSH authorized_keys format:
     - `ssh-ed25519 <base64>`

3) **Add a “Verify GitHub username” command/flow**
   - Precondition: the user must have uploaded at least once (backend needs a profile row).
   - Ask the user to add `publisher.public_key` to GitHub → Settings → SSH and GPG keys.

## API flow (toolkit → backend)

1) Request challenge:
   - `POST /api/v1/me/github/verify/challenge`
   - Header: `X-Publisher-Token: <publisherToken>`
   - Body: `{ "github_username": "someuser" }`

2) Sign:
   - Sign the exact UTF-8 bytes of `message_to_sign` with Ed25519.
   - Base64-encode the 64-byte signature.

3) Confirm:
   - `POST /api/v1/me/github/verify/confirm`
   - Header: `X-Publisher-Token: <publisherToken>`
   - Body: `{ "github_username": "...", "challenge": "...", "signature": "..." }`

On success, the backend stores `profiles.github_username` + `profiles.github_verified_at` and marks the profile `verified=true`.

## References (full details)

- `docs/toolkit-github-verification.md` (toolkit implementation guide)
- `docs/github-username-verification.md` (flow overview + error cases)

