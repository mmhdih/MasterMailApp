"""Rendering personalised messages and sending them over SMTP."""
from __future__ import annotations

import html
import mimetypes
import os
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Any

from .textutil import jalali_month_label, jalali_today, norm_key, to_fa_digits

PLACEHOLDER_RE = re.compile(r"\{\{?\s*([^{}\n]{1,60}?)\s*\}?\}")

BUILTIN_PLACEHOLDERS = [
    {"key": "seller_name", "label": "نام فروشنده"},
    {"key": "seller_id", "label": "شناسه فروشنده"},
    {"key": "email", "label": "ایمیل"},
    {"key": "date", "label": "تاریخ امروز"},
    {"key": "month", "label": "ماه جاری"},
    {"key": "row_count", "label": "تعداد ردیف فایل"},
    {"key": "file_name", "label": "نام فایل پیوست"},
    {"key": "sender_name", "label": "نام فرستنده"},
]

ALIASES = {
    "seller name": "seller_name", "name": "seller_name", "نام فروشنده": "seller_name", "نام": "seller_name",
    "seller id": "seller_id", "id": "seller_id", "شناسه": "seller_id", "شناسه فروشنده": "seller_id",
    "ایمیل": "email", "تاریخ": "date", "ماه": "month",
}


class MailError(Exception):
    pass


def build_context(recipient: dict, *, sender_name: str = "", attachment: str = "") -> dict[str, str]:
    ctx: dict[str, str] = {}
    for key, value in (recipient.get("fields") or {}).items():
        ctx[norm_key(key)] = "" if value is None else str(value)
    base = {
        "seller_name": recipient.get("name") or "",
        "seller_id": recipient.get("seller_id") or "",
        "email": recipient.get("email") or "",
        "date": jalali_today(),
        "month": jalali_month_label(),
        "row_count": to_fa_digits(recipient.get("row_count") or "") if recipient.get("row_count") else "",
        "file_name": os.path.basename(attachment) if attachment else "",
        "sender_name": sender_name,
    }
    for key, value in base.items():
        ctx[norm_key(key)] = str(value)
    return ctx


def render(template: str, ctx: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = norm_key(match.group(1))
        key = norm_key(ALIASES.get(key, key))
        if key in ctx:
            return ctx[key]
        return match.group(0)

    return PLACEHOLDER_RE.sub(repl, template or "")


def unknown_placeholders(template: str, ctx: dict[str, str]) -> list[str]:
    missing = []
    for match in PLACEHOLDER_RE.finditer(template or ""):
        key = norm_key(ALIASES.get(norm_key(match.group(1)), match.group(1)))
        if key not in ctx and match.group(1) not in missing:
            missing.append(match.group(1))
    return missing


_URL_RE = re.compile(r"(https?://[^\s<]+)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def text_to_html(body: str, signature: str = "") -> str:
    """Plain text with blank-line paragraphs -> a clean RTL HTML email."""
    def para(block: str) -> str:
        escaped = html.escape(block)
        escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
        escaped = _URL_RE.sub(r'<a href="\1" style="color:#0A84FF">\1</a>', escaped)
        lines = escaped.split("\n")
        if all(re.match(r"^\s*[-•▪]\s+", ln) for ln in lines if ln.strip()) and len(lines) > 1:
            items = "".join(f"<li>{re.sub(r'^\s*[-•▪]\s+', '', ln)}</li>" for ln in lines if ln.strip())
            return f'<ul style="margin:0 0 14px;padding-right:20px">{items}</ul>'
        return f'<p style="margin:0 0 14px">{"<br>".join(lines)}</p>'

    blocks = [b for b in re.split(r"\n\s*\n", (body or "").strip()) if b.strip()]
    content = "".join(para(b) for b in blocks)
    if signature.strip():
        sig = "<br>".join(html.escape(ln) for ln in signature.strip().split("\n"))
        content += f'<div style="margin-top:22px;padding-top:14px;border-top:1px solid #E5E5EA;color:#6E6E73;font-size:13px">{sig}</div>'
    return (
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:0;background:#ffffff">'
        '<div dir="rtl" style="direction:rtl;text-align:right;font-family:Vazirmatn,Tahoma,\'Segoe UI\',Arial,sans-serif;'
        'font-size:14px;line-height:1.9;color:#1D1D1F;max-width:640px;padding:8px 4px">'
        f"{content}</div></body></html>"
    )


def build_message(*, from_addr: str, from_name: str, to_addr: str, subject: str, body: str,
                  html_body: str | None = None, attachments: list[str] | None = None,
                  reply_to: str = "", bcc: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_addr)) if from_name else from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1] if "@" in from_addr else None)
    if reply_to:
        msg["Reply-To"] = reply_to
    if bcc:
        msg["Bcc"] = bcc
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    for path in attachments or []:
        ctype, _ = mimetypes.guess_type(path)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        data = Path(path).read_bytes()
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=os.path.basename(path))
    return msg


