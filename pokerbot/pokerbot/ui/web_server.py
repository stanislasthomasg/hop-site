"""Small local web interface (standard library only): play page + dashboard.

    python -m pokerbot web --port 8000   ->  http://localhost:8000

``App`` holds the game API. The same object runs inside the browser in the
static-site build (see site_builder.py), so both share one code path.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..engine.actions import Action
from .session import GameSession

WEB = Path(__file__).with_name("web")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8"}


class App:
    """Game API shared by the local server and the browser build (Pyodide)."""

    def __init__(self, default_opponents: list[str], seed: int | None = None, db=None) -> None:
        self.lock = threading.Lock()
        self.default = default_opponents
        self.seed = seed
        self.db = db
        self.session: GameSession | None = None

    def new_session(self, opponents: list[str]) -> dict:
        if self.session:
            self.session.close()
        self.session = GameSession(opponents, seed=self.seed, db=self.db)
        self.session.new_hand()
        return self.session.snapshot()

    def handle(self, path: str, body: dict | None) -> tuple[int, dict]:
        """GET when ``body`` is None, POST otherwise. Returns (status, JSON object)."""
        with self.lock:
            try:
                if body is None:
                    if path == "/api/state":
                        return 200, (self.session.snapshot() if self.session else {"phase": "idle"})
                    if path == "/api/dashboard":
                        from .dashboard import build_data
                        return 200, build_data()
                    return 404, {"error": "not found"}
                if path == "/api/new_session":
                    return 200, self.new_session(body.get("opponents") or self.default)
                if self.session is None:
                    self.new_session(self.default)
                s = self.session
                if path == "/api/new_hand":
                    s.new_hand()
                    return 200, s.snapshot()
                if path == "/api/act":
                    t = body.get("type")
                    action = {"fold": Action.fold, "check": Action.check, "call": Action.call}.get(t)
                    s.act(action() if action else Action.raise_to(int(body.get("amount", 0))))
                    return 200, s.snapshot()
                return 404, {"error": "not found"}
            except Exception as e:  # illegal action, not your turn...: shown on the page
                return 400, {"error": str(e)}

    def handle_json(self, path: str, body_json: str | None) -> str:
        """String-in/string-out wrapper used from JavaScript in the browser build."""
        code, obj = self.handle(path, None if body_json is None else json.loads(body_json or "{}"))
        return json.dumps({"status": code, "body": obj})


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _file(self, f: Path) -> None:
            self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/play"):
                return self._file(WEB / "play.html")
            if path == "/dashboard":
                return self._file(WEB / "dashboard.html")
            if path.startswith("/static/"):
                f = (WEB / path[len("/static/"):]).resolve()
                if f.parent == WEB.resolve() and f.exists():
                    return self._file(f)
            if path.startswith("/api/"):
                code, obj = app.handle(path, None)
                return self._json(obj, code)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "JSON invalide"}, 400)
            code, obj = app.handle(self.path, body)
            self._json(obj, code)

    return Handler


def serve(port: int = 8000, opponents: list[str] | None = None, seed: int | None = None,
          host: str = "127.0.0.1") -> None:
    app = App(opponents or ["bot:best"], seed)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"pokerbot web: http://{host}:{port}  (Ctrl+C pour arrêter)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
