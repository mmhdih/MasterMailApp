"""Persian / RTL correctness of everything the app reads, writes and sends."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from fakes import FakeSMTP, Panel
from mastermail.ids import parse_ids
from mastermail.mailer import build_context, build_message, render, text_to_html
from mastermail.splitter import split_table
from mastermail.tabular import Table, detect_columns, read_table, write_table
from mastermail.textutil import clean_email, jalali_today, norm_key, to_ascii_digits, to_fa_digits
from test_campaign_flow import make_service, wait

ZWNJ = "‌"


# ----------------------------------------------------------------------- text
def test_digits_both_ways():
    assert to_ascii_digits("۰۱۲۳۴۵۶۷۸۹ ٠١٢٣٤٥٦٧٨٩") == "0123456789 0123456789"
    assert to_fa_digits("1405/09/04") == "۱۴۰۵/۰۹/۰۴"


def test_ids_from_persian_text():
    pasted = "شناسه‌ها: ۱۰۰۱، ۱۰۰۲؛ ١٠٠٣\n۱۰۰۱ «۱۰۰۴»"
    r = parse_ids(pasted)
    assert "1001" in r.ids and "1002" in r.ids and "1003" in r.ids
    assert r.duplicates == ["1001"]


@pytest.mark.parametrize("a,b", [
    ("كد فروشنده", "کد فروشنده"),          # Arabic kaf
    ("شناسه فروشندي", "شناسه فروشندی"),     # Arabic yeh
    (f"نام{ZWNJ}فروشنده", "نام فروشنده"),   # ZWNJ vs space
    ("Seller_ID", "seller id"),
])
def test_norm_key_unifies_persian_variants(a, b):
    assert norm_key(a) == norm_key(b)


def test_email_cells_with_persian_digits_and_separators():
    assert clean_email("info۱@shop.ir؛ sales@shop.ir") == "info1@shop.ir, sales@shop.ir"


def test_jalali_and_persian_placeholders():
    rec = {"seller_id": "۱۰۰۱", "name": "فروشگاه کتاب‌سرا", "email": "a@b.ir", "row_count": 12,
           "fields": {"مبلغ کل": "۲٬۵۰۰٬۰۰۰ ریال", f"نام{ZWNJ}شهر": "تهران"}}
    ctx = build_context(rec)
    out = render("{seller_name} | {مبلغ کل} | {نام شهر} | {row_count} | {تاريخ}", ctx)
    assert out.startswith("فروشگاه کتاب‌سرا | ۲٬۵۰۰٬۰۰۰ ریال | تهران | ۱۲ | ")
    assert out.endswith(jalali_today())
    assert all(ch in "۰۱۲۳۴۵۶۷۸۹ " or "؀" <= ch <= "ۿ" for ch in jalali_today())


# ----------------------------------------------------------------------- files
def _persian_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "فروش آبان"
    ws.append(["كد فروشنده", "نام فروشنده", "شهر", "مبلغ"])
    ws.append(["۱۰۰۱", "فروشگاه علی", "تهران/کرج", 1000])
    ws.append(["۱۰۰۱", "فروشگاه علی", f"تهران/کرج", 2000])
    ws.append([1002, f"کتاب{ZWNJ}سرای سارا", "شیراز", 3000])
    wb.save(path)


def test_persian_headers_sheet_and_digits(tmp_path):
    p = tmp_path / f"گزارش{ZWNJ}فروش آبان.xlsx"
    _persian_workbook(p)
    t = read_table(str(p))
    assert t.sheet == "فروش آبان"
    cols = detect_columns(t)
    assert cols["id"] == "كد فروشنده" and cols["name"] == "نام فروشنده"


def test_split_persian_values_rtl_and_names(tmp_path):
    p = tmp_path / "r.xlsx"
    _persian_workbook(p)
    t = read_table(str(p))
    res = split_table(t, "شهر", tmp_path / "خروجی")
    files = sorted(Path(f).name for f in res.files.values())
    assert files == ["تهران-کرج.xlsx", "شیراز.xlsx"]
    ws = load_workbook(res.files["شیراز"]).active
    assert ws.sheet_view.rightToLeft is True
    assert [c.value for c in ws[1]] == ["كد فروشنده", "نام فروشنده", "شهر", "مبلغ"]
    assert ws["B2"].value == f"کتاب{ZWNJ}سرای سارا"  # ZWNJ kept inside data

    res = split_table(t, "كد فروشنده", tmp_path / "ids", as_id=True, file_prefix="گزارش-", include_blanks=False)
    assert sorted(Path(f).name for f in res.files.values()) == ["گزارش-1001.xlsx", "گزارش-1002.xlsx"]


def test_csv_bom_and_windows_1256(tmp_path):
    out = tmp_path / "خروجی.csv"
    write_table(out, Table(["نام", "ایمیل"], [{"نام": "علی", "ایمیل": "a@b.ir"}]))
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")  # Excel opens UTF-8 with BOM correctly
    legacy = tmp_path / "legacy.csv"
    legacy.write_bytes("شناسه فروشنده,نام\n1001,فروشگاه\n".encode("cp1256"))
    t = read_table(str(legacy))
    assert t.headers == ["شناسه فروشنده", "نام"] and t.rows[0]["نام"] == "فروشگاه"


def test_docx_import_persian(env):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("فروشنده گرامی {seller_name}،")
    doc.add_paragraph("")
    doc.add_paragraph("گزارش آبان ۱۴۰۵ پیوست است.")
    path = env / "متن.docx"
    doc.save(path)
    from mastermail.service import Service
    svc = Service()
    up = svc.upload(path.name, path.read_bytes())
    assert svc.import_docx(up["file_id"])["body"] == "فروشنده گرامی {seller_name}،\n\nگزارش آبان ۱۴۰۵ پیوست است."


# ----------------------------------------------------------------------- email
def test_message_headers_and_bodies_are_persian_safe(tmp_path):
    att = tmp_path / "گزارش آبان ۱۰۰۱.xlsx"
    att.write_bytes(b"x")
    msg = build_message(from_addr="ops@shop.ir", from_name="تیم عملیات", to_addr="a@b.ir",
                        subject="گزارش آبان — فروشگاه علی", body="سلام علی\n\nمتن", html_body=text_to_html("سلام علی"),
                        attachments=[str(att)])
    raw = msg.as_bytes()
    raw.decode("ascii")  # headers are encoded, nothing raw 8-bit in the header block
    parsed = message_from_bytes(raw, policy=policy.default)
    assert str(parsed["Subject"]) == "گزارش آبان — فروشگاه علی"
    assert parsed["From"].addresses[0].display_name == "تیم عملیات"
    assert [p.get_filename() for p in parsed.iter_attachments()] == ["گزارش آبان ۱۰۰۱.xlsx"]
    plain = parsed.get_body(("plain",))
    assert plain.get_content_charset() == "utf-8" and "سلام علی" in plain.get_content()
    html = parsed.get_body(("html",)).get_content()
    assert '<html lang="fa" dir="rtl">' in html and "direction:rtl" in html and "text-align:right" in html


def test_full_campaign_in_persian(env):
    panel = Panel({"1001": ("ali@shop.ir", "فروشگاه علی"), "1002": ("sara@shop.ir", f"کتاب{ZWNJ}سرای سارا")})
    smtp = FakeSMTP()
    svc = make_service(env, panel, smtp)
    p = env / "src.xlsx"
    _persian_workbook(p)
    up = svc.upload(f"گزارش{ZWNJ}فروش آبان.xlsx", p.read_bytes())
    assert "گزارش" in Path(up["path"]).name

    c = svc.create_campaign({"name": "کمپین آبان: گزارش/تسویه"})
    info = svc.inspect_file({"file_id": up["file_id"]})
    c = svc.set_source(c["id"], {"mode": "file", "file_id": up["file_id"], "columns": info["detected"], "split": True})
    assert [r["seller_id"] for r in c["recipients"]] == ["1001", "1002"]  # Persian digits normalised

    j = wait(svc, svc.crawl_campaign(c["id"], {}))
    assert j.state == "done"
    j = wait(svc, svc.prepare_split(c["id"], {}))
    assert j.state == "done"
    ws_dir = Path(svc.get_campaign(c["id"])["workspace"])
    assert ws_dir.is_dir() and "کمپین آبان" in ws_dir.name and "/" not in ws_dir.name

    svc.update_campaign(c["id"], {"compose": {
        "subject": "صورت‌حساب {month} — {seller_name}",
        "body": "{seller_name} گرامی، سلام\n\nمبلغ اولین ردیف شما {مبلغ} و شهر {شهر} است.\n\n- مورد اول\n- مورد دوم"}})
    j = wait(svc, svc.start_send(c["id"], {}))
    assert j.state == "done" and j.result["sent"] == 2, j.error

    msg = next(m["msg"] for m in smtp.messages if m["rcpts"] == ["sara@shop.ir"])
    subject = str(msg["Subject"])
    assert subject.startswith("صورت‌حساب ") and subject.endswith(f"کتاب{ZWNJ}سرای سارا")
    text = msg.get_body(("plain",)).get_content()
    assert "مبلغ اولین ردیف شما 3000 و شهر شیراز است." in text
    html = msg.get_body(("html",)).get_content()
    assert 'dir="rtl"' in html and "<ul" in html and f"کتاب{ZWNJ}سرای سارا" in html

    report = load_workbook(j.result["report"]).active
    assert report.sheet_view.rightToLeft is True
    assert [c.value for c in report[1]][:4] == ["seller id", "seller name", "email", "وضعیت"]
    assert {report.cell(r, 4).value for r in range(2, 4)} == {"ارسال شد"}
    panel.stop()
    smtp.stop()


# ----------------------------------------------------------------------- http
def test_api_speaks_utf8(env):
    from mastermail.db import Database
    from mastermail.jobs import JobManager
    from mastermail.server import AppServer
    from mastermail.service import Service
    from mastermail.settings import Settings

    svc = Service(Settings(), Database(), JobManager())
    srv = AppServer(svc, token="t").start()
    base = f"http://127.0.0.1:{srv.port}"
    try:
        req = urllib.request.Request(base + "/api/campaigns", data=json.dumps({"name": "کمپین فارسی"}).encode(),
                                     method="POST", headers={"X-Token": "t", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert r.headers["Content-Type"] == "application/json; charset=utf-8"
            raw = r.read()
        assert "کمپین فارسی".encode() in raw  # not \\u-escaped
        try:
            urllib.request.urlopen(urllib.request.Request(base + f"/api/campaigns/{json.loads(raw)['id']}/source",
                                   data=b'{"mode":"ids","text":""}', method="POST", headers={"X-Token": "t"}))
        except urllib.error.HTTPError as e:
            err = json.loads(e.read())["error"]
            assert any("؀" <= ch <= "ۿ" for ch in err)
        name = "گزارش ارسال.xlsx"
        target = svc.settings.workspace() / name
        target.write_bytes(b"x")
        url = base + "/api/download?t=t&path=" + urllib.parse.quote(str(target))
        with urllib.request.urlopen(url) as r:
            disp = r.headers["Content-Disposition"]
        assert str(make_header(decode_header(disp))) and "UTF-8''" in disp
        assert urllib.parse.unquote(disp.split("UTF-8''")[1]) == name
        with urllib.request.urlopen(base + "/") as r:
            page = r.read().decode("utf-8")
            assert r.headers["Content-Type"].endswith("charset=utf-8")
        assert '<html lang="fa" dir="rtl">' in page
    finally:
        srv.stop()
