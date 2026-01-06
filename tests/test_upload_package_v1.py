from __future__ import annotations

import gzip
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from git_analysis.upload_package_v1 import (
    build_upload_package_v1,
    canonical_json_bytes,
    ensure_publisher_token,
    upload_package_v1,
)


def test_publisher_token_is_created_and_persisted(tmp_path: Path) -> None:
    token_path = tmp_path / "publisher_token"
    t1 = ensure_publisher_token(token_path)
    t2 = ensure_publisher_token(token_path)
    assert t1
    assert t1 == t2


def test_canonical_json_is_deterministic() -> None:
    payload = {"b": 1, "a": {"y": 2, "x": 3}}
    b1 = canonical_json_bytes(payload)
    b2 = canonical_json_bytes(payload)
    assert b1 == b2


def test_privacy_modes_filter_repo_urls() -> None:
    base = {
        "schema_version": "upload_package_v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "toolkit_version": "0.1.0",
        "publisher": {"kind": "pseudonym", "value": "anon"},
        "weekly": {"definition": {}, "series_by_period": {}},
    }
    repos = [
        {"repo_key": "r1", "remote_canonical": "github.com/org/repo"},
        {"repo_key": "r2", "remote_canonical": "internal.example.com/org/repo"},
    ]

    p_none = build_upload_package_v1(base=base, repos=repos, privacy_mode="none")
    assert all("remote_canonical" not in r for r in p_none["repos"])

    p_all = build_upload_package_v1(base=base, repos=repos, privacy_mode="all")
    assert {r["remote_canonical"] for r in p_all["repos"]} == {"github.com/org/repo", "internal.example.com/org/repo"}

    p_public_only = build_upload_package_v1(base=base, repos=repos, privacy_mode="public_only")
    assert {r["remote_canonical"] for r in p_public_only["repos"] if "remote_canonical" in r} == {"github.com/org/repo"}
    assert all(r.get("remote_canonical") != "internal.example.com/org/repo" for r in p_public_only["repos"])


def test_upload_posts_gzipped_json_and_headers(tmp_path: Path) -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/v1/uploads":
                self.send_response(404)
                self.end_headers()
                return
            enc = self.headers.get("Content-Encoding")
            token = self.headers.get("X-Publisher-Token")
            sha = self.headers.get("X-Payload-SHA256")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if enc != "gzip" or not token or not sha:
                self.send_response(400)
                self.end_headers()
                return
            raw = gzip.decompress(body)
            digest = hashlib.sha256(raw).hexdigest()
            received["sha"] = sha
            received["digest"] = digest
            received["payload"] = json.loads(raw.decode("utf-8"))
            if digest != sha:
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(201)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    token_path = tmp_path / "publisher_token"
    token = ensure_publisher_token(token_path)

    payload = {
        "schema_version": "upload_package_v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "toolkit_version": "0.1.0",
        "publisher": {"kind": "pseudonym", "value": "anon"},
        "privacy": {"mode": "none"},
        "repos": [],
        "weekly": {"definition": {}, "series_by_period": {}},
    }
    raw = canonical_json_bytes(payload)
    sha = hashlib.sha256(raw).hexdigest()

    upload_package_v1(
        upload_url=f"http://127.0.0.1:{server.server_port}/api/v1/uploads",
        publisher_token=token,
        payload_bytes=raw,
        payload_sha256=sha,
        timeout_s=5,
    )

    server.shutdown()
    assert received["sha"] == sha
    assert received["digest"] == sha


def test_upload_raises_on_non_2xx(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(400)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    token_path = tmp_path / "publisher_token"
    token = ensure_publisher_token(token_path)
    raw = canonical_json_bytes({"ok": True})
    sha = hashlib.sha256(raw).hexdigest()

    with pytest.raises(RuntimeError):
        upload_package_v1(
            upload_url=f"http://127.0.0.1:{server.server_port}/api/v1/uploads",
            publisher_token=token,
            payload_bytes=raw,
            payload_sha256=sha,
            timeout_s=5,
        )

    server.shutdown()
