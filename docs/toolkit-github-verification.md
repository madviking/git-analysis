# Toolkit Developer Guide — GitHub Username Verification

This describes how the toolkit CLI should implement GitHub username “ownership verification” against the backend **without OAuth**, using the publisher’s Ed25519 key.

## Concept

The backend will mark the public profile as verified when:
1) The toolkit proves it controls the publisher private key by signing a short-lived challenge.
2) GitHub reports that the same public key is present on the target username’s SSH keys list (`/users/{username}/keys`).

This is intentionally “lightweight verification”: it proves control of the key and that the key is attached to the GitHub account, without requiring repo changes, commits, gists, or OAuth.

## Requirements

### 1) Persist a publisher Ed25519 keypair

- Generate once per publisher and store locally (same lifecycle as the publisher token).
- Keep the private key private; never upload it.

### 2) Upload payload must include the public key

Every `upload_package_v1` payload must include:
- `publisher.public_key`: OpenSSH authorized_keys format for Ed25519
  - `ssh-ed25519 <base64>`

The backend validates that `publisher.public_key` is a syntactically valid `ssh-ed25519` key.

### 3) User must add the key to GitHub

To pass verification, the user must add `publisher.public_key` to:
GitHub → Settings → SSH and GPG keys → New SSH key.

## API flow (toolkit)

### Step 0: ensure a profile exists

Verification is tied to the publisher profile row. The toolkit should ensure the user has uploaded at least once before starting verification.

### Step 1: request a challenge

`POST /api/v1/me/github/verify/challenge`

Headers:
- `X-Publisher-Token: <publisherToken>`

Body:
```json
{ "github_username": "madviking" }
```

Response fields:
- `challenge`: random base64url string (no padding)
- `message_to_sign`: exact message the toolkit must sign
- `expires_at`: expiration timestamp

### Step 2: sign the challenge

- Compute Ed25519 signature over the **exact UTF-8 bytes** of `message_to_sign`.
- Base64-encode the signature using standard base64.

### Step 3: confirm verification

`POST /api/v1/me/github/verify/confirm`

Headers:
- `X-Publisher-Token: <publisherToken>`

Body:
```json
{
  "github_username": "madviking",
  "challenge": "challenge_from_step_1",
  "signature": "base64_ed25519_signature"
}
```

Success response:
- `verified: true`
- `verified_at`

## UX guidance (keep it non-suspicious)

- Explain plainly: “We verify by checking that your toolkit key is listed on your GitHub account. No repo access, no OAuth.”
- Show the exact `publisher.public_key` line and a “Copy” button.
- If verification fails with “key not found on GitHub”, show instructions to add the SSH key and re-try.
- Keep verification optional; do not block uploads.

## Error handling expectations

Common failures:
- `404 profile not found`: user hasn’t uploaded yet → prompt to upload once.
- `400 invalid signature` / `challenge expired` / `key not found on GitHub`: show actionable guidance and allow retry.
- `502 github verification failed`: treat as transient; allow retry/backoff.

### Upload error: missing public key

If the toolkit attempts an upload without including `publisher.public_key`, the backend will reject it with:

`upload failed: HTTP 400: {"error":"bad_request","message":"publisher.public_key is required"}`

Fix:
- Ensure every upload payload includes `publisher.public_key` (OpenSSH `ssh-ed25519 <base64>`).
- If the publisher keypair does not exist yet, generate it and persist it before uploading.

## Notes for backend operators (FYI)

- Backend optionally uses `GITHUB_TOKEN` to avoid low unauthenticated rate limits.
- Backend base URL is configurable via `GITHUB_API_BASE_URL` (useful for tests).
