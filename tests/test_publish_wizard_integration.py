from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


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


def test_publish_wizard_persists_config_and_uploads(tmp_path: Path) -> None:
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

    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    (tmp_path / "server.json").write_text(json.dumps({"api_url": f"http://127.0.0.1:{server.server_port}"}), encoding="utf-8")

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

    # Always-prompt wizard flow (publish yes, identity, privacy, token path, confirm upload).
    answers = "\n".join(
        [
            "y",
            "Alice",
            "none",
            str(token_path),
            "y",
            "",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()
    assert proc.returncode == 0, proc.stderr

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    pub = cfg.get("publish") or {}
    assert pub.get("publisher") == "Alice"
    assert pub.get("repo_url_privacy") == "none"
    assert pub.get("publisher_token_path") == str(token_path)

    payload = received.get("payload") or {}
    assert payload.get("schema_version") == "upload_package_v1"
    assert (payload.get("publisher") or {}).get("value") == "Alice"
    assert (payload.get("privacy") or {}).get("mode") == "none"

