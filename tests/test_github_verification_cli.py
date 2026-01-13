from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def _parse_openssh_ed25519_public_key_line(line: str) -> bytes:
    parts = (line or "").strip().split()
    assert len(parts) >= 2
    assert parts[0] == "ssh-ed25519"
    blob = base64.b64decode(parts[1].encode("ascii"))

    def read_u32(buf: bytes, off: int) -> tuple[int, int]:
        if off + 4 > len(buf):
            raise ValueError("truncated")
        return struct.unpack(">I", buf[off : off + 4])[0], off + 4

    def read_str(buf: bytes, off: int) -> tuple[bytes, int]:
        n, off = read_u32(buf, off)
        if off + n > len(buf):
            raise ValueError("truncated")
        return buf[off : off + n], off + n

    ktype, off = read_str(blob, 0)
    assert ktype == b"ssh-ed25519"
    key, off = read_str(blob, off)
    assert len(key) == 32
    assert off == len(blob)
    return key


def _ed25519_public_key_pem_from_raw(raw32: bytes) -> bytes:
    if len(raw32) != 32:
        raise ValueError("expected 32-byte Ed25519 public key")
    # SubjectPublicKeyInfo for Ed25519 (RFC 8410):
    # 30 2a 30 05 06 03 2b 65 70 03 21 00 <32 bytes>
    der = b"\x30\x2a\x30\x05\x06\x03\x2b\x65\x70\x03\x21\x00" + raw32
    b64 = base64.b64encode(der).decode("ascii")
    lines = [b64[i : i + 64] for i in range(0, len(b64), 64)]
    pem = "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n"
    return pem.encode("ascii")


def test_github_verify_cli_flow_signs_and_confirms(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("ssh-keygen/openssl expectations are POSIX-focused")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required")
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required")

    received: list[dict[str, object]] = []
    challenge = "abc123"
    message_to_sign = "git-analysis verify: sign this exact message"

    token_path = tmp_path / "publisher_token"
    key_path = tmp_path / "publisher_ed25519"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            token = self.headers.get("X-Publisher-Token")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append({"path": self.path, "token": token, "body": body})

            if self.path == "/api/v1/me/github/verify/challenge":
                obj = json.loads(body.decode("utf-8"))
                assert obj.get("github_username") == "madviking"
                resp = {
                    "challenge": challenge,
                    "message_to_sign": message_to_sign,
                    "expires_at": "2026-01-01T00:00:00Z",
                }
                out = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return

            if self.path == "/api/v1/me/github/verify/confirm":
                obj = json.loads(body.decode("utf-8"))
                assert obj.get("github_username") == "madviking"
                assert obj.get("challenge") == challenge
                sig_b64 = str(obj.get("signature") or "")
                sig = base64.b64decode(sig_b64.encode("ascii"))
                assert len(sig) == 64

                pub_path = Path(str(key_path) + ".pub")
                assert pub_path.exists()
                pub_line = pub_path.read_text(encoding="utf-8").strip()
                raw_pk = _parse_openssh_ed25519_public_key_line(pub_line)
                pub_pem = _ed25519_public_key_pem_from_raw(raw_pk)

                msg_bin = tmp_path / "msg.bin"
                sig_bin = tmp_path / "sig.bin"
                pub_pem_path = tmp_path / "pub.pem"
                msg_bin.write_bytes(message_to_sign.encode("utf-8"))
                sig_bin.write_bytes(sig)
                pub_pem_path.write_bytes(pub_pem)

                subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-verify",
                        "-rawin",
                        "-pubin",
                        "-inkey",
                        str(pub_pem_path),
                        "-sigfile",
                        str(sig_bin),
                        "-in",
                        str(msg_bin),
                    ],
                    check=True,
                    capture_output=True,
                )

                resp = {"verified": True, "verified_at": "2026-01-01T00:00:00Z"}
                out = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "upload_config": {
                    "api_url": f"http://127.0.0.1:{server.server_port}",
                    "publisher_token_path": str(token_path),
                    "publisher_key_path": str(key_path),
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "github-verify",
        "--config",
        str(config_path),
        "--username",
        "madviking",
    ]
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, text=True, capture_output=True)
    server.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert "Publisher token (local secret):" in proc.stdout
    assert "Publisher key (Ed25519):" in proc.stdout
    assert "ssh-ed25519 " in proc.stdout
    assert "verified" in proc.stdout.lower()

    assert [r.get("path") for r in received] == [
        "/api/v1/me/github/verify/challenge",
        "/api/v1/me/github/verify/confirm",
    ]


def test_github_verify_cli_defaults_username_from_config(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("ssh-keygen/openssl expectations are POSIX-focused")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required")
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required")

    received: list[dict[str, object]] = []
    challenge = "abc123"
    message_to_sign = "git-analysis verify: sign this exact message"

    token_path = tmp_path / "publisher_token"
    key_path = tmp_path / "publisher_ed25519"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            token = self.headers.get("X-Publisher-Token")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append({"path": self.path, "token": token, "body": body})

            if self.path == "/api/v1/me/github/verify/challenge":
                obj = json.loads(body.decode("utf-8"))
                assert obj.get("github_username") == "madviking"
                resp = {
                    "challenge": challenge,
                    "message_to_sign": message_to_sign,
                    "expires_at": "2026-01-01T00:00:00Z",
                }
                out = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return

            if self.path == "/api/v1/me/github/verify/confirm":
                obj = json.loads(body.decode("utf-8"))
                assert obj.get("github_username") == "madviking"
                assert obj.get("challenge") == challenge
                sig_b64 = str(obj.get("signature") or "")
                sig = base64.b64decode(sig_b64.encode("ascii"))
                assert len(sig) == 64

                resp = {"verified": True, "verified_at": "2026-01-01T00:00:00Z"}
                out = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "me_github_usernames": ["madviking"],
                "upload_config": {
                    "api_url": f"http://127.0.0.1:{server.server_port}",
                    "publisher_token_path": str(token_path),
                    "publisher_key_path": str(key_path),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "github-verify",
        "--config",
        str(config_path),
    ]
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, text=True, capture_output=True)
    server.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert [r.get("path") for r in received] == [
        "/api/v1/me/github/verify/challenge",
        "/api/v1/me/github/verify/confirm",
    ]
