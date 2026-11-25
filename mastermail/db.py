"""SQLite store: seller directory (crawl cache), campaigns and the send log."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .paths import database_file

SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    seller_id   TEXT PRIMARY KEY,
    email       TEXT DEFAULT '',
    name        TEXT DEFAULT '',
    extra       TEXT DEFAULT '{}',
    source      TEXT DEFAULT '',
    status      TEXT DEFAULT '',
    updated_at  REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS campaigns (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    status      TEXT DEFAULT 'draft',
    created_at  REAL,
    updated_at  REAL,
    data        TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS send_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT,
    seller_id   TEXT,
    email       TEXT,
    status      TEXT,
    detail      TEXT DEFAULT '',
    attachment  TEXT DEFAULT '',
    dry_run     INTEGER DEFAULT 0,
    at          REAL
);
CREATE INDEX IF NOT EXISTS idx_send_log_campaign ON send_log(campaign_id);
"""


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else database_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # -- sellers ----------------------------------------------------------
    def get_seller(self, seller_id: str) -> dict | None:
        rows = self._query("SELECT * FROM sellers WHERE seller_id=?", (seller_id,))
        return _seller(rows[0]) if rows else None

    def get_sellers(self, ids: list[str]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for row in self._query(f"SELECT * FROM sellers WHERE seller_id IN ({marks})", chunk):
                found[row["seller_id"]] = _seller(row)
        return found

    def upsert_seller(self, seller_id: str, *, email: str | None = None, name: str | None = None,
                      extra: dict | None = None, source: str = "", status: str = "") -> None:
        current = self.get_seller(seller_id) or {"email": "", "name": "", "extra": {}}
        new_email = current["email"] if email is None or (email == "" and current["email"]) else email
        new_name = current["name"] if name is None or (name == "" and current["name"]) else name
        merged_extra = dict(current.get("extra") or {})
        merged_extra.update(extra or {})
        self._exec(
            """INSERT INTO sellers(seller_id,email,name,extra,source,status,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(seller_id) DO UPDATE SET email=excluded.email, name=excluded.name,
               extra=excluded.extra, source=excluded.source, status=excluded.status,
               updated_at=excluded.updated_at""",
            (seller_id, new_email, new_name, json.dumps(merged_extra, ensure_ascii=False),
             source, status, time.time()),
        )

    def search_sellers(self, q: str = "", limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
        where, params = "", []
        if q:
            where = "WHERE seller_id LIKE ? OR email LIKE ? OR name LIKE ?"
            like = f"%{q}%"
            params = [like, like, like]
        total = self._query(f"SELECT COUNT(*) AS n FROM sellers {where}", params)[0]["n"]
        rows = self._query(
            f"SELECT * FROM sellers {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        return [_seller(r) for r in rows], total

    def delete_seller(self, seller_id: str) -> None:
        self._exec("DELETE FROM sellers WHERE seller_id=?", (seller_id,))

    def count_sellers(self) -> dict[str, int]:
        row = self._query(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN email<>'' THEN 1 ELSE 0 END) AS with_email FROM sellers"
        )[0]
        return {"total": row["total"] or 0, "with_email": row["with_email"] or 0}

    # -- campaigns --------------------------------------------------------
    def save_campaign(self, campaign: dict) -> None:
        now = time.time()
        campaign["updated_at"] = now
        campaign.setdefault("created_at", now)
        self._exec(
            """INSERT INTO campaigns(id,name,status,created_at,updated_at,data) VALUES(?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, status=excluded.status,
               updated_at=excluded.updated_at, data=excluded.data""",
            (campaign["id"], campaign.get("name", ""), campaign.get("status", "draft"),
             campaign["created_at"], now, json.dumps(campaign, ensure_ascii=False)),
        )

    def get_campaign(self, campaign_id: str) -> dict | None:
        rows = self._query("SELECT data FROM campaigns WHERE id=?", (campaign_id,))
        return json.loads(rows[0]["data"]) if rows else None

    def list_campaigns(self, limit: int = 100) -> list[dict]:
        rows = self._query("SELECT data FROM campaigns ORDER BY updated_at DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            data = json.loads(r["data"])
            data.pop("recipients", None)
            out.append(data)
        return out

    def delete_campaign(self, campaign_id: str) -> None:
        self._exec("DELETE FROM campaigns WHERE id=?", (campaign_id,))
        self._exec("DELETE FROM send_log WHERE campaign_id=?", (campaign_id,))

    # -- send log ---------------------------------------------------------
    def log_send(self, campaign_id: str, seller_id: str, email: str, status: str,
                 detail: str = "", attachment: str = "", dry_run: bool = False) -> None:
        self._exec(
            "INSERT INTO send_log(campaign_id,seller_id,email,status,detail,attachment,dry_run,at) VALUES(?,?,?,?,?,?,?,?)",
            (campaign_id, seller_id, email, status, detail, attachment, int(dry_run), time.time()),
        )

    def send_log(self, campaign_id: str) -> list[dict]:
        return self._query("SELECT * FROM send_log WHERE campaign_id=? ORDER BY id", (campaign_id,))

    def stats(self) -> dict[str, int]:
        sent = self._query("SELECT COUNT(*) AS n FROM send_log WHERE status='sent' AND dry_run=0")[0]["n"]
        campaigns = self._query("SELECT COUNT(*) AS n FROM campaigns")[0]["n"]
        sellers = self.count_sellers()
        return {"emails_sent": sent, "campaigns": campaigns, "sellers": sellers["total"],
                "sellers_with_email": sellers["with_email"]}


def _seller(row: dict) -> dict:
    data = dict(row)
    try:
        data["extra"] = json.loads(data.get("extra") or "{}")
    except ValueError:
        data["extra"] = {}
    return data
