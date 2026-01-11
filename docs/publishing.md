# Publishing (upload wizard)

Publishing is interactive and always prompts at run start whether to publish.

The first time you publish (or if `upload_config` is missing), the wizard collects:
1) Which years to include in the upload (full calendar years; 2025 is always included)
2) Public display name preference: derived pseudonym (default), GitHub username, or custom string
3) Publisher token path (local secret)
4) LLM coding inflection points (start date, “>90% by LLM” date)
5) Primary LLM coding tool (initial + current) from a fixed list

Once `upload_config` is set up, the wizard does not re-prompt for these values; update them by editing `config.json` under `upload_config.*`.

If publishing is enabled, the tool will later:
1) Print an upload preview summary (and save the payload to disk)
2) Print the payload SHA-256 (canonical JSON bytes)
3) Prompt for final confirmation before upload
 
Uploads contain only your own (“me”) stats (not aggregate stats across all authors) and contain no repo identifiers/URLs.

## Display name updates
The backend exposes an authenticated endpoint for changing the publicly shown username (profile display name).

- Endpoint: `POST /api/v1/me/display-name`
- Auth: `X-Publisher-Token: <publisherToken>` (same token used for uploads)

You can update it without re-running analysis:

```bash
./cli.sh display-name --name "New Name"
./cli.sh display-name --pseudonym
```

## Replace semantics / publisher token
The client sends a stable `publisher_token` (a local secret) in the `X-Publisher-Token` header. The server should store only a hash and use it to identify the publisher for replace semantics.

Default location: `~/.config/git-analysis/publisher_token` (override in the wizard or via `config.json`).

## Server destination
The server base URL is configured in `config.json` under `upload_config.api_url` (or overridden via `--upload-url`).
If your server uses HTTPS, the client verifies certificates using a discovered CA trust store; for private CAs, set `upload_config.ca_bundle_path` or pass `--ca-bundle`.

Uploads are sent as:
- `POST /api/v1/uploads`
- Body: gzipped canonical JSON
- Headers:
  - `Content-Encoding: gzip`
  - `X-Publisher-Token: <secret>`
  - `X-Payload-SHA256: <sha256 of uncompressed canonical JSON bytes>`

## Saved defaults
Wizard answers are persisted to `config.json` under `upload_config.*` and reused as defaults in future prompts.

Note: uploads are disabled when analysis is run with `--include-merges`, `--include-bootstraps`, or `--dedupe path` (non-standard runs).

## Upload an existing report folder

If a report folder already contains `json/upload_package_v1.json`, you can upload it without re-running analysis:

```bash
./cli.sh upload --report-dir reports/<run-type>/<timestamp> --yes
```

`--yes` skips the confirmation prompt.

If HTTPS verification fails, provide a CA bundle:

```bash
./cli.sh upload --report-dir reports/<run-type>/<timestamp> --yes --ca-bundle /path/to/ca.pem
```
