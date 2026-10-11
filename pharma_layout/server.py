"""Tiny stdlib HTTP server: serves the UI and a JSON API. Binds to localhost only by default.

  GET  /              the single-page UI
  GET  /api/example   the synthetic demo spec
  GET  /api/capabilities   {cpsat: bool, ortools_version, reason}  (is the optional CP-SAT generator usable?)
  POST /api/run       body: spec JSON -> {ok, overall, html, generation, validation, notes}
                      invalid spec / JSON -> 400 {ok:false, errors:[...]}
                      unexpected internal error -> 500 {ok:false, errors:[...]} (never a dropped connection)
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import cpsat
from .pipeline import run_pipeline
from .report import CSS
from .spec import SpecError

PKG = Path(__file__).resolve().parent
EXAMPLE_PATH = PKG.parent / "examples" / "synthetic_osd_demo.json"
MAX_BODY = 1_000_000


def load_example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    server_version = "PharmaLayoutMVP/0.1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            page = (PKG / "static" / "index.html").read_text(encoding="utf-8").replace("/*__CSS__*/", CSS)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/example":
            self._json(200, load_example())
        elif self.path == "/api/capabilities":
            self._json(200, cpsat.capabilities())
        else:
            self._json(404, {"ok": False, "errors": ["not found"]})

    def do_POST(self):  # noqa: N802
        if self.path not in ("/api/run", "/api/alternatives"):
            return self._json(404, {"ok": False, "errors": ["not found"]})
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(400, {"ok": False, "errors": ["bad Content-Length"]})
        if n <= 0 or n > MAX_BODY:
            return self._json(400, {"ok": False, "errors": [f"body must be 1..{MAX_BODY} bytes"]})
        try:
            raw = json.loads(self.rfile.read(n).decode("utf-8"))
        except RecursionError:
            return self._json(400, {"ok": False, "errors": ["body is not valid input: JSON nesting is too deep"]})
        except ValueError as e:   # JSONDecodeError, UnicodeDecodeError and Python's integer-size limit are all ValueErrors
            return self._json(400, {"ok": False, "errors": [f"body is not valid JSON: {str(e)[:200]}"]})
        if self.path == "/api/alternatives":
            try:
                from .alternatives import build_alternatives, render_alternatives
                from .spec import validate_spec
                validate_spec(raw)          # reject bad input with the usual 400 before any solving
                a = build_alternatives(raw)
                return self._json(200, {"ok": True, "html": render_alternatives(a), "selected": a["selected"]["label"] if a["selected"] else None,
                                        "shown": [c["label"] for c in a["shown"]]})
            except SpecError as e:
                return self._json(400, {"ok": False, "errors": e.errors})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"ok": False, "errors": [f"internal error ({type(e).__name__}); this is a bug, not a verdict on your input"]})
        try:
            res = run_pipeline(raw)
        except SpecError as e:
            return self._json(400, {"ok": False, "errors": e.errors})
        except Exception as e:  # noqa: BLE001 - last resort: answer instead of dropping the connection
            return self._json(500, {"ok": False, "errors": [f"internal error ({type(e).__name__}); this is a bug, not a verdict on your input"]})
        self._json(200, {"ok": True, "overall": res["validation"]["overall"], "html": res["html"],
                         "generation": res["generation"], "validation": res["validation"], "notes": res["notes"]})

    def log_message(self, fmt, *args):  # quieter console
        pass


def make_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    srv = make_server(host, port)
    print(f"Pharma layout MVP running at http://{host}:{srv.server_address[1]}/  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
