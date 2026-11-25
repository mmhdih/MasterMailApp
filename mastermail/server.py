"""Local HTTP API + static UI server (127.0.0.1 only, token protected)."""
from __future__ import annotations

import json
import mimetypes
import queue
import re
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from .paths import resource
from .service import Service, UserError

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")

Handler = Callable[..., Any]


class Router:
    def __init__(self) -> None:
        self.routes: list[tuple[str, re.Pattern, Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        self.routes.append((method, re.compile("^" + pattern + "$"), handler))

    def match(self, method: str, path: str):
        for m, rx, handler in self.routes:
            if m == method:
                found = rx.match(path)
                if found:
                    return handler, found.groupdict()
        return None, None


def build_router(svc: Service) -> Router:
    r = Router()
    j = lambda body: body or {}  # noqa: E731

    r.add("GET", "/api/state", lambda q, b: svc.state())
    r.add("POST", "/api/settings", lambda q, b: svc.update_settings(j(b)))
    r.add("POST", "/api/smtp/test", lambda q, b: svc.test_smtp())
    r.add("POST", "/api/file/inspect", lambda q, b: svc.inspect_file(j(b)))
    r.add("POST", "/api/file/docx", lambda q, b: svc.import_docx(j(b).get("file_id", "")))
    r.add("POST", "/api/ids/parse", lambda q, b: __import__("mastermail.ids", fromlist=["x"]).parse_ids(j(b).get("text", "")).to_dict())
    r.add("POST", "/api/open", lambda q, b: svc.open_path(j(b).get("path", ""), bool(j(b).get("reveal"))))
    r.add("POST", "/api/dialog/folder", lambda q, b: {"path": svc.choose_folder(j(b).get("title", ""))})
    r.add("GET", "/api/templates", lambda q, b: svc.templates())
    r.add("POST", "/api/compose/smart", lambda q, b: svc.smart_compose(j(b)))
    r.add("POST", "/api/compose/ai", lambda q, b: svc.ai_draft(j(b)))

    r.add("GET", "/api/jobs", lambda q, b: svc.jobs.list())
    r.add("GET", "/api/jobs/(?P<jid>[\\w\\-]+)", lambda q, b, jid: _job(svc, jid))
    r.add("POST", "/api/jobs/(?P<jid>[\\w\\-]+)/(?P<action>[\\w\\-]+)",
          lambda q, b, jid, action: {"ok": svc.jobs.control(jid, action)})

    r.add("POST", "/api/crawl", lambda q, b: svc.start_crawl(j(b)))
    r.add("POST", "/api/split", lambda q, b: svc.start_split(j(b)))

    r.add("GET", "/api/sellers", lambda q, b: svc.sellers(q.get("q", ""), int(q.get("limit", 200)), int(q.get("offset", 0))))
    r.add("POST", "/api/sellers/import", lambda q, b: svc.import_sellers(j(b)))
    r.add("POST", "/api/sellers/export", lambda q, b: svc.export_sellers(j(b).get("ids")))
    r.add("POST", "/api/sellers/(?P<sid>[\\w\\-]+)", lambda q, b, sid: svc.update_seller(sid, j(b)))
    r.add("DELETE", "/api/sellers/(?P<sid>[\\w\\-]+)", lambda q, b, sid: svc.delete_seller(sid) or {"ok": True})

    r.add("GET", "/api/campaigns", lambda q, b: svc.list_campaigns())
    r.add("POST", "/api/campaigns", lambda q, b: svc.create_campaign(j(b)))
    c = "/api/campaigns/(?P<cid>[0-9a-f]+)"
    r.add("GET", c, lambda q, b, cid: svc.get_campaign(cid))
    r.add("PATCH", c, lambda q, b, cid: svc.update_campaign(cid, j(b)))
    r.add("DELETE", c, lambda q, b, cid: svc.delete_campaign(cid) or {"ok": True})
    r.add("POST", c + "/source", lambda q, b, cid: svc.set_source(cid, j(b)))
    r.add("POST", c + "/recipients/(?P<sid>[\\w\\-]+)", lambda q, b, cid, sid: svc.update_recipient(cid, sid, j(b)))
    r.add("POST", c + "/exclude", lambda q, b, cid: svc.bulk_exclude(cid, j(b)))
    r.add("POST", c + "/crawl", lambda q, b, cid: svc.crawl_campaign(cid, j(b)))
    r.add("POST", c + "/split", lambda q, b, cid: svc.prepare_split(cid, j(b)))
    r.add("POST", c + "/shared", lambda q, b, cid: svc.add_shared_attachment(cid, j(b).get("file_id", "")))
    r.add("DELETE", c + "/shared/(?P<fid>[0-9a-f]+)", lambda q, b, cid, fid: svc.remove_shared_attachment(cid, fid))
    r.add("POST", c + "/folder-files", lambda q, b, cid: svc.add_folder_files(cid, j(b).get("file_ids", [])))
    r.add("POST", c + "/preview", lambda q, b, cid: svc.preview(cid, j(b)))
    r.add("POST", c + "/test", lambda q, b, cid: svc.send_test(cid, j(b)))
    r.add("POST", c + "/send", lambda q, b, cid: svc.start_send(cid, j(b)))
    r.add("POST", c + "/report", lambda q, b, cid: svc.campaign_report(cid))
    r.add("GET", c + "/log", lambda q, b, cid: svc.campaign_log(cid))
    return r


def _job(svc: Service, jid: str) -> dict:
    job = svc.jobs.get(jid)
    if not job:
        raise UserError("کار پیدا نشد.")
    return job.snapshot(with_logs=True)


class AppServer:
    def __init__(self, svc: Service, host: str = "127.0.0.1", port: int = 0, token: str | None = None,
                 web_root: Path | None = None):
        self.svc = svc
        self.token = token or secrets.token_urlsafe(24)
        self.router = build_router(svc)
        self.web_root = (web_root or resource("web")).resolve()
        server = self

        class RequestHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            # -- helpers ---------------------------------------------------
            def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, status: int, data: Any) -> None:
                self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                           "application/json; charset=utf-8")

            def _authorised(self, query: dict) -> bool:
                return secrets.compare_digest(self.headers.get("X-Token", "") or query.get("t", ""), server.token)

            # -- verbs -----------------------------------------------------
            def do_GET(self) -> None:  # noqa: N802
                self._dispatch("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch("POST")

            def do_PATCH(self) -> None:  # noqa: N802
                self._dispatch("PATCH")

            def do_DELETE(self) -> None:  # noqa: N802
                self._dispatch("DELETE")

            def _dispatch(self, method: str) -> None:
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                path = url.path
                if not path.startswith("/api/"):
                    if method == "GET":
                        return self._static(path)
                    return self._json(405, {"error": "method not allowed"})
                if not self._authorised(query):
                    return self._json(401, {"error": "unauthorised"})
                if path == "/api/events":
                    return self._events()
                if path == "/api/upload" and method == "POST":
                    return self._upload(query)
                if path == "/api/download":
                    return self._download(query)
                handler, params = server.router.match(method, path)
                if handler is None:
                    return self._json(404, {"error": "not found"})
                body = None
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    try:
                        body = json.loads(self.rfile.read(length).decode("utf-8"))
                    except ValueError:
                        return self._json(400, {"error": "درخواست نامعتبر است."})
                try:
                    result = handler(query, body, **params)
                    self._json(200, result if result is not None else {"ok": True})
                except UserError as exc:
                    self._json(400, {"error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    self._json(500, {"error": f"خطای داخلی: {exc}"})

            def _upload(self, query: dict) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                name = unquote(query.get("name", "file"))
                data = self.rfile.read(length) if length else b""
                try:
                    self._json(200, server.svc.upload(name, data))
                except UserError as exc:
                    self._json(400, {"error": str(exc)})

            def _download(self, query: dict) -> None:
                target = Path(unquote(query.get("path", ""))).resolve()
                allowed = [server.svc.settings.workspace().resolve()]
                if not target.is_file() or not any(str(target).startswith(str(a)) for a in allowed):
                    return self._json(404, {"error": "فایل پیدا نشد."})
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                from urllib.parse import quote
                self._send(200, target.read_bytes(), ctype,
                           {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(target.name)}"})

            def _static(self, path: str) -> None:
                rel = unquote(path).lstrip("/") or "index.html"
                target = (server.web_root / rel).resolve()
                if not str(target).startswith(str(server.web_root)) or not target.is_file():
                    target = server.web_root / "index.html"
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                    ctype += "; charset=utf-8"
                self._send(200, target.read_bytes(), ctype)

            def _events(self) -> None:
                q = server.svc.bus.subscribe()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.close_connection = True
                try:
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            event = q.get(timeout=15)
                            payload = json.dumps(event, ensure_ascii=False, default=str)
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
                finally:
                    server.svc.bus.unsubscribe(q)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.httpd = Server((host, port), RequestHandler)
        self.host, self.port = self.httpd.server_address[:2]
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?t={self.token}"

    def start(self) -> "AppServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="http", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
