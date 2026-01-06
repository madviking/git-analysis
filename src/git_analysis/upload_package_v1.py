from __future__ import annotations

import gzip
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path


def canonical_json_bytes(data: object) -> bytes:
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def ensure_publisher_token(path: Path) -> str:
    p = Path(path).expanduser()
    if p.exists():
        token = p.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(f"publisher token file is empty: {p}")
        return token

    p.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    p.write_text(token + "\n", encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
    return token


def _host_for_remote_canonical(remote_canonical: str) -> str:
    s = (remote_canonical or "").strip().lower()
    if not s:
        return ""
    return s.split("/", 1)[0]


def build_upload_package_v1(*, base: dict, repos: list[dict], privacy_mode: str) -> dict:
    mode = (privacy_mode or "").strip().lower()
    if mode not in ("none", "public_only", "all"):
        raise ValueError(f"invalid privacy_mode: {privacy_mode!r}")

    allowed_public_hosts = {"github.com", "gitlab.com", "bitbucket.org"}
    out_repos: list[dict] = []
    for r in repos:
        repo_key = str(r.get("repo_key", "")).strip()
        if not repo_key:
            raise ValueError("repo missing repo_key")
        row: dict[str, object] = {"repo_key": repo_key}
        remote_canonical = str(r.get("remote_canonical", "")).strip()
        if mode == "all" and remote_canonical:
            row["remote_canonical"] = remote_canonical
        elif mode == "public_only" and remote_canonical:
            host = _host_for_remote_canonical(remote_canonical)
            if host in allowed_public_hosts:
                row["remote_canonical"] = remote_canonical
        out_repos.append(row)

    out_repos.sort(key=lambda d: str(d.get("repo_key", "")))

    out = dict(base)
    out["privacy"] = {"mode": mode, "verification_opt_in": mode in ("public_only", "all")}
    out["repos"] = out_repos
    return out


def upload_package_v1(
    *,
    upload_url: str,
    publisher_token: str,
    payload_bytes: bytes,
    payload_sha256: str,
    timeout_s: int = 30,
) -> None:
    if not upload_url.strip():
        raise ValueError("upload_url is required")
    if not publisher_token.strip():
        raise ValueError("publisher_token is required")
    if not payload_sha256.strip():
        raise ValueError("payload_sha256 is required")
    if hashlib.sha256(payload_bytes).hexdigest() != payload_sha256:
        raise ValueError("payload_sha256 does not match payload_bytes")

    body = gzip.compress(payload_bytes)
    req = urllib.request.Request(
        upload_url,
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "X-Publisher-Token": publisher_token,
            "X-Payload-SHA256": payload_sha256,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            if 200 <= code < 300:
                return
            payload = resp.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"upload failed: HTTP {code}: {payload[:500]}")
    except urllib.error.HTTPError as e:
        payload = ""
        try:
            payload = e.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        raise RuntimeError(f"upload failed: HTTP {e.code}: {payload[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"upload failed: {e}") from e
