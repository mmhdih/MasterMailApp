from openpyxl import Workbook, load_workbook

from mastermail.splitter import split_table
from mastermail.tabular import Table, detect_columns, read_table, write_table


def make_report(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Seller ID", "نام فروشنده", "کالا", "مبلغ"])
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_read_and_detect(tmp_path):
    p = tmp_path / "r.xlsx"
    make_report(p, [[1001.0, "علی", "کتاب", 10], [1002, "سارا", "قلم", 5], [None, None, None, None]])
    t = read_table(str(p))
    assert t.headers == ["Seller ID", "نام فروشنده", "کالا", "مبلغ"]
    assert len(t.rows) == 2 and t.rows[0]["Seller ID"] == 1001
    cols = detect_columns(t)
    assert cols == {"id": "Seller ID", "email": "", "name": "نام فروشنده"}


def test_detect_email_by_content(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("code;contact\n1;a@b.ir\n2;c@d.ir\n", encoding="utf-8")
    t = read_table(str(p))
    assert detect_columns(t)["email"] == "contact"


def test_split_files_and_single_workbook(tmp_path):
    t = Table(["seller", "v"], [{"seller": "1/1", "v": 1}, {"seller": "1:1", "v": 2}, {"seller": "", "v": 3}, {"seller": "CON", "v": 4}])
    res = split_table(t, "seller", tmp_path / "out")
    names = sorted(p.split("/")[-1] for p in res.files.values())
    assert names == ["1-1-2.xlsx", "1-1.xlsx", "CON-1.xlsx", "بدون مقدار.xlsx"]
    assert res.row_count == 4
    wb = load_workbook(res.files["1/1"])
    assert [c.value for c in wb.active[1]] == ["seller", "v"]

    res2 = split_table(t, "seller", tmp_path / "one", single_workbook=True, include_blanks=False)
    assert len(set(res2.files.values())) == 1 and res2.skipped_blank_rows == 1
    assert len(load_workbook(next(iter(res2.files.values()))).sheetnames) == 3


def test_split_only_values_as_ids(tmp_path):
    t = Table(["id", "x"], [{"id": 1001.0, "x": 1}, {"id": "1001", "x": 2}, {"id": "1002", "x": 3}])
    res = split_table(t, "id", tmp_path, as_id=True, only_values={"1001"}, include_blanks=False)
    assert list(res.counts.items()) == [("1001", 2)]


def test_write_csv_roundtrip(tmp_path):
    p = tmp_path / "o.csv"
    write_table(p, Table(["a", "ب"], [{"a": 1, "ب": "فارسی"}]))
    assert read_table(str(p)).rows == [{"a": "1", "ب": "فارسی"}]
