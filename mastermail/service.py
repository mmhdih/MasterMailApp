"""Application service: everything the UI can ask for, independent of HTTP."""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import APP_NAME, APP_NAME_FA, APP_TAGLINE, POWERED_BY, __version__
from .ai import AIError, draft_email
from .crawler import CrawlAborted, CrawlConfig, Crawler, CrawlResult
from .db import Database
from .ids import normalise_id, parse_ids
from .jobs import Job, JobManager
from .mailer import (BUILTIN_PLACEHOLDERS, MailError, SmtpSession, build_context, build_message,
                     read_docx, recipients_of, render, text_to_html, unknown_placeholders)
from .naming import safe_filename
from .paths import uploads_dir
from .settings import Settings
from .splitter import SplitCancelled, group_rows, split_table
from .tabular import (SUPPORTED_SUFFIXES, Table, TableError, describe_columns, detect_columns,
                      read_table, sheet_names, write_table)
from .templates import TEMPLATES, smart_compose
from .textutil import cell_text, clean_email, is_valid_email


class UserError(Exception):
    """A problem the user can fix; the message is shown as-is."""


ATTACH_NONE, ATTACH_SPLIT, ATTACH_SHARED, ATTACH_FOLDER = "none", "split", "shared", "folder"

CRAWL_SMART, CRAWL_FULL = "smart", "full"
SMART_CRAWLS = ("new", "no_email", "stale")   # what smart mode still fetches from the panel


def crawl_mode(payload: dict) -> str:
    mode = (payload or {}).get("mode")
    if mode in (CRAWL_SMART, CRAWL_FULL):
        return mode
    return CRAWL_FULL if (payload or {}).get("refresh") else CRAWL_SMART


