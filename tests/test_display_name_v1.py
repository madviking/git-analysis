from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from git_analysis.upload_package_v1 import update_display_name_v1


def test_update_display_name_posts_token_and_json() -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/v1/me/display-name":
                self.send_response(404)
                self.end_headers()
                return
            received["token"] = self.headers.get("X-Publisher-Token")
            received["ctype"] = self.headers.get("Content-Type")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received["body"] = body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"slug":"abc","display_name":"New Name","updated_at":"2026-01-07T00:00:00Z"}')

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        resp = update_display_name_v1(
            api_url=f"http://127.0.0.1:{server.server_port}",
            publisher_token="tok123",
            display_name=" New Name ",
            timeout_s=5,
        )
    finally:
        server.shutdown()

    assert received.get("token") == "tok123"
    assert str(received.get("ctype") or "").startswith("application/json")
    obj = json.loads((received.get("body") or b"").decode("utf-8"))
    assert obj["display_name"] == "New Name"
    assert resp.get("slug") == "abc"
    assert resp.get("display_name") == "New Name"


def test_update_display_name_raises_on_404() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not_found","message":"no profile"}')

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with pytest.raises(RuntimeError):
            update_display_name_v1(
                api_url=f"http://127.0.0.1:{server.server_port}",
                publisher_token="tok123",
                display_name="Name",
                timeout_s=5,
            )
    finally:
        server.shutdown()

