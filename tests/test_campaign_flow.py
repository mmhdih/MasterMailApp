"""Full pipeline: file of seller rows → crawl (with login) → split → compose → send."""
import time

from openpyxl import Workbook

from fakes import FakeSMTP, Panel, stub_factory
from mastermail.db import Database
from mastermail.jobs import JobManager
from mastermail.service import Service
from mastermail.settings import Settings


def wait(svc, job, timeout=20, until=("done", "failed", "stopped")):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = svc.jobs.get(job["id"])
        if j.state in until:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {svc.jobs.get(job['id']).snapshot(True)}")


def make_service(env, panel, smtp):
    settings = Settings()
    settings.update({
        "smtp": {"host": "127.0.0.1", "port": smtp.port, "security": "none", "username": "user",
                 "use_system_username": False, "from_email": "ops@shop.ir", "from_name": "تیم فروشندگان"},
        "sending": {"delay": 0, "pause_every": 0, "signature": "تیم عملیات"},
        "crawler": {"base_url": panel.base_url, "delay": 0, "element_timeout": 1, "retries": 1, "login_wait": 30},
    })
    settings.set_secret("smtp_password", "secret")
    return Service(settings, Database(), JobManager(), driver_factory=stub_factory)


def test_end_to_end(env):
    panel = Panel(require_login=True)
    smtp = FakeSMTP(reject={"sara@shop.ir"})
    svc = make_service(env, panel, smtp)

    # A monthly report: several rows per seller, no email column.
    wb = Workbook()
    ws = wb.active
    ws.append(["seller id", "کالا", "مبلغ"])
    for sid, n in (("1001", 3), ("1002", 2), ("1003", 1), ("1004", 1)):
        for i in range(n):
            ws.append([int(sid), f"کالا {i}", 1000 * (i + 1)])
    path = env / "report.xlsx"
    wb.save(path)
    up = svc.upload("گزارش آبان.xlsx", path.read_bytes())

    info = svc.inspect_file({"file_id": up["file_id"]})
    assert info["detected"]["id"] == "seller id" and info["repeated_ids"] and info["suggest_split"]

    c = svc.create_campaign({"name": "گزارش آبان"})
    c = svc.set_source(c["id"], {"mode": "file", "file_id": up["file_id"], "columns": info["detected"], "split": True})
    assert [r["seller_id"] for r in c["recipients"]] == ["1001", "1002", "1003", "1004"]
    assert c["recipients"][0]["row_count"] == 3 and c["attachments"]["mode"] == "split"

    # crawl: the panel demands a login first
    job = svc.crawl_campaign(c["id"], {})
    j = wait(svc, job, until=("waiting", "done", "failed"))
    assert j.state == "waiting" and j.action["type"] == "login"
    panel.logged_in = True
    svc.jobs.control(job["id"], "confirm-login")
    j = wait(svc, job)
    assert j.state == "done", j.error
    assert j.result == {"crawled": 4, "ok": 2, "partial": 1, "empty": 1, "failed": 0}
    c = svc.get_campaign(c["id"])
    emails = {r["seller_id"]: r["email"] for r in c["recipients"]}
    assert emails == {"1001": "ali@shop.ir", "1002": "sara@shop.ir", "1003": "", "1004": ""}
    assert c["readiness"]["with_email"] == 2

    # manual fix for one seller is saved to the directory too
    svc.update_recipient(c["id"], "1003", {"email": "third@shop.ir"})
    assert svc.db.get_seller("1003")["email"] == "third@shop.ir"

    # attachments: split the source file per seller
    j = wait(svc, svc.prepare_split(c["id"], {}))
    assert j.state == "done" and j.result["group_count"] == 4
    svc.update_campaign(c["id"], {"compose": {"subject": "گزارش {month} — {seller_name}",
                                             "body": "سلام {seller_name}\n\nفایل {file_name} شامل {row_count} ردیف است."}})
    c = svc.get_campaign(c["id"])
    assert c["attachment_status"]["matched"] == 4 and c["readiness"]["can_send"]

    preview = svc.preview(c["id"], {"seller_id": "1001"})
    assert "فروشگاه علی" in preview["subject"] and "1001.xlsx" in preview["text"] and "۳ ردیف" in preview["text"]
    assert preview["attachments"][0]["name"] == "1001.xlsx" and not preview["unknown"]

    # test email
    svc.send_test(c["id"], {"to": "me@shop.ir"})
    assert smtp.messages[-1]["msg"]["Subject"].startswith("[آزمایشی]")

    # dry run sends nothing
    before = len(smtp.messages)
    j = wait(svc, svc.start_send(c["id"], {"dry_run": True}))
    assert j.state == "done" and j.result["sent"] == 3 and len(smtp.messages) == before

    # real send: sara is rejected by the server, 1004 has no email
    j = wait(svc, svc.start_send(c["id"], {}))
    assert j.state == "done", j.error
    assert (j.result["sent"], j.result["failed"]) == (2, 1)
    sent = smtp.messages[before:]
    assert sorted(m["rcpts"][0] for m in sent) == ["ali@shop.ir", "third@shop.ir"]
    ali = next(m["msg"] for m in sent if m["rcpts"] == ["ali@shop.ir"])
    assert ali["From"].addresses[0].addr_spec == "ops@shop.ir"
    assert "فروشگاه علی" in str(ali["Subject"])
    atts = [p.get_filename() for p in ali.iter_attachments()]
    assert atts == ["1001.xlsx"]
    html = ali.get_body(("html",)).get_content()
    assert "تیم عملیات" in html and 'dir="rtl"' in html

    c = svc.get_campaign(c["id"])
    assert c["status"] == "partial" and c["stats"]["sent"] == 2 and c["stats"]["failed"] == 1
    import os
    assert os.path.isfile(j.result["report"])

    # retry failed after the server stops rejecting
    smtp.reject.clear()
    j = wait(svc, svc.start_send(c["id"], {"only_failed": True}))
    assert j.result["sent"] == 1
    assert svc.get_campaign(c["id"])["status"] == "sent"
    assert len([r for r in svc.campaign_log(c["id"]) if r["status"] == "sent" and not r["dry_run"]]) == 3

    # second campaign with ids only: directory cache fills emails without crawling
    c2 = svc.create_campaign({})
    c2 = svc.set_source(c2["id"], {"mode": "ids", "text": "1001 1002 1003"})
    assert all(r["email"] for r in c2["recipients"])
    assert {r["origin"]["email"] for r in c2["recipients"]} == {"directory"}

    panel.stop()
    smtp.stop()


def test_standalone_crawl_uses_cache_and_exports(env):
    panel = Panel()
    smtp = FakeSMTP()
    svc = make_service(env, panel, smtp)
    j = wait(svc, svc.start_crawl({"text": "1005, 1006\n1007"}))
    assert j.state == "done" and j.result["crawled"] == 3 and j.result["ok"] == 3
    j = wait(svc, svc.start_crawl({"text": "1005 1006 1007 1008"}))
    assert j.result["crawled"] == 1 and j.result["cached"] == 3
    from mastermail.tabular import read_table
    rows = read_table(j.result["export"]).rows
    assert [r["email"] for r in rows] == ["reza@shop.ir", "mina@shop.ir", "omid@shop.ir", "nazanin@shop.ir"]
    panel.stop()
    smtp.stop()


def test_smtp_errors_are_friendly(env):
    panel = Panel()
    smtp = FakeSMTP(password="other")
    svc = make_service(env, panel, smtp)
    import pytest
    from mastermail.service import UserError
    with pytest.raises(UserError, match="رمز عبور"):
        svc.test_smtp()
    svc.settings.update({"smtp": {"port": 1}})
    with pytest.raises(UserError):
        svc.test_smtp()
    panel.stop()
    smtp.stop()
