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
    config_path.write_text(json.dumps({"upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}"}}), encoding="utf-8")

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

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    up = cfg.get("upload_config") or {}
    assert up.get("publisher") == "Alice"
    assert up.get("repo_url_privacy") == "none"
    assert up.get("publisher_token_path") == str(token_path)
    llm = up.get("llm_coding") or {}
    assert (llm.get("started_at") or {}).get("value") == "2023-06"
    assert (llm.get("started_at") or {}).get("precision") == "month"
    assert (llm.get("dominant_at") or {}).get("value") == "2024-02-15"
    assert (llm.get("dominant_at") or {}).get("precision") == "day"
    assert llm.get("primary_tool_initial") == "github_copilot"
    assert llm.get("primary_tool_current") == "cursor"

    payload = received.get("payload") or {}
    assert payload.get("schema_version") == "upload_package_v1"
    assert (payload.get("publisher") or {}).get("value") == "Alice"
    assert (payload.get("privacy") or {}).get("mode") == "none"
    llm2 = payload.get("llm_coding") or {}
    assert (llm2.get("started_at") or {}).get("value") == "2023-06"
    assert (llm2.get("dominant_at") or {}).get("value") == "2024-02-15"
    assert llm2.get("primary_tool_initial") == "github_copilot"
    assert llm2.get("primary_tool_current") == "cursor"


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
    config = {
        "upload_config": {
            "default_publish": False,
            "api_url": "http://example.invalid",
            "publisher": "Alice",
            "repo_url_privacy": "none",
            "publisher_token_path": str(token_path),
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
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input="y\nn\n", text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr

    out = proc.stdout
    assert "Public identity" not in out
    assert "Repo URL privacy mode" not in out
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
    assert "graphs" in out
