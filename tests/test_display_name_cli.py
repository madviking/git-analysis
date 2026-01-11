from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from git_analysis.publish import pseudonym_for_token
from git_analysis.upload_package_v1 import ensure_publisher_token


def test_display_name_cli_can_reset_to_pseudonym(tmp_path: Path) -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/v1/me/display-name":
                self.send_response(404)
                self.end_headers()
                return
            token = self.headers.get("X-Publisher-Token")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received["token"] = token
            received["body"] = body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"slug":"abc","display_name":"x","updated_at":"2026-01-07T00:00:00Z"}')

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    token_path = tmp_path / "publisher_token"
    token = ensure_publisher_token(token_path)
    expected = pseudonym_for_token(token)

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
        "display-name",
        "--config",
        str(config_path),
        "--pseudonym",
    ]
    proc = subprocess.run(cmd, cwd=str(tmp_path), env=env, text=True, capture_output=True)
    server.shutdown()
    assert proc.returncode == 0, proc.stderr
    assert "Publisher token (local secret):" in proc.stdout
    assert str(token_path) in proc.stdout
    assert "local secret" in proc.stdout
    assert f"API POST http://127.0.0.1:{server.server_port}/api/v1/me/display-name" in proc.stdout
    assert f'{{"display_name":"{expected}"}}' in proc.stdout

    obj = json.loads((received.get("body") or b"").decode("utf-8"))
    assert obj.get("display_name") == expected
    assert received.get("token") == token
