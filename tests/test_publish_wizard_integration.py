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

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    up = cfg.get("upload_config") or {}
    assert up.get("publisher") == "Alice"
    pid = up.get("publisher_identity") or {}
    assert pid.get("kind") == "user_provided"
    assert pid.get("value") == "Alice"
    assert bool(pid.get("verified", False)) is False
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
    assert (payload.get("publisher") or {}).get("kind") == "user_provided"
    assert bool((payload.get("publisher") or {}).get("verified", False)) is False
    llm2 = payload.get("llm_coding") or {}
    assert (llm2.get("started_at") or {}).get("value") == "2023-06"
    assert (llm2.get("dominant_at") or {}).get("value") == "2024-02-15"
    assert llm2.get("primary_tool_initial") == "github_copilot"
    assert llm2.get("primary_tool_current") == "cursor"

    assert "repos" not in payload
    assert "privacy" not in payload

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
    techs = rows[0].get("technologies") or []
    assert techs and isinstance(techs, list)
    assert {t.get("technology") for t in techs} == {"Other"}


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
            "publisher_token_path": str(token_path),
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
    assert "Public identity" not in out
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


def test_publish_wizard_supports_verified_github_username(tmp_path: Path) -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/v1/uploads":
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
            "github",
            "trailo",
            str(token_path),
            "unknown",
            "unknown",
            "none",
            "none",
            "y",
        ]
    )
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, input=answers, text=True, capture_output=True)
    server.shutdown()
    assert proc.returncode == 0, proc.stderr

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    up = cfg.get("upload_config") or {}
    pid = up.get("publisher_identity") or {}
    assert pid.get("kind") == "github_username"
    assert pid.get("value") == "trailo"
    assert bool(pid.get("verified", False)) is True

    payload = received.get("payload") or {}
    pub = payload.get("publisher") or {}
    assert pub.get("kind") == "github_username"
    assert pub.get("value") == "trailo"
    assert bool(pub.get("verified", False)) is True
