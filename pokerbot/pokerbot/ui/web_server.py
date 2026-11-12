"""Small local web interface (standard library only): play page + dashboard.

    python -m pokerbot web --port 8000   ->  http://localhost:8000
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..engine.actions import Action
from .dashboard import build_data
from .session import GameSession

WEB = Path(__file__).with_name("web")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8"}


class App:
    def __init__(self, default_opponents: list[str], seed: int | None = None) -> None:
        self.lock = threading.Lock()
        self.default = default_opponents
        self.seed = seed
        self.session: GameSession | None = None

    def new_session(self, opponents: list[str]) -> dict:
        if self.session:
            self.session.close()
        self.session = GameSession(opponents, seed=self.seed)
        self.session.new_hand()
        return self.session.snapshot()


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
            if path == "/api/state":
                with app.lock:
                    return self._json(app.session.snapshot() if app.session else {"phase": "idle"})
            if path == "/api/dashboard":
                return self._json(build_data())
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "JSON invalide"}, 400)
            try:
                with app.lock:
                    if self.path == "/api/new_session":
                        return self._json(app.new_session(body.get("opponents") or app.default))
                    if app.session is None:
                        app.new_session(app.default)
                    s = app.session
                    if self.path == "/api/new_hand":
                        s.new_hand()
                        return self._json(s.snapshot())
                    if self.path == "/api/act":
                        t = body.get("type")
                        action = {"fold": Action.fold, "check": Action.check, "call": Action.call}.get(t)
                        action = action() if action else Action.raise_to(int(body.get("amount", 0)))
                        s.act(action)
                        return self._json(s.snapshot())
            except Exception as e:  # report engine errors (illegal action...) to the page
                return self._json({"error": str(e)}, 400)
            self._json({"error": "not found"}, 404)

        def _file(self, f: Path) -> None:
            self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

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
