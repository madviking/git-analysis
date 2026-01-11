from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from git_analysis.upload_package_v1 import (
    canonical_json_bytes,
    ensure_publisher_token,
    _ensure_macos_ca_bundle,
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


def _make_https_server_with_ca(tmp_path: Path, handler_cls: type[BaseHTTPRequestHandler]) -> tuple[HTTPServer, Path]:
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required for HTTPS upload tests")

    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    srv_key = tmp_path / "server.key"
    srv_csr = tmp_path / "server.csr"
    srv_crt = tmp_path / "server.crt"
    srv_ext = tmp_path / "server.ext"
    srv_ext.write_text("subjectAltName=IP:127.0.0.1\n", encoding="utf-8")

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_crt),
            "-subj",
            "/CN=git-analysis test CA",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(srv_key),
            "-out",
            str(srv_csr),
            "-subj",
            "/CN=127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(srv_csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(srv_crt),
            "-days",
            "1",
            "-sha256",
            "-extfile",
            str(srv_ext),
        ],
        check=True,
        capture_output=True,
    )

    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(srv_crt), keyfile=str(srv_key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, ca_crt


def test_upload_https_succeeds_with_ca_bundle(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/v1/uploads":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(201)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server, ca_bundle = _make_https_server_with_ca(tmp_path, Handler)
    token = ensure_publisher_token(tmp_path / "publisher_token")
    raw = canonical_json_bytes({"ok": True})
    sha = hashlib.sha256(raw).hexdigest()

    upload_package_v1(
        upload_url=f"https://127.0.0.1:{server.server_port}/api/v1/uploads",
        publisher_token=token,
        payload_bytes=raw,
        payload_sha256=sha,
        timeout_s=5,
        ca_bundle_path=str(ca_bundle),
    )

    server.shutdown()


def test_upload_https_error_includes_ca_bundle_hint(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(201)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server, _ca_bundle = _make_https_server_with_ca(tmp_path, Handler)
    token = ensure_publisher_token(tmp_path / "publisher_token")
    raw = canonical_json_bytes({"ok": True})
    sha = hashlib.sha256(raw).hexdigest()

    with pytest.raises(RuntimeError) as e:
        upload_package_v1(
            upload_url=f"https://127.0.0.1:{server.server_port}/api/v1/uploads",
            publisher_token=token,
            payload_bytes=raw,
            payload_sha256=sha,
            timeout_s=5,
        )

    server.shutdown()
    msg = str(e.value)
    assert "CERTIFICATE_VERIFY_FAILED" in msg or "certificate verify failed" in msg.lower()
    assert "--ca-bundle" in msg or "ca_bundle_path" in msg


def test_macos_ca_bundle_auto_generation(tmp_path: Path) -> None:
    if sys.platform != "darwin":
        pytest.skip("macOS-only CA bundle generation")

    cafile = _ensure_macos_ca_bundle(cache_dir=tmp_path)
    assert cafile is not None
    assert cafile.exists()
    txt = cafile.read_text(encoding="utf-8", errors="ignore")
    assert "BEGIN CERTIFICATE" in txt
