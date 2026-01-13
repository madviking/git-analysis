from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)
    return proc.stdout


def _commit_file(*, repo: Path, filename: str, content: str, author_date: str) -> None:
    p = repo / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _run(["git", "add", filename], cwd=repo)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = author_date
    env["GIT_COMMITTER_DATE"] = author_date
    _run(["git", "commit", "-m", f"update {filename}"], cwd=repo, env=env)


def _parse_openssh_ed25519_public_key_line(line: str) -> bytes:
    parts = (line or "").strip().split()
    assert len(parts) >= 2
    assert parts[0] == "ssh-ed25519"
    blob = base64.b64decode(parts[1].encode("ascii"))

    import struct

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


def test_publish_wizard_can_verify_github_username_after_upload(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("ssh-keygen/openssl expectations are POSIX-focused")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required")
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required")

    requests: list[dict[str, object]] = []
    challenge = "abc123"
    message_to_sign = "git-analysis verify: sign this exact message"

    token_path = tmp_path / "publisher_token"
    key_path = tmp_path / "publisher_ed25519"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            token = self.headers.get("X-Publisher-Token")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append({"path": self.path, "token": token, "body": body})

            if self.path == "/api/v1/uploads":
                self.send_response(201)
                self.end_headers()
                return

            if self.path == "/api/v1/me/display-name":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"slug":"abc","display_name":"x","updated_at":"2026-01-07T00:00:00Z"}')
                return

            if self.path == "/api/v1/me/github/verify/challenge":
                obj = json.loads(body.decode("utf-8"))
                assert obj.get("github_username") == "madviking"
                resp = {"challenge": challenge, "message_to_sign": message_to_sign, "expires_at": "2026-01-01T00:00:00Z"}
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

                out = json.dumps({"verified": True, "verified_at": "2026-01-01T00:00:00Z"}).encode("utf-8")
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

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"me_emails": ["test@example.com"], "upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    answers = "\n".join(
        [
            "y",
            "2025",
            "github",
            "madviking",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert [r.get("path") for r in requests] == [
        "/api/v1/uploads",
        "/api/v1/me/display-name",
        "/api/v1/me/github/verify/challenge",
        "/api/v1/me/github/verify/confirm",
    ]


def test_publish_wizard_github_verify_404_html_suggests_wrong_api_url(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("ssh-keygen/openssl expectations are POSIX-focused")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required")
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required")

    token_path = tmp_path / "publisher_token"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))

            if self.path == "/api/v1/uploads":
                self.send_response(201)
                self.end_headers()
                return
            if self.path == "/api/v1/me/display-name":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"slug":"abc","display_name":"x","updated_at":"2026-01-07T00:00:00Z"}')
                return
            if self.path == "/api/v1/me/github/verify/challenge":
                body = b"<!DOCTYPE html><html><head><title>Not found</title></head><body>next</body></html>"
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"me_emails": ["test@example.com"], "upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    answers = "\n".join(
        [
            "y",
            "2025",
            "github",
            "madviking",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.lower()
    assert "github-verify challenge failed: http 404" in out
    assert "this looks like a web ui" in out or "api_url" in out


def test_publish_wizard_github_verify_retries_port_minus_one_on_html_404(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("ssh-keygen/openssl expectations are POSIX-focused")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required")
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required")

    api_requests: list[dict[str, object]] = []
    ui_requests: list[dict[str, object]] = []
    challenge = "abc123"
    message_to_sign = "git-analysis verify: sign this exact message"

    token_path = tmp_path / "publisher_token"

    class ApiHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            token = self.headers.get("X-Publisher-Token")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            api_requests.append({"path": self.path, "token": token, "body": body})

            if self.path == "/api/v1/me/github/verify/challenge":
                obj = json.loads(body.decode("utf-8"))
                assert obj.get("github_username") == "madviking"
                resp = {"challenge": challenge, "message_to_sign": message_to_sign, "expires_at": "2026-01-01T00:00:00Z"}
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

                # Validate signature against the publisher public key generated by the CLI.
                key_path = tmp_path / "publisher_ed25519"
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

                out = json.dumps({"verified": True, "verified_at": "2026-01-01T00:00:00Z"}).encode("utf-8")
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

    class UiHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            ui_requests.append({"path": self.path, "body": body})

            if self.path == "/api/v1/uploads":
                self.send_response(201)
                self.end_headers()
                return

            if self.path == "/api/v1/me/display-name":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"slug":"abc","display_name":"x","updated_at":"2026-01-07T00:00:00Z"}')
                return

            if self.path == "/api/v1/me/github/verify/challenge":
                html = b"<!DOCTYPE html><html><head><title>Not found</title></head><body>next</body></html>"
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    # Pick ports such that ui_port == api_port + 1 (for the tool's fallback heuristic).
    api_server = None
    ui_server = None
    for _attempt in range(25):
        api_server = HTTPServer(("127.0.0.1", 0), ApiHandler)
        api_port = int(api_server.server_port)
        try:
            ui_server = HTTPServer(("127.0.0.1", api_port + 1), UiHandler)
            break
        except OSError:
            api_server.shutdown()
            api_server.server_close()
            api_server = None
            continue
    assert api_server is not None and ui_server is not None

    t_api = threading.Thread(target=api_server.serve_forever, daemon=True)
    t_ui = threading.Thread(target=ui_server.serve_forever, daemon=True)
    t_api.start()
    t_ui.start()

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"me_emails": ["test@example.com"], "upload_config": {"api_url": f"http://127.0.0.1:{ui_server.server_port}"}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    answers = "\n".join(
        [
            "y",
            "2025",
            "github",
            "madviking",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    ui_server.shutdown()
    api_server.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert [r.get("path") for r in ui_requests] == ["/api/v1/uploads", "/api/v1/me/display-name", "/api/v1/me/github/verify/challenge"]
    assert [r.get("path") for r in api_requests] == ["/api/v1/me/github/verify/challenge", "/api/v1/me/github/verify/confirm"]


def test_publish_wizard_github_verify_key_not_found_prints_instructions(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("ssh-keygen/openssl expectations are POSIX-focused")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required")
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required")

    requests: list[dict[str, object]] = []
    token_path = tmp_path / "publisher_token"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append({"path": self.path, "body": body})

            if self.path == "/api/v1/uploads":
                self.send_response(201)
                self.end_headers()
                return
            if self.path == "/api/v1/me/display-name":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"slug":"abc","display_name":"x","updated_at":"2026-01-07T00:00:00Z"}')
                return
            if self.path == "/api/v1/me/github/verify/challenge":
                out = json.dumps({"challenge": "c", "message_to_sign": "m", "expires_at": "2026-01-01T00:00:00Z"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return
            if self.path == "/api/v1/me/github/verify/confirm":
                out = json.dumps({"error": "bad_request", "message": "profile public key not found on github user"}).encode("utf-8")
                self.send_response(400)
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

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"me_emails": ["test@example.com"], "upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    answers = "\n".join(
        [
            "y",
            "2025",
            "github",
            "madviking",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.lower()
    assert "profile public key not found on github user" in out
    assert "new ssh key" in out
    assert "not a gpg key" in out or "gpg" in out
    assert "authentication key" in out
    assert "signing key" in out
    assert "/users/madviking/keys" in out or "api.github.com/users/madviking/keys" in out


def test_publish_wizard_github_verify_key_not_found_can_retry(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("ssh-keygen/openssl expectations are POSIX-focused")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required")
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required")

    requests: list[str] = []
    token_path = tmp_path / "publisher_token"
    confirm_calls = 0

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            nonlocal confirm_calls
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append(self.path)

            if self.path == "/api/v1/uploads":
                self.send_response(201)
                self.end_headers()
                return
            if self.path == "/api/v1/me/display-name":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"slug":"abc","display_name":"x","updated_at":"2026-01-07T00:00:00Z"}')
                return
            if self.path == "/api/v1/me/github/verify/challenge":
                out = json.dumps({"challenge": "c", "message_to_sign": "m", "expires_at": "2026-01-01T00:00:00Z"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return
            if self.path == "/api/v1/me/github/verify/confirm":
                confirm_calls += 1
                if confirm_calls == 1:
                    out = json.dumps({"error": "bad_request", "message": "profile public key not found on github user"}).encode("utf-8")
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    self.wfile.write(out)
                    return
                out = json.dumps({"verified": True, "verified_at": "2026-01-01T00:00:00Z"}).encode("utf-8")
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

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"me_emails": ["test@example.com"], "upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    answers = "\n".join(
        [
            "y",
            "2025",
            "github",
            "madviking",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
            "y",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert requests.count("/api/v1/me/github/verify/confirm") == 2
    assert "github username verified" in proc.stdout.lower()


def test_publish_wizard_persists_config_and_uploads(tmp_path: Path) -> None:
    received: dict[str, object] = {}
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/v1/uploads":
                if self.path != "/api/v1/me/display-name":
                    self.send_response(404)
                    self.end_headers()
                    return
                token = self.headers.get("X-Publisher-Token")
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                requests.append({"path": self.path, "token": token, "body": body})
                try:
                    obj = json.loads(body.decode("utf-8"))
                except Exception:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"bad_request","message":"invalid json"}')
                    return
                received["display_name_req"] = obj
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"slug": "abc123", "display_name": str(obj.get("display_name", "")), "updated_at": "2026-01-07T00:00:00Z"}
                    ).encode("utf-8")
                )
                return

            enc = self.headers.get("Content-Encoding")
            token = self.headers.get("X-Publisher-Token")
            sha = self.headers.get("X-Payload-SHA256")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append({"path": self.path, "token": token, "sha": sha, "enc": enc, "body": body})
            if enc != "gzip" or not token or not sha:
                self.send_response(400)
                self.end_headers()
                return
            raw = gzip.decompress(body)
            digest = hashlib.sha256(raw).hexdigest()
            received["sha"] = sha
            received["digest"] = digest
            received["payload"] = json.loads(raw.decode("utf-8"))
            self.send_response(201)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    # Minimal git repo under scan root.
    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")
    # A non-"me" commit in the same year should not be included in the upload payload.
    _run(["git", "config", "user.name", "Other User"], cwd=repo)
    _run(["git", "config", "user.email", "other@example.com"], cwd=repo)
    _commit_file(repo=repo, filename="b.txt", content="b\n", author_date="2025-01-03T12:00:00Z")
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "me_emails": ["test@example.com"],
                "upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"},
            }
        ),
        encoding="utf-8",
    )

    token_path = tmp_path / "publisher_token"
    key_path = tmp_path / "publisher_ed25519"

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))

    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    # Always-prompt wizard flow (publish yes, identity, privacy, token path, confirm upload).
    answers = "\n".join(
        [
            "y",
            "2025",
            "custom",
            "Alice",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "server.json").exists() is False
    assert '"schema_version"' not in proc.stdout
    assert '"weekly"' not in proc.stdout
    assert "Upload package saved at:" in proc.stdout
    assert "Publisher token (local secret):" in proc.stdout
    assert str(token_path) in proc.stdout
    assert "not derived from SSH keys" in proc.stdout
    assert "Publisher key (Ed25519):" in proc.stdout
    assert str(key_path) in proc.stdout
    assert "ssh-ed25519 " in proc.stdout
    assert f"API POST http://127.0.0.1:{server.server_port}/api/v1/uploads" in proc.stdout
    assert "Payload:" in proc.stdout
    assert "upload_package_v1.json" in proc.stdout
    assert f"API POST http://127.0.0.1:{server.server_port}/api/v1/me/display-name" in proc.stdout
    assert '{"display_name":"Alice"}' in proc.stdout

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    up = cfg.get("upload_config") or {}
    assert up.get("display_name") == "Alice"
    assert up.get("publisher_token_path") == str(token_path)
    assert up.get("publisher_key_path") == str(key_path)
    llm = up.get("llm_coding") or {}
    assert (llm.get("started_at") or {}).get("value") == "2023-06"
    assert (llm.get("started_at") or {}).get("precision") == "month"
    assert (llm.get("dominant_at") or {}).get("value") == "2024-02-15"
    assert (llm.get("dominant_at") or {}).get("precision") == "day"
    assert llm.get("primary_tool_initial") == "github_copilot"
    assert llm.get("primary_tool_current") == "cursor"

    payload = received.get("payload") or {}
    assert payload.get("schema_version") == "upload_package_v1"
    assert (payload.get("publisher") or {}).get("kind") == "pseudonym"
    assert isinstance((payload.get("publisher") or {}).get("value"), str)
    pubkey = str((payload.get("publisher") or {}).get("public_key") or "")
    assert pubkey.startswith("ssh-ed25519 ")
    assert len(pubkey.split()) == 2
    llm2 = payload.get("llm_coding") or {}
    assert (llm2.get("started_at") or {}).get("value") == "2023-06"
    assert (llm2.get("dominant_at") or {}).get("value") == "2024-02-15"
    assert llm2.get("primary_tool_initial") == "github_copilot"
    assert llm2.get("primary_tool_current") == "cursor"

    assert "repos" not in payload
    assert "privacy" not in payload

    assert [r.get("path") for r in requests] == ["/api/v1/uploads", "/api/v1/me/display-name"]
    assert (received.get("display_name_req") or {}).get("display_name") == "Alice"

    year_totals = payload.get("year_totals") or []
    assert any(int(row.get("year")) == 2025 for row in year_totals if isinstance(row, dict))
    totals_2025 = next((row for row in year_totals if isinstance(row, dict) and int(row.get("year", 0)) == 2025), {})
    assert int((totals_2025.get("totals") or {}).get("commits", 0)) == 1
    assert int(totals_2025.get("repos_total", 0)) == 1
    assert int(totals_2025.get("repos_active", 0)) == 1
    assert int(totals_2025.get("repos_new", 0)) == 1

    weekly = payload.get("weekly") or {}
    assert (weekly.get("definition") or {}).get("technology_kind") == "language_for_path"
    rows = (weekly.get("series_by_period") or {}).get("2025") or []
    assert rows and isinstance(rows, list)
    assert int(rows[0].get("repos_active", 0)) == 1
    assert int(rows[0].get("repos_new", 0)) == 1
    assert float(rows[0].get("repo_activity_top1_share_changed", 0.0) or 0.0) == 1.0
    assert float(rows[0].get("repo_activity_top3_share_changed", 0.0) or 0.0) == 1.0
    techs = rows[0].get("technologies") or []
    assert techs and isinstance(techs, list)
    assert {t.get("technology") for t in techs} == {"Other"}
    assert int(payload.get("weekly_nonzero_commits_weeks", 0) or 0) == 1
    assert int(payload.get("weekly_nonzero_changed_weeks", 0) or 0) == 1


def test_publish_wizard_skips_setup_when_config_present(tmp_path: Path) -> None:
    # Minimal git repo under scan root.
    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    token_path = tmp_path / "publisher_token"
    key_path = tmp_path / "publisher_ed25519"
    config = {
        "upload_config": {
            "default_publish": False,
            "api_url": "http://example.invalid",
            "display_name": "Alice",
            "publisher_token_path": str(token_path),
            "publisher_key_path": str(key_path),
            "upload_years": [2025],
            "llm_coding": {
                "started_at": {"value": "2023-06", "precision": "month"},
                "dominant_at": {"value": "2024-02-15", "precision": "day"},
                "primary_tool_initial": "github_copilot",
                "primary_tool_current": "cursor",
            },
        }
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))

    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    # With a complete upload_config present, only confirm publish + upload (no re-running the setup wizard).
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input="y\n2025\nn\n", text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr

    out = proc.stdout
    assert "display name" not in out.lower()
    assert "Primary LLM coding tool when you started" not in out
    assert "Edit config.json" in out
    assert "Continuing analysis" in out


