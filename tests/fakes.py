"""Test doubles: a fake seller panel, a Selenium-like stub driver and a fake SMTP server."""
from __future__ import annotations

import base64
import http.server
import re
import socketserver
import threading
import urllib.request
from email import message_from_bytes, policy

SELLERS: dict[str, tuple[str | None, str] | None] = {
    "1001": ("ali@shop.ir", "فروشگاه علی"),
    "1002": ("sara@shop.ir", "فروشگاه سارا"),
    "1003": (None, "فقط نام تجاری"),
    "1004": None,
    "1005": ("reza@shop.ir", "لوازم خانگی رضا"),
    "1006": ("mina@shop.ir", "پوشاک مینا"),
    "1007": ("omid@shop.ir", "کتاب امید"),
    "1008": ("nazanin@shop.ir", "گالری نازنین"),
}


class Panel:
    """Local HTTP panel. While `logged_in` is False every page redirects to /login."""

    def __init__(self, sellers: dict | None = None, require_login: bool = False):
        self.sellers = sellers if sellers is not None else SELLERS
        self.logged_in = not require_login
        panel = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0]
                if path == "/__login":  # demo helper: pretend the user logged in
                    panel.logged_in = True
                    body = "ok"
                elif path.startswith("/login"):
                    body = "<html><body><form><input name=user><input name=pass type=password></form></body></html>"
                elif not panel.logged_in:
                    self.send_response(302)
                    self.send_header("Location", "/login?next=" + path)
                    self.end_headers()
                    return
                else:
                    sid = path.strip("/").split("/")[-1]
                    rec = panel.sellers.get(sid)
                    if rec is None:
                        body = "<html><body><h1>یافت نشد</h1></body></html>"
                    else:
                        email, name = rec
                        fields = f'<input name="business_name_fa" value="{name}">'
                        if email:
                            fields = f'<input name="email" value="{email}">' + fields
                        body = f"<html><body><form>{fields}</form></body></html>"
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/marketplace/sellers/item/{{id}}/"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


_ATTR_SEL = re.compile(r'^(?P<tag>[a-z]+)?\[(?P<attr>[\w\-]+)=["\']?(?P<val>[^"\'\]]+)["\']?\]$')


class StubElement:
    def __init__(self, attrs: dict[str, str]):
        self.attrs = attrs

    @property
    def text(self) -> str:
        return ""

    def get_attribute(self, name: str) -> str:
        return self.attrs.get(name, "")


class StubDriver:
    """Just enough of selenium's WebDriver for the crawler."""

    def __init__(self, *_a, **_k):
        self.current_url = ""
        self.html = ""

    def get(self, url: str) -> None:
        with urllib.request.urlopen(url) as resp:  # follows the login redirect
            self.current_url = resp.geturl()
            self.html = resp.read().decode("utf-8")

    def find_elements(self, _by, selector: str):
        m = _ATTR_SEL.match(selector.strip())
        if not m:
            return []
        tag = m.group("tag") or r"[a-z]+"
        out = []
        for raw in re.findall(rf"<{tag}\b([^>]*)>", self.html):
            attrs = dict(re.findall(r'([\w\-]+)="([^"]*)"', raw))
            attrs.update({k: v for k, v in re.findall(r"([\w\-]+)=([^\s\"'>]+)", raw)})
            if attrs.get(m.group("attr")) == m.group("val"):
                out.append(StubElement(attrs))
        return out

    def find_element(self, by, selector):
        found = self.find_elements(by, selector)
        if not found:
            from selenium.common.exceptions import NoSuchElementException
            raise NoSuchElementException(selector)
        return found[0]

    def set_page_load_timeout(self, _t):
        pass

    def quit(self):
        pass


def stub_factory(_cfg):
    return StubDriver()


class FakeSMTP:
    """Plain SMTP (no TLS) server that accepts AUTH PLAIN/LOGIN and records messages."""

    def __init__(self, username: str = "user", password: str = "secret", reject: set[str] | None = None):
        self.messages: list = []
        self.username, self.password = username, password
        self.reject = reject or set()
        smtp = self

        class Handler(socketserver.StreamRequestHandler):
            def reply(self, line: str):
                self.wfile.write((line + "\r\n").encode())

            def handle(self):
                self.reply("220 fake ESMTP ready")
                authed = False
                rcpts: list[str] = []
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    cmd = line.split(" ", 1)[0].upper()
                    if cmd in ("EHLO", "HELO"):
                        self.wfile.write(b"250-fake\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
                    elif cmd == "AUTH":
                        parts = line.split()
                        if parts[1].upper() == "PLAIN":
                            token = parts[2] if len(parts) > 2 else ""
                            if not token:
                                self.reply("334 ")
                                token = self.rfile.readline().decode().strip()
                            _, user, pw = base64.b64decode(token).decode().split("\x00")
                        else:
                            self.reply("334 VXNlcm5hbWU6")
                            user = base64.b64decode(self.rfile.readline().strip()).decode()
                            self.reply("334 UGFzc3dvcmQ6")
                            pw = base64.b64decode(self.rfile.readline().strip()).decode()
                        if user == smtp.username and pw == smtp.password:
                            authed = True
                            self.reply("235 ok")
                        else:
                            self.reply("535 bad credentials")
                    elif cmd == "MAIL":
                        if not authed:
                            self.reply("530 auth required")
                        else:
                            rcpts = []
                            self.reply("250 ok")
                    elif cmd == "RCPT":
                        addr = re.search(r"<([^>]*)>", line).group(1)
                        if addr in smtp.reject:
                            self.reply("550 no such user")
                        else:
                            rcpts.append(addr)
                            self.reply("250 ok")
                    elif cmd == "DATA":
                        self.reply("354 go")
                        chunks = []
                        while True:
                            data_line = self.rfile.readline()
                            if data_line in (b".\r\n", b".\n", b""):
                                break
                            if data_line.startswith(b".."):
                                data_line = data_line[1:]
                            chunks.append(data_line)
                        msg = message_from_bytes(b"".join(chunks), policy=policy.default)
                        smtp.messages.append({"rcpts": rcpts, "msg": msg})
                        self.reply("250 queued")
                    elif cmd == "RSET":
                        rcpts = []
                        self.reply("250 ok")
                    elif cmd == "NOOP":
                        self.reply("250 ok")
                    elif cmd == "QUIT":
                        self.reply("221 bye")
                        return
                    else:
                        self.reply("502 not implemented")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
