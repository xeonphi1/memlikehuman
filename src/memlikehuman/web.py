"""Loopback-only offline dashboard. No outbound requests, CDN, or provider objects."""

import hmac
import json
import secrets
import sqlite3
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from .archive import write_archive
from .dashboard import Dashboard
from .models import Scope
from .store import Store

MAX_UPLOAD = 64 * 1024 * 1024
ASSETS = Path(__file__).with_name("web_assets")


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, data_dir: Path, port: int = 0):
        self.dashboard = Dashboard(data_dir)
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: WebServer

    def log_message(self, *args):
        pass  # Transcripts, query strings, and credentials never enter HTTP logs.

    def reply(
        self, status: int, data: bytes, kind="application/json; charset=utf-8", filename=None
    ):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self, post=False):
        try:
            if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
                return self.reply(403, b'{"error":"Invalid host"}')
            origin = self.headers.get("Origin")
            if origin and origin != self.server.origin:
                return self.reply(403, b'{"error":"Cross-origin request denied"}')
            url = urlsplit(self.path)
            if not post and url.path in ("/", "/app.js", "/style.css"):
                name, kind = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                }[url.path]
                return self.reply(200, (ASSETS / name).read_bytes(), kind)
            if not hmac.compare_digest(
                self.headers.get("X-MemLikeHuman-Token", ""), self.server.token
            ):
                return self.reply(403, b'{"error":"Open the URL printed by memlikehuman web"}')
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            library = query.get("library", "main")
            scope = Scope(
                persona_id=query.get("persona", "default"),
                project_id=query.get("project", "default"),
            )
            dashboard = self.server.dashboard
            if post:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > MAX_UPLOAD:
                    return self.reply(413, b'{"error":"Upload must be between 1 byte and 64 MiB"}')
                self.connection.settimeout(30)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("Incomplete upload")
                if url.path == "/api/import":
                    result = dashboard.import_file(raw, query.get("name", "导入的记忆库"))
                elif url.path == "/api/edit":
                    payload = json.loads(raw)
                    result = dashboard.mutate(library, scope, payload["action"], payload["payload"])
                else:
                    return self.reply(404, b'{"error":"Not found"}')
            elif url.path == "/api/overview":
                result = dashboard.overview(library)
            elif url.path == "/api/list":
                result = dashboard.browse(
                    library,
                    scope,
                    query.get("layer", "events"),
                    query.get("q", ""),
                    int(query.get("page", "0")),
                )
            elif url.path == "/api/detail":
                result = dashboard.detail(library, scope, query["layer"], query["id"])
            elif url.path == "/api/export":
                fmt = query.get("format", "json")
                if fmt not in ("json", "jsonl", "sqlite3"):
                    raise ValueError("Unknown export format")
                store = Store(dashboard.directory(library))
                with tempfile.TemporaryDirectory(prefix="mlh-export-") as tmp:
                    path = Path(tmp) / ("memlikehuman." + fmt)
                    if fmt == "sqlite3":
                        store.backup(path)
                    else:
                        write_archive(path, store.export())
                    return self.reply(200, path.read_bytes(), "application/octet-stream", path.name)
            else:
                return self.reply(404, b'{"error":"Not found"}')
            self.reply(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
        except ValidationError:
            self.reply(400, b'{"error":"Invalid fields or unsupported values. Check the form."}')
        except (
            ValueError,
            KeyError,
            TypeError,
            OSError,
            sqlite3.Error,
            StopIteration,
            OverflowError,
        ):
            self.reply(
                400,
                json.dumps(
                    {
                        "error": "操作未完成：请检查格式、来源、分区及记录是否已被修改。现有记忆库不会被导入覆盖。"
                    },
                    ensure_ascii=False,
                ).encode(),
            )

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch(post=True)


def serve(data_dir: Path, port: int = 0, open_browser: bool = True):
    server = WebServer(data_dir, port)
    url = server.origin + "/#token=" + server.token
    print(f"MemLikeHuman · Offline dashboard\n{url}\nPress Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