def test_publish_prompt_explains_what_you_get(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))

    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input="n\n", text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr

    out = proc.stdout
    assert "What you get by publishing" in out
    assert "LLM tools" in out
    assert "leaderboards" in out or "top lists" in out


def test_publish_upload_years_always_include_2025(tmp_path: Path) -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/v1/uploads":
                if self.path == "/api/v1/me/display-name":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"slug":"abc","display_name":"x","updated_at":"2026-01-07T00:00:00Z"}')
                    return
                self.send_response(404)
                self.end_headers()
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            raw = gzip.decompress(body)
            received["payload"] = json.loads(raw.decode("utf-8"))
            self.send_response(201)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2024-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "me_emails": ["test@example.com"],
                "upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"},
            }
        ),
        encoding="utf-8",
    )
    token_path = tmp_path / "publisher_token"

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))

    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2024",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    answers = "\n".join(
        [
            "y",
            "2024",
            "custom",
            "Alice",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()
    assert proc.returncode == 0, proc.stderr

    payload = received.get("payload") or {}
    periods = payload.get("periods") or []
    labels = {p.get("label") for p in periods if isinstance(p, dict)}
    assert "2024" in labels
    assert "2025" in labels


def test_publish_upload_http_error_is_graceful(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"bad_request","message":"invalid privacy.mode: \\"\\""}')

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    scan_root = tmp_path / "scan"
    repo = scan_root / "r"
    repo.mkdir(parents=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/repo.git"], cwd=repo)
    _commit_file(repo=repo, filename="a.txt", content="a\n", author_date="2025-01-02T12:00:00Z")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "me_emails": ["test@example.com"],
                "upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"},
            }
        ),
        encoding="utf-8",
    )
    token_path = tmp_path / "publisher_token"

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))

    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "--root",
        str(scan_root),
        "--years",
        "2025",
        "--config",
        str(config_path),
        "--jobs",
        "1",
    ]

    answers = "\n".join(
        [
            "y",
            "2025",
            "custom",
            "Alice",
            str(token_path),
            "2023-06",
            "2024-02-15",
            "github_copilot",
            "cursor",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert "upload failed: HTTP 400" in (proc.stdout + proc.stderr)
