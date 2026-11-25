"""Split one sheet into one file per distinct value of a column.

Ported from ExcelSeparator, rebuilt on openpyxl so it shares the reader with
the rest of the app and keeps original column order and headers intact.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from openpyxl import Workbook

from .ids import normalise_id
from .naming import BLANK_LABEL, UniqueNamer, safe_filename, safe_sheet_name
from .tabular import Table, TableError, fill_sheet, looks_persian, write_table
from .textutil import cell_text

MAX_SHEETS_PER_WORKBOOK = 200
OUTPUT_FORMATS = ("xlsx", "csv")

Progress = Callable[[int, int, str], None]


class SplitCancelled(Exception):
    pass


@dataclass
class SplitResult:
    output_dir: str = ""
    files: dict[str, str] = field(default_factory=dict)   # group value -> path
    counts: dict[str, int] = field(default_factory=dict)  # group value -> rows
    row_count: int = 0
    skipped_blank_rows: int = 0

    def to_dict(self) -> dict:
        return {
            "output_dir": self.output_dir,
            "files": self.files,
            "counts": self.counts,
            "file_count": len(set(self.files.values())),
            "group_count": len(self.counts),
            "row_count": self.row_count,
            "skipped_blank_rows": self.skipped_blank_rows,
        }


def group_rows(table: Table, column: str, include_blanks: bool = True, as_id: bool = False) -> list[tuple[str, list[dict]]]:
    if column not in table.headers:
        raise TableError(f"ستون «{column}» در فایل وجود ندارد.")
    groups: dict[str, list[dict]] = {}
    blanks: list[dict] = []
    for row in table.rows:
        value = cell_text(row.get(column))
        if as_id:
            value = normalise_id(value)
        if not value:
            blanks.append(row)
            continue
        groups.setdefault(value, []).append(row)
    ordered = list(groups.items())
    if include_blanks and blanks:
        ordered.append((BLANK_LABEL, blanks))
    return ordered


def split_table(
    table: Table,
    column: str,
    output_dir: str | Path,
    *,
    output_format: str = "xlsx",
    single_workbook: bool = False,
    include_blanks: bool = True,
    file_prefix: str = "",
    file_suffix: str = "",
    as_id: bool = False,
    only_values: set[str] | None = None,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
    source_name: str = "خروجی",
) -> SplitResult:
    if output_format not in OUTPUT_FORMATS:
        raise TableError("قالب خروجی نامعتبر است.")
    if single_workbook and output_format == "csv":
        raise TableError("حالت «یک فایل چندشیتی» فقط با قالب اکسل کار می‌کند.")
    groups = group_rows(table, column, include_blanks, as_id)
    if only_values is not None:
        groups = [(k, v) for k, v in groups if k in only_values]
    if not groups:
        raise TableError("هیچ گروهی برای جداسازی پیدا نشد؛ ستون انتخاب‌شده خالی است.")
    if single_workbook and len(groups) > MAX_SHEETS_PER_WORKBOOK:
        raise TableError(
            f"تعداد گروه‌ها ({len(groups)}) برای یک فایل چندشیتی زیاد است؛ حداکثر {MAX_SHEETS_PER_WORKBOOK} شیت."
        )
    out = Path(output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TableError(f"پوشه خروجی ساخته نشد: {exc}") from exc

    result = SplitResult(output_dir=str(out))
    if not include_blanks:
        result.skipped_blank_rows = sum(1 for r in table.rows if not cell_text(r.get(column)))
    rtl = looks_persian(table)
    total = len(groups)

    if single_workbook:
        path = out / f"{safe_filename(source_name)}-تفکیک‌شده.xlsx"
        wb = Workbook()
        wb.remove(wb.active)
        namer = UniqueNamer(max_length=31)
        for index, (label, rows) in enumerate(groups, start=1):
            _check(cancel)
            ws = wb.create_sheet(namer.make_unique(safe_sheet_name(label)))
            fill_sheet(ws, table.headers, rows, rtl)
            result.files[label] = str(path)
            result.counts[label] = len(rows)
            result.row_count += len(rows)
            _report(progress, index, total, label)
        try:
            wb.save(path)
        except PermissionError as exc:
            raise TableError(f"فایل «{path.name}» قابل نوشتن نیست؛ شاید در اکسل باز باشد.") from exc
        return result

    namer = UniqueNamer()
    for index, (label, rows) in enumerate(groups, start=1):
        _check(cancel)
        name = namer.make_unique(safe_filename(f"{file_prefix}{label}{file_suffix}"))
        path = out / f"{name}.{output_format}"
        write_table(path, Table(list(table.headers), rows), safe_sheet_name(label), rtl)
        result.files[label] = str(path)
        result.counts[label] = len(rows)
        result.row_count += len(rows)
        _report(progress, index, total, label)
    return result


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise SplitCancelled()


def _report(progress: Progress | None, done: int, total: int, label: str) -> None:
    if progress:
        try:
            progress(done, total, label)
        except Exception:  # noqa: BLE001
            pass


def remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
