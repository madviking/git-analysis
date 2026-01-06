# Publishing (upload wizard)

Publishing is interactive and always prompts at run start:
1) Whether to publish
2) Public identity (blank = derived pseudonym)
3) Repo URL privacy mode: `none` | `public_only` | `all`
4) Publisher token path (local secret)

If publishing is enabled, the tool will later:
1) Print a payload preview (token redacted)
2) Print the payload SHA-256 (canonical JSON bytes)
3) Prompt for final confirmation before upload

## Privacy modes
- `none`: do not include repo URLs in the uploaded payload
- `public_only`: include only known public hosts (currently `github.com`, `gitlab.com`, `bitbucket.org`)
- `all`: include all `remote_canonical` values

`verification_opt_in` is set automatically when privacy mode is `public_only` or `all`.

## Replace semantics / publisher token
The client sends a stable `publisher_token` (a local secret) in the `X-Publisher-Token` header. The server should store only a hash and use it to identify the publisher for replace semantics.

Default location: `~/.config/git-analysis/publisher_token` (override in the wizard or via `config.json`).

## Server destination
The server base URL is configured in `server.json`:

```json
{
  "api_url": "http://localhost:3220"
}
```

Uploads are sent as:
- `POST /api/v1/uploads`
- Body: gzipped canonical JSON
- Headers:
  - `Content-Encoding: gzip`
  - `X-Publisher-Token: <secret>`
  - `X-Payload-SHA256: <sha256 of uncompressed canonical JSON bytes>`

## Saved defaults
Wizard answers are persisted to `config.json` under `publish.*` and reused as defaults in future prompts.

