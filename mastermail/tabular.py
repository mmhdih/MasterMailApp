"""Reading and writing spreadsheets (xlsx / xlsm / xls / csv) without pandas.

openpyxl + csv cover everything the app needs and keep the portable exe small.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .textutil import cell_text, is_valid_email, norm_key

EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}
LEGACY_EXCEL_SUFFIXES = {".xls"}
CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
SUPPORTED_SUFFIXES = EXCEL_SUFFIXES | LEGACY_EXCEL_SUFFIXES | CSV_SUFFIXES

ID_CANDIDATES = [
    "seller id", "sellerid", "seller code", "seller_id", "id", "شناسه فروشنده",
    "شناسه", "کد فروشنده", "ای دی", "آیدی فروشنده", "آی دی فروشنده", "کد تامین کننده",
]
EMAIL_CANDIDATES = ["email", "e mail", "mail", "seller email", "ایمیل", "پست الکترونیک", "رایانامه"]
NAME_CANDIDATES = [
    "seller name", "business name fa", "business name", "name", "shop name", "store name",
    "نام فروشنده", "نام تجاری", "نام فروشگاه", "فروشنده", "نام",
]

_PERSIAN_RE = re.compile(r"[؀-ۿ]")


class TableError(Exception):
    """Anything the user needs to fix about an input or output file."""


class Table:
    """A sheet in memory: ordered headers plus row dicts."""

    def __init__(self, headers: list[str], rows: list[dict[str, Any]], sheet: str = ""):
        self.headers = headers
        self.rows = rows
        self.sheet = sheet

    def __len__(self) -> int:
        return len(self.rows)

    def ensure_column(self, name: str) -> None:
        if name not in self.headers:
            self.headers.append(name)
            for row in self.rows:
                row.setdefault(name, "")

    def column_values(self, column: str) -> list[str]:
        return [cell_text(row.get(column)) for row in self.rows]


# ----------------------------------------------------------------------------
# reading
# ----------------------------------------------------------------------------
def _check_path(path: str) -> Path:
    if not path:
        raise TableError("مسیر فایل خالی است.")
    file_path = Path(path)
    if not file_path.is_file():
        raise TableError(f"فایل پیدا نشد: {file_path.name}")
    if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise TableError("فرمت فایل پشتیبانی نمی‌شود. فقط xlsx، xls و csv مجاز است.")
    return file_path


def sheet_names(path: str) -> list[str]:
    file_path = _check_path(path)
    suffix = file_path.suffix.lower()
    if suffix in CSV_SUFFIXES:
        return []
    if suffix in LEGACY_EXCEL_SUFFIXES:
        book = _open_xls(file_path)
        return book.sheet_names()
    try:
        wb = load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise TableError(f"فایل اکسل باز نشد: {exc}") from exc
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _clean(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def unique_headers(raw: Iterable[Any]) -> list[str]:
    headers: list[str] = []
    for index, cell in enumerate(raw):
        name = cell_text(cell)
        if not name:
            name = f"ستون {index + 1}"
        base, counter = name, 2
        while name in headers:
            name = f"{base} ({counter})"
            counter += 1
        headers.append(name)
    return headers


def _rows_to_table(raw_rows: list[list[Any]], header_row: int, sheet: str) -> Table:
    if header_row < 1:
        raise TableError("شماره سطر عنوان باید حداقل ۱ باشد.")
    if len(raw_rows) < header_row:
        raise TableError("این شیت داده‌ای ندارد.")
    # Drop trailing empty columns that Excel often reports.
    width = 0
    for raw in raw_rows:
        for idx in range(len(raw) - 1, -1, -1):
            if cell_text(raw[idx]):
                width = max(width, idx + 1)
                break
    headers = unique_headers(list(raw_rows[header_row - 1])[:width] + [None] * max(0, width - len(raw_rows[header_row - 1])))
    rows: list[dict[str, Any]] = []
    for raw in raw_rows[header_row:]:
        values = list(raw)[:width] + [None] * max(0, width - len(raw))
        row = {headers[i]: _clean(values[i]) for i in range(width)}
        if any(cell_text(v) for v in row.values()):
            rows.append(row)
    if not headers:
        raise TableError("هیچ ستونی در این شیت پیدا نشد.")
    return Table(headers, rows, sheet)


def read_table(path: str, sheet: str = "", header_row: int = 1) -> Table:
    file_path = _check_path(path)
    suffix = file_path.suffix.lower()
    if suffix in CSV_SUFFIXES:
        return _rows_to_table(_read_delimited(file_path), header_row, "CSV")
    if suffix in LEGACY_EXCEL_SUFFIXES:
        book = _open_xls(file_path)
        names = book.sheet_names()
        name = sheet if sheet in names else names[0]
        ws = book.sheet_by_name(name)
        raw = [ws.row_values(i) for i in range(ws.nrows)]
        return _rows_to_table(raw, header_row, name)
    try:
        wb = load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise TableError(f"فایل اکسل باز نشد: {exc}") from exc
    try:
        name = sheet if sheet and sheet in wb.sheetnames else wb.sheetnames[0]
        raw = [list(r) for r in wb[name].iter_rows(values_only=True)]
    finally:
        wb.close()
    return _rows_to_table(raw, header_row, name)


def _open_xls(file_path: Path):
    try:
        import xlrd  # type: ignore
    except ImportError as exc:
        raise TableError("برای خواندن فایل‌های قدیمی xls بسته xlrd لازم است؛ فایل را با فرمت xlsx ذخیره کنید.") from exc
    try:
        return xlrd.open_workbook(str(file_path))
    except Exception as exc:  # noqa: BLE001
        raise TableError(f"فایل xls باز نشد: {exc}") from exc


def _read_delimited(file_path: Path) -> list[list[str]]:
    raw = file_path.read_bytes()
    for encoding in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    delimiter = "\t" if file_path.suffix.lower() == ".tsv" else ","
    sample = text[:8192]
    if sample:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            pass
    return [row for row in csv.reader(text.splitlines(), delimiter=delimiter)]


# ----------------------------------------------------------------------------
# column detection
# ----------------------------------------------------------------------------
def _match_column(headers: list[str], candidates: list[str]) -> str:
    keyed = {norm_key(h): h for h in headers}
    for cand in candidates:
        if norm_key(cand) in keyed:
            return keyed[norm_key(cand)]
    return ""


def detect_columns(table: Table) -> dict[str, str]:
    """Best guess for the seller-id, email and name columns ('' when unsure)."""
    headers = table.headers
    id_col = _match_column(headers, ID_CANDIDATES)
    if not id_col:
        for h in headers:
            k = norm_key(h)
            if ("seller" in k and ("id" in k or "code" in k)) or ("شناسه" in k and "فروشنده" in k):
                id_col = h
                break
    email_col = _match_column(headers, EMAIL_CANDIDATES)
    if not email_col:
        sample = table.rows[:50]
        for h in headers:
            values = [cell_text(r.get(h)) for r in sample if cell_text(r.get(h))]
            if values and sum(is_valid_email(v) for v in values) >= max(1, len(values) * 0.6):
                email_col = h
                break
    name_col = _match_column([h for h in headers if h not in (id_col, email_col)], NAME_CANDIDATES)
    return {"id": id_col, "email": email_col, "name": name_col}


def describe_columns(table: Table, limit_rows: int | None = None) -> list[dict[str, Any]]:
    rows = table.rows if limit_rows is None else table.rows[:limit_rows]
    info = []
    for h in table.headers:
        values = [cell_text(r.get(h)) for r in rows]
        filled = [v for v in values if v]
        uniques = list(dict.fromkeys(filled))
        info.append({
            "name": h,
            "unique": len(uniques),
            "blank": len(values) - len(filled),
            "sample": uniques[0] if uniques else "",
        })
    return info


# ----------------------------------------------------------------------------
# writing
# ----------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor="0A84FF")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Vazirmatn")
BODY_FONT = Font(name="Vazirmatn")
THIN = Side(style="thin", color="E5E5EA")


def looks_persian(table: Table) -> bool:
    sample = " ".join(table.headers) + " " + " ".join(
        cell_text(v) for r in table.rows[:20] for v in r.values()
    )
    return bool(_PERSIAN_RE.search(sample))


def fill_sheet(ws, headers: list[str], rows: Iterable[dict[str, Any]], rtl: bool | None = None) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = [max(10, min(60, len(str(h)) + 4)) for h in headers]
    for row in rows:
        values = [row.get(h, "") for h in headers]
        ws.append(values)
        for i, v in enumerate(values):
            widths[i] = max(widths[i], min(60, len(cell_text(v)) + 2))
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 24
    if headers:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, ws.max_row)}"
    if rtl:
        ws.sheet_view.rightToLeft = True


def write_table(path: str | Path, table: Table, sheet_title: str = "Sheet1", rtl: bool | None = None) -> Path:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(file_path.name + ".tmp")
    if rtl is None:
        rtl = looks_persian(table)
    try:
        if file_path.suffix.lower() in CSV_SUFFIXES:
            with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(table.headers)
                for row in table.rows:
                    writer.writerow([cell_text(row.get(h, "")) for h in table.headers])
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = sheet_title[:31] or "Sheet1"
            fill_sheet(ws, table.headers, table.rows, rtl)
            wb.save(tmp)
        os.replace(tmp, file_path)
    except PermissionError as exc:
        _silent_unlink(tmp)
        raise TableError(f"فایل «{file_path.name}» قابل نوشتن نیست؛ احتمالاً در اکسل باز است.") from exc
    except OSError as exc:
        _silent_unlink(tmp)
        raise TableError(f"ذخیره فایل ناموفق بود: {exc}") from exc
    return file_path


def _silent_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
