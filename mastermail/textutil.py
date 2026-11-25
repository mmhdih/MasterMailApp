"""Small text helpers shared across the app: digits, Jalali dates, normalisation."""
from __future__ import annotations

import datetime as _dt
import re

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_ASCII = str.maketrans(_FA_DIGITS + _AR_DIGITS, "0123456789" * 2)
_TO_FA = str.maketrans("0123456789", _FA_DIGITS)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def to_ascii_digits(text: str) -> str:
    return str(text).translate(_TO_ASCII)


def to_fa_digits(text: object) -> str:
    return str(text).translate(_TO_FA)


def norm_key(text: object) -> str:
    """Normalise a column / placeholder name for loose matching."""
    value = to_ascii_digits(str(text)).strip().lower()
    value = value.replace("‌", " ").replace("ي", "ی").replace("ك", "ک")
    value = re.sub(r"[\s_\-.]+", " ", value)
    return value.strip()


def clean_email(value: object) -> str:
    text = to_ascii_digits(str(value or "")).strip().strip("<>").strip()
    text = text.replace("mailto:", "")
    # A cell can hold several addresses; keep them, separated by commas.
    parts = [p.strip("<>") for p in re.split(r"[;,،؛\s]+", text) if p.strip("<>")]
    return ", ".join(parts)


def is_valid_email(value: str) -> bool:
    parts = [p.strip() for p in str(value or "").split(",") if p.strip()]
    return bool(parts) and all(EMAIL_RE.match(p) for p in parts)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_today(today: _dt.date | None = None, persian_digits: bool = True) -> str:
    today = today or _dt.date.today()
    jy, jm, jd = gregorian_to_jalali(today.year, today.month, today.day)
    text = f"{jd} {JALALI_MONTHS[jm - 1]} {jy}"
    return to_fa_digits(text) if persian_digits else text


def jalali_month_label(today: _dt.date | None = None) -> str:
    today = today or _dt.date.today()
    jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
    return to_fa_digits(f"{JALALI_MONTHS[jm - 1]} {jy}")


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return str(value).strip()
