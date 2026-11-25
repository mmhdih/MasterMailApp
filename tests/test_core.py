import datetime as dt

from mastermail.ids import parse_ids
from mastermail.mailer import build_context, render, text_to_html, unknown_placeholders
from mastermail.textutil import clean_email, gregorian_to_jalali, is_valid_email, jalali_today
from mastermail.templates import smart_compose, TEMPLATES


def test_parse_ids_handles_persian_digits_separators_and_duplicates():
    r = parse_ids("۱۲۳۴، 5678\n1234 ; bad! 99.0\t'777'")
    assert r.ids == ["1234", "5678", "99", "777"]
    assert r.duplicates == ["1234"]
    assert r.invalid == ["bad!"]


def test_jalali():
    assert gregorian_to_jalali(2026, 3, 21) == (1405, 1, 1)
    assert jalali_today(dt.date(2026, 11, 25), persian_digits=False) == "4 آذر 1405"


def test_email_helpers():
    assert clean_email(" mailto:A@B.IR ") == "A@B.IR"
    assert clean_email("a@b.ir; c@d.ir") == "a@b.ir, c@d.ir"
    assert is_valid_email("a@b.ir, c@d.ir")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("")


def test_render_placeholders_and_aliases():
    rec = {"seller_id": "1001", "name": "فروشگاه علی", "email": "ali@shop.ir", "row_count": 3,
           "fields": {"City": "تهران"}}
    ctx = build_context(rec, sender_name="تیم", attachment="/x/1001.xlsx")
    text = render("{seller_name} ({seller id}) {{email}} {city} {file_name} {row_count} {unknown}", ctx)
    assert text.startswith("فروشگاه علی (1001) ali@shop.ir تهران 1001.xlsx ۳")
    assert "{unknown}" in text
    assert unknown_placeholders("{seller_name} {nope}", ctx) == ["nope"]


def test_text_to_html_escapes_and_formats():
    html = text_to_html("سلام <b>\n\n- یک\n- دو\n\n**مهم** https://x.ir", "امضا")
    assert "&lt;b&gt;" in html and "<ul" in html and "<strong>مهم</strong>" in html
    assert 'href="https://x.ir"' in html and 'dir="rtl"' in html and "امضا" in html


def test_templates_and_smart_compose():
    assert len(TEMPLATES) >= 5
    out = smart_compose("ارسال صورت‌حساب آبان", has_attachment=True, deadline="۳۰ آبان")
    assert "{seller_name}" in out["subject"] and "پیوست" in out["body"] and "۳۰ آبان" in out["body"]
