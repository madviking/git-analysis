from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from git_analysis.upload_package_v1 import canonical_json_bytes


def test_upload_cli_uploads_existing_report_dir(tmp_path: Path) -> None:
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

    report_dir = tmp_path / "reports" / "x" / "y"
    (report_dir / "json").mkdir(parents=True)
    (report_dir / "json" / "run_meta.json").write_text(
        json.dumps({"include_merges": False, "include_bootstraps": False, "dedupe": "remote"}, indent=2) + "\n",
        encoding="utf-8",
    )

    payload = {
        "schema_version": "upload_package_v1",
        "generated_at": "2025-01-01T00:00:00Z",
        "toolkit_version": "0.1.0",
        "data_scope": "me",
        "publisher": {"kind": "user_provided", "value": "Alice"},
        "periods": [{"label": "2025", "start": "2025-01-01", "end": "2026-01-01"}],
        "weekly": {"definition": {"bucket": "week_start_monday_00_00_00Z", "timestamp_source": "author_time"}, "series_by_period": {}},
        "year_totals": [{"year": 2025, "totals": {"commits": 0, "insertions": 0, "deletions": 0, "changed": 0}}],
    }
    payload_bytes = canonical_json_bytes(payload)
    (report_dir / "json" / "upload_package_v1.json").write_bytes(payload_bytes)

    token_path = tmp_path / "publisher_token"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"upload_config": {"api_url": f"http://127.0.0.1:{server.server_port}", "publisher_token_path": str(token_path)}}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str((Path(__file__).resolve().parents[1] / "src"))
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        "-m",
        "git_analysis.cli",
        "upload",
        "--report-dir",
        str(report_dir),
        "--config",
        str(config_path),
        "--yes",
    ]
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, text=True, capture_output=True)
    server.shutdown()
    assert proc.returncode == 0, proc.stderr

    payload2 = received.get("payload") or {}
    assert payload2.get("schema_version") == "upload_package_v1"