class Service:
    def __init__(self, settings: Settings | None = None, db: Database | None = None,
                 jobs: JobManager | None = None,
                 driver_factory: Callable | None = None):
        self.settings = settings or Settings()
        self.db = db or Database()
        self.jobs = jobs or JobManager()
        self.bus = self.jobs.bus
        self.driver_factory = driver_factory
        self._lock = threading.RLock()
        self._campaigns: dict[str, dict] = {}
        self.native_dialogs: Callable[[str, dict], Any] | None = None  # set by the window shell

    # ==================================================================
    # app
    # ==================================================================
    def state(self) -> dict:
        return {
            "app": {"name": APP_NAME, "name_fa": APP_NAME_FA, "tagline": APP_TAGLINE,
                    "version": __version__, "powered_by": POWERED_BY, "platform": sys.platform,
                    "native_dialogs": self.native_dialogs is not None},
            "settings": self.settings.public(),
            "stats": self.db.stats(),
            "jobs": self.jobs.list(),
        }

    def update_settings(self, patch: dict) -> dict:
        secrets = patch.pop("secrets", None) or {}
        self.settings.update(patch)
        stored = {}
        for kind, value in secrets.items():
            stored[kind] = self.settings.set_secret(kind, value or "",
                                                    persist=self.settings.section("smtp").get("remember_password", True)
                                                    or kind != "smtp_password")
        data = self.settings.public()
        data["stored_in_keyring"] = stored
        self.bus.publish("settings", data)
        return data

    # ==================================================================
    # files
    # ==================================================================
    def upload(self, name: str, data: bytes) -> dict:
        suffix = Path(name).suffix.lower()
        if not name or len(data) == 0:
            raise UserError("فایل خالی است.")
        if len(data) > 200 * 1024 * 1024:
            raise UserError("حجم فایل بیش از ۲۰۰ مگابایت است.")
        file_id = uuid.uuid4().hex[:12]
        folder = uploads_dir() / file_id
        folder.mkdir(parents=True, exist_ok=True)
        stem = safe_filename(Path(name).stem) or "file"
        path = folder / f"{stem}{suffix}"
        path.write_bytes(data)
        return {"file_id": file_id, "name": name, "size": len(data), "path": str(path),
                "is_table": suffix in SUPPORTED_SUFFIXES}

    def file_path(self, file_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", file_id or ""):
            raise UserError("شناسه فایل نامعتبر است.")
        folder = uploads_dir() / file_id
        files = [p for p in folder.glob("*") if p.is_file()] if folder.is_dir() else []
        if not files:
            raise UserError("فایل بارگذاری‌شده پیدا نشد؛ دوباره بارگذاری کنید.")
        return files[0]

    def _resolve_table_path(self, payload: dict) -> Path:
        if payload.get("file_id"):
            return self.file_path(payload["file_id"])
        path = Path(payload.get("path") or "")
        if not path.is_file():
            raise UserError("فایل پیدا نشد.")
        return path

    def inspect_file(self, payload: dict) -> dict:
        path = self._resolve_table_path(payload)
        try:
            sheets = sheet_names(str(path))
            table = read_table(str(path), payload.get("sheet") or "", int(payload.get("header_row") or 1))
        except TableError as exc:
            raise UserError(str(exc)) from exc
        detected = detect_columns(table)
        columns = describe_columns(table)
        id_col = detected["id"]
        groups = 0
        repeated = False
        if id_col:
            values = [normalise_id(cell_text(r.get(id_col))) for r in table.rows]
            filled = [v for v in values if v]
            groups = len(set(filled))
            repeated = groups < len(filled)
        preview = [{h: cell_text(r.get(h)) for h in table.headers} for r in table.rows[:8]]
        return {
            "name": path.name, "sheets": sheets, "sheet": table.sheet, "headers": table.headers,
            "row_count": len(table.rows), "columns": columns, "detected": detected,
            "preview": preview, "id_groups": groups, "repeated_ids": repeated,
            "suggest_split": bool(id_col) and (repeated or len(table.headers) > 4),
        }

    def import_docx(self, file_id: str) -> dict:
        try:
            return {"body": read_docx(str(self.file_path(file_id)))}
        except MailError as exc:
            raise UserError(str(exc)) from exc

    def open_path(self, path: str, reveal: bool = False) -> bool:
        target = Path(path)
        if not target.exists():
            raise UserError("مسیر پیدا نشد.")
        if reveal and target.is_file():
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(target)])
                return True
            target = target.parent
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            raise UserError(f"باز کردن مسیر ممکن نشد: {exc}") from exc
        return True

    def choose_folder(self, title: str = "") -> str:
        if self.native_dialogs is None:
            raise UserError("انتخاب پوشه فقط در نسخه دسکتاپ در دسترس است؛ مسیر را دستی وارد کنید.")
        return self.native_dialogs("folder", {"title": title}) or ""

    def choose_file(self, title: str = "") -> str:
        if self.native_dialogs is None:
            raise UserError("انتخاب فایل فقط در نسخه دسکتاپ در دسترس است.")
        return self.native_dialogs("file", {"title": title}) or ""

    # ==================================================================
    # mail account
    # ==================================================================
    def _smtp_session(self) -> SmtpSession:
        smtp = self.settings.section("smtp")
        username = self.settings.smtp_username()
        password = self.settings.get_secret("smtp_password")
        if not smtp.get("host"):
            raise UserError("آدرس سرور ایمیل در تنظیمات وارد نشده است.")
        if not username:
            raise UserError("نام کاربری ایمیل در تنظیمات وارد نشده است.")
        if not password and smtp.get("security") != "none":
            raise UserError("رمز عبور ایمیل وارد نشده است. از «تنظیمات › حساب ایمیل» آن را وارد کنید.")
        return SmtpSession(smtp["host"], int(smtp["port"]), username, password,
                           smtp.get("security", "starttls"), int(smtp.get("timeout", 60)))

    def test_smtp(self) -> dict:
        session = self._smtp_session()
        started = time.monotonic()
        try:
            session.connect()
        except MailError as exc:
            raise UserError(str(exc)) from exc
        finally:
            session.close()
        return {"ok": True, "ms": int((time.monotonic() - started) * 1000),
                "username": session.username, "from": self.settings.from_address()}

    # ==================================================================
    # compose helpers
    # ==================================================================
    def templates(self) -> dict:
        return {"templates": TEMPLATES, "placeholders": BUILTIN_PLACEHOLDERS}

    def smart_compose(self, payload: dict) -> dict:
        return smart_compose(payload.get("brief", ""), tone=payload.get("tone", "formal"),
                             has_attachment=bool(payload.get("has_attachment")),
                             sender_name=self.settings.section("smtp").get("from_name", ""),
                             deadline=payload.get("deadline", ""))

    def ai_draft(self, payload: dict) -> dict:
        ai = self.settings.section("ai")
        key = self.settings.get_secret("anthropic_api_key")
        if not key:
            # No key: fall back to the offline writer so the button always helps.
            result = self.smart_compose(payload)
            result["offline"] = True
            return result
        try:
            result = draft_email(key, model=ai.get("model") or "claude-opus-5-5",
                                 brief=payload.get("brief", ""), tone=payload.get("tone", "formal"),
                                 has_attachment=bool(payload.get("has_attachment")),
                                 placeholders=payload.get("placeholders"),
                                 current_body=payload.get("current_body", ""))
        except AIError as exc:
            raise UserError(str(exc)) from exc
        result["offline"] = False
        return result

    # ==================================================================
    # seller directory
    # ==================================================================
    def sellers(self, q: str = "", limit: int = 200, offset: int = 0) -> dict:
        rows, total = self.db.search_sellers(q, limit, offset)
        return {"sellers": rows, "total": total, "counts": self.db.count_sellers()}

    def update_seller(self, seller_id: str, patch: dict) -> dict:
        email = clean_email(patch.get("email")) if "email" in patch else None
        if email and not is_valid_email(email):
            raise UserError("آدرس ایمیل معتبر نیست.")
        self.db.upsert_seller(seller_id, email=email, name=patch.get("name"), source="manual", status="manual")
        return self.db.get_seller(seller_id) or {}

    def delete_seller(self, seller_id: str) -> None:
        self.db.delete_seller(seller_id)

    def import_sellers(self, payload: dict) -> dict:
        path = self._resolve_table_path(payload)
        try:
            table = read_table(str(path), payload.get("sheet") or "")
        except TableError as exc:
            raise UserError(str(exc)) from exc
        cols = detect_columns(table)
        cols.update({k: v for k, v in (payload.get("columns") or {}).items() if v})
        if not cols["id"]:
            raise UserError("ستون شناسه فروشنده در فایل پیدا نشد.")
        added = 0
        for row in table.rows:
            sid = normalise_id(cell_text(row.get(cols["id"])))
            if not sid:
                continue
            email = clean_email(row.get(cols["email"])) if cols["email"] else None
            name = cell_text(row.get(cols["name"])) if cols["name"] else None
            if email and not is_valid_email(email):
                email = None
            if email or name:
                self.db.upsert_seller(sid, email=email, name=name, source="import", status="import")
                added += 1
        return {"imported": added, "columns": cols}

    def export_sellers(self, ids: list[str] | None = None) -> dict:
        if ids:
            found = self.db.get_sellers(ids)
            rows = [found.get(i, {"seller_id": i}) for i in ids]
        else:
            rows, _ = self.db.search_sellers("", limit=1_000_000)
        table = Table(["seller id", "seller name", "email", "وضعیت", "آخرین بروزرسانی"], [
            {"seller id": r.get("seller_id"), "seller name": r.get("name", ""), "email": r.get("email", ""),
             "وضعیت": _status_fa(r.get("status", "")),
             "آخرین بروزرسانی": _fmt_ts(r.get("updated_at"))}
            for r in rows
        ])
        folder = self.settings.workspace() / "Exports"
        path = folder / f"دفترچه آدرس {dt.datetime.now():%Y-%m-%d %H%M%S}.xlsx"
        write_table(path, table, "sellers", rtl=True)
        return {"path": str(path)}

    # ==================================================================
    # standalone crawler
    # ==================================================================
    def _crawl_config(self) -> CrawlConfig:
        return CrawlConfig.from_settings(self.settings.section("crawler"))

    # -- address book: what do we already know? --------------------------
    def book_status(self, ids: list[str]) -> tuple[dict[str, str], dict[str, dict]]:
        """Classify each id against the address book.

        fresh     saved with an email, newer than the validity period
        stale     saved with an email, but older than the validity period
        no_email  in the book, but no email was found last time
        new       never seen
        """
        cached = self.db.get_sellers(ids)
        max_age = max(0, int(self.settings.section("crawler").get("cache_days", 30))) * 86400
        now = time.time()
        status: dict[str, str] = {}
        for sid in ids:
            rec = cached.get(sid)
            if not rec:
                status[sid] = "new"
            elif not rec.get("email"):
                status[sid] = "no_email"
            elif max_age and now - (rec.get("updated_at") or 0) > max_age:
                status[sid] = "stale"
            else:
                status[sid] = "fresh"
        return status, cached

    @staticmethod
    def _plan(status: dict[str, str]) -> dict:
        counts = {k: 0 for k in ("fresh", "provided", "stale", "no_email", "new")}
        for s in status.values():
            counts[s] = counts.get(s, 0) + 1
        smart = sum(1 for s in status.values() if s in SMART_CRAWLS)
        return {"total": len(status), **counts, "smart": smart, "full": len(status),
                "cache_days": None}

    def _ids_from_payload(self, payload: dict) -> list[str]:
        if payload.get("file_id"):
            info = self.inspect_file(payload)
            col = payload.get("id_column") or info["detected"]["id"]
            if not col:
                raise UserError("ستون شناسه فروشنده در فایل پیدا نشد.")
            table = read_table(str(self.file_path(payload["file_id"])), payload.get("sheet") or "")
            ids = [normalise_id(cell_text(r.get(col))) for r in table.rows if cell_text(r.get(col))]
        elif payload.get("text"):
            ids = parse_ids(payload["text"]).ids
        else:
            ids = [normalise_id(i) for i in payload.get("ids", [])]
        return list(dict.fromkeys(i for i in ids if i))

    def crawl_plan(self, payload: dict) -> dict:
        ids = self._ids_from_payload(payload)
        plan = self._plan(self.book_status(ids)[0])
        plan["cache_days"] = int(self.settings.section("crawler").get("cache_days", 30))
        return plan

    def _ensure_no_crawl_running(self) -> None:
        if self.jobs.active("crawl"):
            raise UserError("یک کراول دیگر در حال اجراست؛ صبر کنید تا تمام شود یا آن را متوقف کنید.")

    def _store_crawl(self, result: CrawlResult) -> None:
        if result.email or result.name:
            self.db.upsert_seller(result.seller_id, email=result.email or "", name=result.name or "",
                                  source="crawl", status=result.status)
        elif not self.db.get_seller(result.seller_id):
            self.db.upsert_seller(result.seller_id, source="crawl", status=result.status)

    def start_crawl(self, payload: dict) -> dict:
        self._ensure_no_crawl_running()
        ids = self._ids_from_payload(payload)
        if not ids:
            raise UserError("هیچ شناسه فروشنده‌ای وارد نشده است.")
        mode = crawl_mode(payload)

        def work(job: Job) -> dict:
            status, cached = self.book_status(ids)
            todo = ids if mode == CRAWL_FULL else [i for i in ids if status[i] in SMART_CRAWLS]
            skipped = len(ids) - len(todo)
            if mode == CRAWL_FULL:
                job.log("info", f"کراول کامل: هر {len(ids)} فروشنده از نو از پنل خوانده می‌شوند.")
            elif skipped:
                job.log("info", f"کراول هوشمند: {skipped} فروشنده از دفترچه آدرس خوانده شد؛ {len(todo)} فروشنده کراول می‌شود.")
            for sid in ids:
                if sid not in todo and sid in cached:
                    job.item({"kind": "crawl", "seller_id": sid, "status": "cached",
                              "email": cached[sid].get("email", ""), "name": cached[sid].get("name", "")})
            summary = None
            if todo:
                crawler = Crawler(self._crawl_config(), job, self.driver_factory, on_result=self._store_crawl)
                try:
                    summary = crawler.run(todo)
                except CrawlAborted as exc:
                    raise UserError(str(exc)) from exc
            export = self.export_sellers(ids)
            found = self.db.get_sellers(ids)
            status = {r["seller_id"]: r["status"] for r in (summary.results if summary else [])}
            rows = [{"seller_id": i, "email": found.get(i, {}).get("email", ""), "name": found.get(i, {}).get("name", ""),
                     "status": status.get(i, "cached")} for i in ids]
            return {"ids": ids, "rows": rows, "crawled": len(todo), "cached": skipped, "mode": mode,
                    "ok": summary.ok if summary else 0, "partial": summary.partial if summary else 0,
                    "empty": summary.empty if summary else 0, "failed": summary.failed if summary else 0,
                    "export": export["path"]}

        title = f"کراول کامل {len(ids)} فروشنده" if mode == CRAWL_FULL else f"کراول هوشمند {len(ids)} فروشنده"
        job = self.jobs.start("crawl", title, work, {"ids": len(ids), "mode": mode})
        return job.snapshot()

    # ==================================================================
    # standalone splitter
    # ==================================================================
    def start_split(self, payload: dict) -> dict:
        path = self._resolve_table_path(payload)
        column = payload.get("column") or ""
        if not column:
            raise UserError("ستون مبنای جداسازی را انتخاب کنید.")
        try:
            table = read_table(str(path), payload.get("sheet") or "", int(payload.get("header_row") or 1))
        except TableError as exc:
            raise UserError(str(exc)) from exc
        out_dir = payload.get("output_dir") or str(
            self.settings.workspace() / "Splits" / f"{safe_filename(Path(payload.get('name') or path.name).stem)}-{dt.datetime.now():%Y%m%d-%H%M%S}"
        )

        def work(job: Job) -> dict:
            try:
                result = split_table(
                    table, column, out_dir,
                    output_format=payload.get("format", "xlsx"),
                    single_workbook=bool(payload.get("single_workbook")),
                    include_blanks=bool(payload.get("include_blanks", True)),
                    file_prefix=payload.get("prefix", ""), file_suffix=payload.get("suffix", ""),
                    progress=lambda d, t, label: job.progress(d, t, label),
                    cancel=job.stop_event, source_name=Path(payload.get("name") or path.name).stem,
                )
            except SplitCancelled:
                job.log("warn", "جداسازی لغو شد.")
                return {}
            except TableError as exc:
                raise UserError(str(exc)) from exc
            data = result.to_dict()
            job.log("ok", f"{data['file_count']} فایل از {data['row_count']} ردیف ساخته شد.")
            return data

        job = self.jobs.start("split", f"جداسازی {Path(payload.get('name') or path.name).name}", work)
        return job.snapshot()

    # ==================================================================
    # campaigns
    # ==================================================================
    def _campaign(self, cid: str) -> dict:
        with self._lock:
            if cid not in self._campaigns:
                data = self.db.get_campaign(cid)
                if not data:
                    raise UserError("کمپین پیدا نشد.")
                self._campaigns[cid] = data
            return self._campaigns[cid]

    def _save(self, campaign: dict, notify: bool = True) -> None:
        with self._lock:
            self.db.save_campaign(campaign)
        if notify:
            self.bus.publish("campaign", {"id": campaign["id"], "status": campaign.get("status")})

    def list_campaigns(self) -> list[dict]:
        items = self.db.list_campaigns()
        for c in items:
            c["recipient_count"] = c.get("stats", {}).get("total", 0)
        return items

    def create_campaign(self, payload: dict) -> dict:
        now = dt.datetime.now()
        cid = uuid.uuid4().hex[:10]
        name = (payload.get("name") or "").strip() or f"کمپین {now:%Y-%m-%d %H:%M}"
        campaign = {
            "id": cid, "name": name, "status": "draft", "step": 0,
            "source": {"mode": "ids", "text": "", "split": False},
            "recipients": [],
            "compose": {"subject": "", "body": "", "template_id": "", "tone": "formal"},
            "attachments": {"mode": ATTACH_NONE, "missing_policy": "skip", "split_format": "xlsx"},
            "sending": {"dry_run": False},
            "stats": {"total": 0, "sent": 0, "failed": 0, "skipped": 0},
            "workspace": "",
        }
        with self._lock:
            self._campaigns[cid] = campaign
        self._save(campaign)
        return campaign

    def get_campaign(self, cid: str) -> dict:
        campaign = self._campaign(cid)
        out = dict(campaign)
        out["attachment_status"] = self._attachment_status(campaign)
        out["readiness"] = self._readiness(campaign)
        return out

    def update_campaign(self, cid: str, patch: dict) -> dict:
        with self._lock:
            campaign = self._campaign(cid)
            for key in ("name", "step"):
                if key in patch:
                    campaign[key] = patch[key]
            for key in ("compose", "attachments", "sending"):
                if isinstance(patch.get(key), dict):
                    campaign.setdefault(key, {}).update(patch[key])
            self._save(campaign, notify=False)
        return self.get_campaign(cid)

    def delete_campaign(self, cid: str) -> None:
        with self._lock:
            self._campaigns.pop(cid, None)
        self.db.delete_campaign(cid)

    def _workspace_for(self, campaign: dict) -> Path:
        if campaign.get("workspace") and Path(campaign["workspace"]).is_dir():
            return Path(campaign["workspace"])
        stamp = dt.datetime.fromtimestamp(campaign.get("created_at") or time.time())
        path = self.settings.workspace() / "Campaigns" / f"{stamp:%Y-%m-%d} {safe_filename(campaign['name'])} [{campaign['id'][:4]}]"
        path.mkdir(parents=True, exist_ok=True)
        campaign["workspace"] = str(path)
        return path

    # -- step 1: source -> recipients -----------------------------------
    def set_source(self, cid: str, payload: dict) -> dict:
        mode = payload.get("mode", "ids")
        recipients: list[dict] = []
        source: dict[str, Any] = {"mode": mode}
        if mode == "ids":
            parsed = parse_ids(payload.get("text", ""))
            if not parsed.ids:
                raise UserError("هیچ شناسه فروشنده معتبری وارد نشده است.")
            source.update({"text": payload.get("text", ""), "split": False})
            recipients = [{"seller_id": sid, "name": "", "email": "", "row_count": 0, "fields": {}} for sid in parsed.ids]
        elif mode == "file":
            path = self.file_path(payload.get("file_id", ""))
            sheet = payload.get("sheet") or ""
            header_row = int(payload.get("header_row") or 1)
            try:
                table = read_table(str(path), sheet, header_row)
            except TableError as exc:
                raise UserError(str(exc)) from exc
            cols = detect_columns(table)
            cols.update({k: v for k, v in (payload.get("columns") or {}).items() if v is not None})
            if not cols.get("id"):
                raise UserError("ستون شناسه فروشنده را مشخص کنید.")
            groups = group_rows(table, cols["id"], include_blanks=False, as_id=True)
            for sid, rows in groups:
                first = rows[0]
                email = ""
                if cols.get("email"):
                    email = next((clean_email(r.get(cols["email"])) for r in rows if cell_text(r.get(cols["email"]))), "")
                name = cell_text(first.get(cols["name"])) if cols.get("name") else ""
                recipients.append({
                    "seller_id": sid, "name": name, "email": email if is_valid_email(email) else "",
                    "row_count": len(rows),
                    "fields": {h: cell_text(first.get(h)) for h in table.headers},
                    "origin": {"email": "file" if email else "", "name": "file" if name else ""},
                })
                if email and is_valid_email(email):
                    self.db.upsert_seller(sid, email=email, name=name or None, source="file", status="file")
            source.update({"file_id": payload["file_id"], "file_name": payload.get("file_name") or path.name,
                           "sheet": table.sheet, "header_row": header_row, "columns": cols,
                           "headers": table.headers, "rows": len(table.rows),
                           "split": bool(payload.get("split"))})
        else:
            raise UserError("نوع منبع نامعتبر است.")

        cached = self.db.get_sellers([r["seller_id"] for r in recipients])
        for r in recipients:
            r.setdefault("origin", {"email": "", "name": ""})
            r.update({"excluded": False, "status": "", "detail": "", "attachment": ""})
            rec = cached.get(r["seller_id"])
            if rec:
                if not r["email"] and rec.get("email"):
                    r["email"], r["origin"]["email"] = rec["email"], "directory"
                if not r["name"] and rec.get("name"):
                    r["name"], r["origin"]["name"] = rec["name"], "directory"

        with self._lock:
            campaign = self._campaign(cid)
            previous = campaign.get("source", {})
            campaign["source"] = source
            campaign["recipients"] = recipients
            campaign["stats"] = {"total": len(recipients), "sent": 0, "failed": 0, "skipped": 0}
            att = campaign.setdefault("attachments", {})
            if source.get("split"):
                att["mode"] = ATTACH_SPLIT
            elif att.get("mode") == ATTACH_SPLIT:
                att["mode"] = ATTACH_NONE
            if previous.get("file_id") != source.get("file_id"):
                att.pop("split_dir", None)
            campaign["status"] = "draft"
            self._save(campaign)
        return self.get_campaign(cid)

    def update_recipient(self, cid: str, seller_id: str, patch: dict) -> dict:
        with self._lock:
            campaign = self._campaign(cid)
            rec = next((r for r in campaign["recipients"] if r["seller_id"] == seller_id), None)
            if rec is None:
                raise UserError("گیرنده پیدا نشد.")
            if "email" in patch:
                email = clean_email(patch["email"])
                if email and not is_valid_email(email):
                    raise UserError("آدرس ایمیل معتبر نیست.")
                rec["email"] = email
                rec.setdefault("origin", {})["email"] = "manual"
            if "name" in patch:
                rec["name"] = str(patch["name"]).strip()
                rec.setdefault("origin", {})["name"] = "manual"
            if "excluded" in patch:
                rec["excluded"] = bool(patch["excluded"])
            self._save(campaign, notify=False)
        if "email" in patch or "name" in patch:
            self.db.upsert_seller(seller_id, email=rec["email"] if "email" in patch else None,
                                  name=rec["name"] if "name" in patch else None, source="manual", status="manual")
        return rec

    def bulk_exclude(self, cid: str, payload: dict) -> dict:
        which = payload.get("which", "")
        with self._lock:
            campaign = self._campaign(cid)
            for r in campaign["recipients"]:
                if which == "no_email":
                    r["excluded"] = r["excluded"] or not is_valid_email(r.get("email", ""))
                elif which == "none":
                    r["excluded"] = False
            self._save(campaign, notify=False)
        return self.get_campaign(cid)

    # -- step 2: crawl missing emails -----------------------------------
    def _campaign_status(self, campaign: dict) -> dict[str, str]:
        """Per active recipient: provided (from the file or typed by hand) or its address-book status."""
        active = [r for r in campaign.get("recipients", []) if not r.get("excluded")]
        book, _ = self.book_status([r["seller_id"] for r in active])
        status = {}
        for r in active:
            origin = (r.get("origin") or {}).get("email", "")
            if r.get("email") and origin in ("file", "manual"):
                status[r["seller_id"]] = "provided"
            elif r.get("email") and book[r["seller_id"]] in ("new", "no_email"):
                status[r["seller_id"]] = "provided"  # email came from somewhere other than the panel
            elif not r.get("email") and book[r["seller_id"]] in ("fresh", "stale"):
                status[r["seller_id"]] = "new"        # book has it but the recipient row is empty: fetch again
            else:
                status[r["seller_id"]] = book[r["seller_id"]]
        return status

    def campaign_crawl_plan(self, cid: str) -> dict:
        plan = self._plan(self._campaign_status(self._campaign(cid)))
        plan["cache_days"] = int(self.settings.section("crawler").get("cache_days", 30))
        return plan

    def crawl_campaign(self, cid: str, payload: dict) -> dict:
        self._ensure_no_crawl_running()
        campaign = self._campaign(cid)
        mode = crawl_mode(payload)
        refresh = mode == CRAWL_FULL
        status = self._campaign_status(campaign)
        targets = list(status) if refresh else [sid for sid, s in status.items() if s in SMART_CRAWLS]
        if not targets:
            raise UserError("ایمیل همه گیرندگان در دفترچه آدرس هست و نیازی به کراول نیست. برای خواندن دوباره از پنل، «کراول کامل از نو» را انتخاب کنید.")

        def on_result(result: CrawlResult) -> None:
            self._store_crawl(result)
            with self._lock:
                rec = next((r for r in campaign["recipients"] if r["seller_id"] == result.seller_id), None)
                if rec is not None:
                    origin = rec.setdefault("origin", {})
                    if result.email and (refresh or not rec.get("email") or origin.get("email") != "manual"):
                        rec["email"], origin["email"] = result.email, "crawl"
                    if result.name and (refresh or not rec.get("name")):
                        rec["name"], origin["name"] = result.name, "crawl"
                    rec["crawl_status"] = result.status
                    rec["crawl_message"] = result.message

        def work(job: Job) -> dict:
            skipped = len(status) - len(targets)
            if refresh:
                job.log("info", f"کراول کامل: هر {len(targets)} گیرنده از نو از پنل خوانده می‌شوند.")
            elif skipped:
                job.log("info", f"کراول هوشمند: {skipped} گیرنده از دفترچه آدرس یا فایل پر شد؛ {len(targets)} فروشنده کراول می‌شود.")
            crawler = Crawler(self._crawl_config(), job, self.driver_factory, on_result=on_result)
            try:
                summary = crawler.run(targets)
            except CrawlAborted as exc:
                raise UserError(str(exc)) from exc
            finally:
                self._save(campaign)
            return {"crawled": len(targets), "ok": summary.ok, "partial": summary.partial,
                    "empty": summary.empty, "failed": summary.failed, "mode": mode,
                    "from_book": len(status) - len(targets)}

        title = (f"کراول کامل {len(targets)} فروشنده" if refresh
                 else f"کراول هوشمند {len(targets)} فروشنده")
        job = self.jobs.start("crawl", title, work, {"campaign": cid, "mode": mode})
        return job.snapshot()

    # -- step 4: attachments ---------------------------------------------
    def prepare_split(self, cid: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        campaign = self._campaign(cid)
        source = campaign.get("source", {})
        if source.get("mode") != "file":
            raise UserError("برای جداسازی خودکار، منبع کمپین باید فایل اکسل باشد.")
        path = self.file_path(source["file_id"])
        table = read_table(str(path), source.get("sheet", ""), int(source.get("header_row", 1)))
        id_col = source["columns"]["id"]
        wanted = {r["seller_id"] for r in campaign["recipients"] if not r.get("excluded")}
        fmt = payload.get("format") or campaign["attachments"].get("split_format", "xlsx")
        prefix = payload.get("prefix", campaign["attachments"].get("split_prefix", ""))
        suffix = payload.get("suffix", campaign["attachments"].get("split_suffix", ""))
        workspace = self._workspace_for(campaign)
        out_dir = workspace / "پیوست‌ها"
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)

        def work(job: Job) -> dict:
            try:
                result = split_table(table, id_col, out_dir, output_format=fmt, include_blanks=False,
                                     as_id=True, only_values=wanted, file_prefix=prefix, file_suffix=suffix,
                                     progress=lambda d, t, label: job.progress(d, t, label),
                                     cancel=job.stop_event, source_name=path.stem)
            except SplitCancelled:
                return {}
            except TableError as exc:
                raise UserError(str(exc)) from exc
            with self._lock:
                att = campaign["attachments"]
                att.update({"mode": ATTACH_SPLIT, "split_dir": str(out_dir), "split_format": fmt,
                            "split_prefix": prefix, "split_suffix": suffix,
                            "split_files": result.files, "split_at": time.time()})
                for r in campaign["recipients"]:
                    r["attachment"] = result.files.get(r["seller_id"], "")
                self._save(campaign)
            job.log("ok", f"{len(result.files)} فایل اختصاصی ساخته شد.")
            return result.to_dict()

        job = self.jobs.start("split", f"آماده‌سازی پیوست‌های «{campaign['name']}»", work, {"campaign": cid})
        return job.snapshot()

    def _attachment_for(self, campaign: dict, rec: dict) -> list[str]:
        att = campaign.get("attachments", {})
        mode = att.get("mode", ATTACH_NONE)
        if mode == ATTACH_SPLIT:
            path = (att.get("split_files") or {}).get(rec["seller_id"]) or rec.get("attachment")
            return [path] if path and os.path.isfile(path) else []
        if mode == ATTACH_SHARED:
            paths = []
            for fid in att.get("shared_files", []):
                try:
                    paths.append(str(self.file_path(fid)))
                except UserError:
                    pass
            return paths
        if mode == ATTACH_FOLDER:
            folder = att.get("folder", "")
            return [find_file_for_seller(folder, rec["seller_id"])] if find_file_for_seller(folder, rec["seller_id"]) else []
        return []

    def _attachment_status(self, campaign: dict) -> dict:
        att = campaign.get("attachments", {})
        mode = att.get("mode", ATTACH_NONE)
        active = [r for r in campaign.get("recipients", []) if not r.get("excluded")]
        if mode == ATTACH_NONE:
            return {"mode": mode, "matched": 0, "missing": [], "ready": True}
        if mode == ATTACH_SPLIT and not att.get("split_dir"):
            return {"mode": mode, "matched": 0, "missing": [], "ready": False, "needs_split": True}
        if mode == ATTACH_SHARED:
            files = self._attachment_for(campaign, {"seller_id": ""})
            return {"mode": mode, "matched": len(active) if files else 0, "missing": [],
                    "ready": bool(files), "files": [os.path.basename(f) for f in files]}
        matched, missing = 0, []
        for r in active:
            if self._attachment_for(campaign, r):
                matched += 1
            else:
                missing.append(r["seller_id"])
        return {"mode": mode, "matched": matched, "missing": missing[:200], "missing_count": len(missing),
                "ready": matched > 0}

    def add_shared_attachment(self, cid: str, file_id: str) -> dict:
        self.file_path(file_id)
        with self._lock:
            campaign = self._campaign(cid)
            att = campaign["attachments"]
            files = att.setdefault("shared_files", [])
            if file_id not in files:
                files.append(file_id)
            names = att.setdefault("shared_names", {})
            names[file_id] = self.file_path(file_id).name
            att["mode"] = ATTACH_SHARED
            self._save(campaign, notify=False)
        return self.get_campaign(cid)

    def remove_shared_attachment(self, cid: str, file_id: str) -> dict:
        with self._lock:
            campaign = self._campaign(cid)
            att = campaign["attachments"]
            att["shared_files"] = [f for f in att.get("shared_files", []) if f != file_id]
            self._save(campaign, notify=False)
        return self.get_campaign(cid)

    def add_folder_files(self, cid: str, file_ids: list[str]) -> dict:
        """Browser fallback for 'folder' mode: uploaded files copied into one campaign folder."""
        with self._lock:
            campaign = self._campaign(cid)
            folder = self._workspace_for(campaign) / "پیوست‌های اختصاصی"
            folder.mkdir(parents=True, exist_ok=True)
            for fid in file_ids:
                src = self.file_path(fid)
                shutil.copy2(src, folder / src.name)
            campaign["attachments"].update({"mode": ATTACH_FOLDER, "folder": str(folder)})
            self._save(campaign, notify=False)
        return self.get_campaign(cid)

    # -- preview / readiness ---------------------------------------------
    def _render_for(self, campaign: dict, rec: dict) -> dict:
        compose = campaign.get("compose", {})
        sending = self.settings.section("sending")
        smtp = self.settings.section("smtp")
        files = self._attachment_for(campaign, rec)
        ctx = build_context(rec, sender_name=smtp.get("from_name", ""), attachment=files[0] if files else "")
        subject = render(compose.get("subject", ""), ctx)
        body = render(compose.get("body", ""), ctx)
        signature = render(sending.get("signature", ""), ctx)
        text_body = body + (f"\n\n--\n{signature}" if signature.strip() else "")
        return {
            "to": rec.get("email", ""), "subject": subject, "text": text_body,
            "html": text_to_html(body, signature) if sending.get("html", True) else "",
            "attachments": files,
            "unknown": unknown_placeholders(compose.get("subject", "") + "\n" + compose.get("body", ""), ctx),
        }

    def preview(self, cid: str, payload: dict) -> dict:
        campaign = self._campaign(cid)
        recipients = campaign.get("recipients", [])
        sid = payload.get("seller_id")
        rec = next((r for r in recipients if r["seller_id"] == sid), None)
        if rec is None:
            rec = next((r for r in recipients if not r.get("excluded")), None) or {
                "seller_id": "123456", "name": "فروشگاه نمونه", "email": "seller@example.com", "row_count": 12, "fields": {}}
        data = self._render_for(campaign, rec)
        data["seller_id"] = rec["seller_id"]
        data["attachments"] = [{"name": os.path.basename(p), "size": os.path.getsize(p)} for p in data["attachments"]]
        data["from"] = self.settings.from_address()
        data["from_name"] = self.settings.section("smtp").get("from_name", "")
        return data

    def _readiness(self, campaign: dict) -> dict:
        active = [r for r in campaign.get("recipients", []) if not r.get("excluded")]
        with_email = [r for r in active if is_valid_email(r.get("email", ""))]
        compose = campaign.get("compose", {})
        att = self._attachment_status(campaign)
        issues = []
        if not active:
            issues.append("هیچ گیرنده‌ای انتخاب نشده است.")
        elif len(with_email) < len(active):
            issues.append(f"{len(active) - len(with_email)} گیرنده ایمیل معتبر ندارند و ارسال نمی‌شوند.")
        if not compose.get("subject", "").strip():
            issues.append("موضوع ایمیل خالی است.")
        if not compose.get("body", "").strip():
            issues.append("متن ایمیل خالی است.")
        if not att.get("ready"):
            issues.append("پیوست‌ها آماده نیستند.")
        elif att.get("missing_count"):
            issues.append(f"{att['missing_count']} گیرنده فایل پیوست ندارند.")
        smtp_ready = bool(self.settings.smtp_username()) and (
            bool(self.settings.get_secret("smtp_password")) or self.settings.section("smtp").get("security") == "none")
        return {
            "recipients": len(active), "with_email": len(with_email),
            "smtp_ready": smtp_ready,
            "can_send": bool(with_email) and bool(compose.get("subject", "").strip())
                         and bool(compose.get("body", "").strip()) and bool(att.get("ready")),
            "issues": issues,
        }

    # -- sending ----------------------------------------------------------
    def send_test(self, cid: str, payload: dict) -> dict:
        campaign = self._campaign(cid)
        to = clean_email(payload.get("to") or self.settings.from_address())
        if not is_valid_email(to):
            raise UserError("آدرس ایمیل آزمایشی معتبر نیست.")
        rec = next((r for r in campaign["recipients"] if r["seller_id"] == payload.get("seller_id")), None) \
            or next((r for r in campaign["recipients"] if not r.get("excluded")), None)
        if rec is None:
            raise UserError("ابتدا گیرندگان را مشخص کنید.")
        msg_data = self._render_for(campaign, rec)
        msg = self._message(msg_data, to, subject_prefix="[آزمایشی] ")
        try:
            with self._smtp_session() as session:
                session.send(msg)
        except MailError as exc:
            raise UserError(str(exc)) from exc
        return {"ok": True, "to": to}

    def _message(self, data: dict, to: str, subject_prefix: str = ""):
        smtp = self.settings.section("smtp")
        sending = self.settings.section("sending")
        return build_message(
            from_addr=self.settings.from_address(), from_name=smtp.get("from_name", ""), to_addr=to,
            subject=subject_prefix + data["subject"], body=data["text"], html_body=data["html"] or None,
            attachments=data["attachments"], reply_to=smtp.get("reply_to", ""),
            bcc=self.settings.from_address() if sending.get("bcc_self") else "",
        )

    def start_send(self, cid: str, payload: dict) -> dict:
        if self.jobs.active("send"):
            raise UserError("یک ارسال دیگر در جریان است.")
        campaign = self._campaign(cid)
        dry_run = bool(payload.get("dry_run"))
        only_failed = bool(payload.get("only_failed"))
        readiness = self._readiness(campaign)
        if not readiness["can_send"]:
            raise UserError(" ".join(readiness["issues"]) or "کمپین آماده ارسال نیست.")
        if not dry_run:
            self._smtp_session()  # validates settings early, with a friendly message

        policy = campaign["attachments"].get("missing_policy", "skip")
        att_mode = campaign["attachments"].get("mode", ATTACH_NONE)
        sending = self.settings.section("sending")
        delay = float(payload.get("delay", sending.get("delay", 1.5)))
        pause_every = int(sending.get("pause_every", 0))
        pause_seconds = float(sending.get("pause_seconds", 0))

        targets = [r for r in campaign["recipients"] if not r.get("excluded") and is_valid_email(r.get("email", ""))]
        if only_failed:
            targets = [r for r in targets if r.get("status") in ("failed", "")]
        elif not dry_run:
            targets = [r for r in targets if r.get("status") != "sent"]
        if not targets:
            raise UserError("گیرنده‌ای برای ارسال باقی نمانده است.")

        def work(job: Job) -> dict:
            session = None if dry_run else self._smtp_session()
            counts = {"sent": 0, "failed": 0, "skipped": 0}
            job.progress(0, len(targets), "آماده‌سازی…")
            with self._lock:
                campaign["status"] = "sending"
                campaign["sending"]["dry_run"] = dry_run
            self._save(campaign)
            try:
                if session:
                    job.log("info", f"اتصال به {session.host}…")
                    session.connect()
                    job.log("ok", "اتصال به سرور ایمیل برقرار شد.")
                for index, rec in enumerate(targets, start=1):
                    job.check()
                    data = self._render_for(campaign, rec)
                    files = data["attachments"]
                    status, detail = "", ""
                    if att_mode in (ATTACH_SPLIT, ATTACH_FOLDER) and not files and policy == "skip":
                        status, detail = "skipped", "فایل پیوست اختصاصی پیدا نشد"
                    elif dry_run:
                        status, detail = "dry", "شبیه‌سازی — ارسال واقعی انجام نشد"
                    else:
                        try:
                            msg = self._message(data, rec["email"])
                            session.send(msg)
                            status = "sent"
                        except MailError as exc:
                            status, detail = "failed", str(exc)
                        except OSError as exc:
                            status, detail = "failed", f"خطای فایل پیوست: {exc}"
                    key = "sent" if status in ("sent", "dry") else status
                    counts[key] = counts.get(key, 0) + 1
                    attach_name = ", ".join(os.path.basename(f) for f in files)
                    with self._lock:
                        if not dry_run or status != "dry":
                            rec["status"], rec["detail"] = status, detail
                        rec["last_attempt"] = time.time()
                    self.db.log_send(cid, rec["seller_id"], rec["email"], status, detail, attach_name, dry_run)
                    job.item({"kind": "send", "seller_id": rec["seller_id"], "email": rec["email"],
                              "name": rec.get("name", ""), "status": status, "detail": detail,
                              "attachment": attach_name})
                    level = {"sent": "ok", "dry": "info", "skipped": "warn"}.get(status, "error")
                    job.log(level, f"{rec['email']} — {_status_fa(status)}" + (f": {detail}" if detail and status != "dry" else ""))
                    job.progress(index, len(targets), rec["email"])
                    if index % 10 == 0:
                        self._save(campaign, notify=False)
                    if index < len(targets):
                        if pause_every and index % pause_every == 0 and pause_seconds > 0 and not dry_run:
                            job.log("info", f"استراحت {int(pause_seconds)} ثانیه‌ای برای جلوگیری از محدودیت سرور…")
                            job.sleep(pause_seconds)
                        elif delay > 0 and not dry_run:
                            job.sleep(delay)
                        elif dry_run:
                            job.sleep(0.02)
            finally:
                if session:
                    session.close()
                with self._lock:
                    real = [r for r in campaign["recipients"] if not r.get("excluded") and is_valid_email(r.get("email", ""))]
                    stats = {
                        "total": len(real),
                        "sent": sum(1 for r in real if r.get("status") == "sent"),
                        "failed": sum(1 for r in real if r.get("status") == "failed"),
                        "skipped": sum(1 for r in real if r.get("status") == "skipped"),
                        "last_run_at": time.time(), "last_run_dry": dry_run,
                    }
                    campaign["stats"] = stats
                    if dry_run:
                        campaign["status"] = "draft"
                    elif job.stopped:
                        campaign["status"] = "stopped"
                    elif stats["sent"] == stats["total"]:
                        campaign["status"] = "sent"
                    else:
                        campaign["status"] = "partial"
                self._save(campaign)
            report = self.campaign_report(cid)
            return {**counts, "dry_run": dry_run, "report": report["path"]}

        title = ("شبیه‌سازی ارسال" if dry_run else "ارسال") + f" «{campaign['name']}»"
        job = self.jobs.start("send", title, work, {"campaign": cid, "dry_run": dry_run})
        return job.snapshot()

    def campaign_report(self, cid: str) -> dict:
        campaign = self._campaign(cid)
        headers = ["seller id", "seller name", "email", "وضعیت", "توضیح", "پیوست", "منبع ایمیل"]
        rows = []
        for r in campaign["recipients"]:
            files = self._attachment_for(campaign, r)
            rows.append({
                "seller id": r["seller_id"], "seller name": r.get("name", ""), "email": r.get("email", ""),
                "وضعیت": "حذف از ارسال" if r.get("excluded") else _status_fa(r.get("status", "")),
                "توضیح": r.get("detail", "") or r.get("crawl_message", ""),
                "پیوست": ", ".join(os.path.basename(f) for f in files),
                "منبع ایمیل": _origin_fa((r.get("origin") or {}).get("email", "")),
            })
        path = self._workspace_for(campaign) / "گزارش ارسال.xlsx"
        try:
            write_table(path, Table(headers, rows), "report", rtl=True)
        except TableError:
            path = path.with_name(f"گزارش ارسال {dt.datetime.now():%H%M%S}.xlsx")
            write_table(path, Table(headers, rows), "report", rtl=True)
        return {"path": str(path)}

    def campaign_log(self, cid: str) -> list[dict]:
        return self.db.send_log(cid)


def find_file_for_seller(folder: str, seller_id: str) -> str:
    """A file whose name starts with the seller id (not followed by another digit)."""
    if not folder or not os.path.isdir(folder):
        return ""
    pattern = re.compile(rf"^{re.escape(seller_id)}(?!\d)", re.IGNORECASE)
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and pattern.match(name):
            return path
    return ""


STATUS_FA = {
    "sent": "ارسال شد", "failed": "ناموفق", "skipped": "رد شد", "dry": "شبیه‌سازی",
    "ok": "کامل", "partial": "ناقص", "not-found": "پیدا نشد", "error": "خطا",
    "manual": "ویرایش دستی", "file": "از فایل", "import": "وارد شده", "": "—",
}


def _status_fa(status: str) -> str:
    return STATUS_FA.get(status, status)


def _origin_fa(origin: str) -> str:
    return {"file": "فایل ورودی", "directory": "دفترچه آدرس", "crawl": "کراول پنل",
            "manual": "ویرایش دستی"}.get(origin, "—")


def _fmt_ts(ts: Any) -> str:
    try:
        return dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""