def recipients_of(to_addr: str) -> list[str]:
    return [p.strip() for p in to_addr.split(",") if p.strip()]


class SmtpSession:
    """One authenticated connection reused for many messages; reconnects on drop."""

    def __init__(self, host: str, port: int, username: str, password: str,
                 security: str = "starttls", timeout: int = 60):
        self.host, self.port = host, int(port)
        self.username, self.password = username, password
        self.security = security
        self.timeout = timeout
        self._server: smtplib.SMTP | None = None

    def connect(self) -> None:
        self.close()
        context = ssl.create_default_context()
        try:
            if self.security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                server.ehlo()
                if self.security == "starttls":
                    server.starttls(context=context)
                    server.ehlo()
            if self.password:
                server.login(self.username, self.password)
        except smtplib.SMTPAuthenticationError as exc:
            raise MailError("نام کاربری یا رمز عبور ایمیل اشتباه است.") from exc
        except (socket.gaierror, ConnectionRefusedError) as exc:
            raise MailError(f"اتصال به سرور {self.host}:{self.port} برقرار نشد. آدرس و پورت را بررسی کنید.") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise MailError(f"سرور {self.host} پاسخ نداد (Timeout). شبکه یا VPN را بررسی کنید.") from exc
        except ssl.SSLError as exc:
            raise MailError(f"خطای رمزنگاری: {exc}. نوع امنیت اتصال را در تنظیمات تغییر دهید.") from exc
        except smtplib.SMTPNotSupportedError as exc:
            raise MailError("سرور از STARTTLS پشتیبانی نمی‌کند؛ نوع امنیت اتصال را تغییر دهید.") from exc
        except smtplib.SMTPException as exc:
            raise MailError(f"خطای سرور ایمیل: {exc}") from exc
        except OSError as exc:
            raise MailError(f"اتصال به سرور ناموفق بود: {exc}") from exc
        self._server = server

    def send(self, msg: EmailMessage) -> None:
        for attempt in (1, 2):
            if self._server is None:
                self.connect()
            try:
                assert self._server is not None
                refused = self._server.send_message(msg)
                if refused:
                    raise MailError("سرور این گیرنده را نپذیرفت: " + ", ".join(refused))
                return
            except smtplib.SMTPRecipientsRefused as exc:
                raise MailError("آدرس گیرنده توسط سرور رد شد.") from exc
            except smtplib.SMTPSenderRefused as exc:
                raise MailError(f"سرور اجازه ارسال از این آدرس را نداد: {exc.smtp_error!r}") from exc
            except smtplib.SMTPDataError as exc:
                raise MailError(f"سرور پیام را نپذیرفت ({exc.smtp_code}).") from exc
            except (smtplib.SMTPServerDisconnected, ConnectionResetError, BrokenPipeError, socket.timeout):
                self._server = None
                if attempt == 2:
                    raise MailError("ارتباط با سرور ایمیل قطع شد.")

    def close(self) -> None:
        if self._server is not None:
            try:
                self._server.quit()
            except Exception:  # noqa: BLE001
                pass
            self._server = None

    def __enter__(self) -> "SmtpSession":
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def read_docx(path: str) -> str:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise MailError("برای خواندن فایل Word بسته python-docx لازم است.") from exc
    try:
        doc = Document(path)
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"فایل Word باز نشد: {exc}") from exc
    paragraphs = [p.text.strip() for p in doc.paragraphs]
    text = "\n\n".join(p for p in paragraphs if p)
    if not text:
        raise MailError("متن فایل Word خالی است.")
    return text
