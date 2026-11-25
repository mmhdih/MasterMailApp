"""Address book: remembered between runs, smart crawl skips what is known, full crawl re-reads everyone."""
import time

from fakes import FakeSMTP, Panel, stub_factory
from mastermail.db import Database
from mastermail.jobs import JobManager
from mastermail.service import Service
from mastermail.settings import Settings
from test_campaign_flow import make_service, wait


def sellers():
    return {"1001": ("ali@shop.ir", "فروشگاه علی"), "1002": ("sara@shop.ir", "فروشگاه سارا"),
            "1003": (None, "بدون ایمیل"), "1004": ("reza@shop.ir", "فروشگاه رضا")}


def crawled_ids(svc, job):
    return [e["text"] for e in svc.jobs.get(job["id"]).logs if "کراول" in e["text"]]


def test_book_survives_restart_and_smart_crawl_skips_known(env):
    panel, smtp = Panel(sellers()), FakeSMTP()
    svc = make_service(env, panel, smtp)
    j = wait(svc, svc.start_crawl({"text": "1001 1002 1003"}))
    assert (j.result["crawled"], j.result["cached"]) == (3, 0)
    svc.db.close()

    # a brand-new app instance on the same data folder = the app was closed and opened again
    svc2 = Service(Settings(), Database(), JobManager(), driver_factory=stub_factory)
    assert svc2.db.get_seller("1001")["email"] == "ali@shop.ir"
    plan = svc2.crawl_plan({"text": "1001 1002 1003 1004"})
    assert plan == {"total": 4, "fresh": 2, "provided": 0, "stale": 0, "no_email": 1, "new": 1,
                    "smart": 2, "full": 4, "cache_days": 30}
    j = wait(svc2, svc2.start_crawl({"text": "1001 1002 1003 1004", "mode": "smart"}))
    assert (j.result["crawled"], j.result["cached"], j.result["mode"]) == (2, 2, "smart")
    rows = {r["seller_id"]: r for r in j.result["rows"]}
    assert rows["1001"]["status"] == "cached" and rows["1004"]["status"] == "ok"
    assert rows["1003"]["status"] == "partial"  # no-email sellers are retried in smart mode
    panel.stop(); smtp.stop()


def test_full_crawl_rereads_everyone_and_updates_book(env):
    data = sellers()
    panel, smtp = Panel(data), FakeSMTP()
    svc = make_service(env, panel, smtp)
    wait(svc, svc.start_crawl({"text": "1001 1002"}))
    data["1001"] = ("ali.new@shop.ir", "فروشگاه علی (جدید)")   # the seller changed their email in the panel
    j = wait(svc, svc.start_crawl({"text": "1001 1002", "mode": "smart"}))
    assert j.result["crawled"] == 0 and svc.db.get_seller("1001")["email"] == "ali@shop.ir"
    j = wait(svc, svc.start_crawl({"text": "1001 1002", "mode": "full"}))
    assert (j.result["crawled"], j.result["mode"]) == (2, "full")
    assert svc.db.get_seller("1001")["email"] == "ali.new@shop.ir"
    assert svc.db.get_seller("1001")["name"] == "فروشگاه علی (جدید)"
    j = wait(svc, svc.start_crawl({"text": "1001", "refresh": True}))  # older "refresh" flag still means full
    assert j.result["mode"] == "full"
    panel.stop(); smtp.stop()


def test_stale_entries_are_refreshed_in_smart_mode(env):
    panel, smtp = Panel(sellers()), FakeSMTP()
    svc = make_service(env, panel, smtp)
    wait(svc, svc.start_crawl({"text": "1001 1002"}))
    old = time.time() - 40 * 86400
    svc.db._exec("UPDATE sellers SET updated_at=? WHERE seller_id='1001'", (old,))
    assert svc.crawl_plan({"text": "1001 1002"})["stale"] == 1
    j = wait(svc, svc.start_crawl({"text": "1001 1002"}))
    assert j.result["crawled"] == 1
    svc.settings.update({"crawler": {"cache_days": 0}})  # 0 = the address book never expires
    svc.db._exec("UPDATE sellers SET updated_at=? WHERE seller_id='1001'", (old,))
    assert svc.crawl_plan({"text": "1001 1002"})["smart"] == 0
    panel.stop(); smtp.stop()


def test_campaign_modes_respect_book_file_and_manual_emails(env):
    panel, smtp = Panel(sellers()), FakeSMTP()
    svc = make_service(env, panel, smtp)
    wait(svc, svc.start_crawl({"text": "1001 1002"}))           # 1001, 1002 known in the book

    c = svc.create_campaign({})
    c = svc.set_source(c["id"], {"mode": "ids", "text": "1001 1002 1003 1004"})
    assert [r["origin"]["email"] for r in c["recipients"]][:2] == ["directory", "directory"]
    svc.update_recipient(c["id"], "1003", {"email": "typed@shop.ir"})  # typed by hand
    plan = svc.campaign_crawl_plan(c["id"])
    assert (plan["fresh"], plan["provided"], plan["new"], plan["smart"], plan["full"]) == (2, 1, 1, 1, 4)

    j = wait(svc, svc.crawl_campaign(c["id"], {"mode": "smart"}))
    assert (j.result["crawled"], j.result["from_book"]) == (1, 3)
    emails = {r["seller_id"]: r["email"] for r in svc.get_campaign(c["id"])["recipients"]}
    assert emails == {"1001": "ali@shop.ir", "1002": "sara@shop.ir", "1003": "typed@shop.ir", "1004": "reza@shop.ir"}

    # nothing left for smart mode → friendly message, full mode still possible
    import pytest
    from mastermail.service import UserError
    with pytest.raises(UserError, match="کراول کامل از نو"):
        svc.crawl_campaign(c["id"], {"mode": "smart"})
    j = wait(svc, svc.crawl_campaign(c["id"], {"mode": "full"}))
    assert j.result["crawled"] == 4
    emails = {r["seller_id"]: r["email"] for r in svc.get_campaign(c["id"])["recipients"]}
    assert emails["1003"] == "typed@shop.ir"   # panel has no email for 1003 → the typed one is kept
    panel.stop(); smtp.stop()


def test_file_emails_are_not_crawled_in_smart_mode(env):
    from openpyxl import Workbook
    panel, smtp = Panel(sellers()), FakeSMTP()
    svc = make_service(env, panel, smtp)
    wb = Workbook(); ws = wb.active
    ws.append(["seller id", "email"]); ws.append([1001, "from.file@shop.ir"]); ws.append([1004, ""])
    path = env / "list.xlsx"; wb.save(path)
    up = svc.upload("list.xlsx", path.read_bytes())
    c = svc.create_campaign({})
    svc.set_source(c["id"], {"mode": "file", "file_id": up["file_id"], "columns": {"id": "seller id", "email": "email"}})
    plan = svc.campaign_crawl_plan(c["id"])
    assert (plan["provided"], plan["smart"]) == (1, 1)
    j = wait(svc, svc.crawl_campaign(c["id"], {}))
    assert j.result["crawled"] == 1
    # file emails are remembered too
    assert svc.db.get_seller("1001")["email"] == "from.file@shop.ir"
    panel.stop(); smtp.stop()
