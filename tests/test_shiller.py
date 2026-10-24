"""Shiller 接入：从页面找下载链接、按第 8 行短名称与列位置核对、解析「年.月」小数日期。

xlrd 只能读取 .xls，测试用假的工作簿对象代替文件格式，只检验接入器自己的逻辑。
"""

import dataclasses

import pytest
import xlrd

from investment_os.connectors import shiller
from investment_os.connectors.shiller import PAGE_URL, ShillerXlsConnector, year_month
from investment_os.data import ingest

from .conftest import NO_RETRY, FakeHttp

XLS = b"\xd0\xcf\x11\xe0" + b"\0" * 60
LINK = "//img1.wsimg.com/blobby/go/abc/downloads/def/ie_data.xls?ver=123"
PAGE = f'<a href="{LINK}">US Stock Markets</a> <a href="//img1.wsimg.com/x/Fig3-1.xls">fig</a>'.encode()


def frac(y, m):
    return y + (m - 0.5) / 12


HEADER = ["Date", "P", "D", "E", "CPI", "Fraction", "Rate GS10", "Price", "Dividend", "Price", "Earnings",
          "Earnings", "CAPE", "", "TR CAPE"]


def row(date_value, y, m, p, d, cape):
    return [date_value, p, d, 1.0, 300.0, frac(y, m), 4.0, p, d, p * 10, 1.0, 1.0, cape, "", cape + 2]


ROWS = [
    ["Stock Market Data Used in \"Irrational Exuberance\""] + [""] * 14,
    HEADER,
    row(2026.09, 2026, 9, 7669.4, 81.2, 40.58),
    row(2026.1, 2026, 10, 7722.7, "", 40.71),   # 10 月；股息尚未补上
    row(2026.11, 2026, 11, 7800.0, "NA", 41.0),
    [""] * 15,
]


class FakeSheet:
    def __init__(self, rows):
        self.rows, self.nrows, self.ncols = rows, len(rows), len(rows[0])

    def cell_value(self, r, c):
        return self.rows[r][c]


class FakeBook:
    def __init__(self, rows):
        self.sheet = FakeSheet(rows)

    def sheet_by_name(self, name):
        if name != "Data":
            raise xlrd.XLRDError(f"No sheet named <{name}>")
        return self.sheet


@pytest.fixture
def book(monkeypatch):
    holder = {"rows": [list(r) for r in ROWS]}
    monkeypatch.setattr(shiller.xlrd, "open_workbook", lambda **kw: FakeBook(holder["rows"]))
    return holder


def _connector(page: bytes = PAGE, body: bytes = XLS) -> ShillerXlsConnector:
    return ShillerXlsConnector(http_get=FakeHttp({PAGE_URL: page, f"https:{LINK}": body}), **NO_RETRY)


def _columns(registry, dataset_id, columns):
    spec = registry.datasets[dataset_id]
    registry.datasets[dataset_id] = dataclasses.replace(spec, params={**spec.params, "columns": columns})


@pytest.mark.parametrize("value,expected", [(2026.01, (2026, 1)), (2026.1, (2026, 10)), (2026.12, (2026, 12)),
                                            (1871.09, (1871, 9)), (1871.11, (1871, 11))])
def test_year_dot_month_dates(value, expected):
    assert year_month(value) == expected


def test_finds_the_link_reads_by_position_and_marks_missing(registry, store, book):
    r = ingest(registry, store, "shiller_fundamentals", {}, _connector())
    assert r.status == "created"
    df, v = store.load("shiller_fundamentals")
    rows = {(x.series_id, x.observation_at.strftime("%Y-%m")): x for x in df.itertuples()}
    assert rows[("SHILLER_D", "2026-09")].value == 81.2
    assert rows[("SHILLER_D", "2026-10")].quality_status == "missing"  # 空单元格
    assert rows[("SHILLER_D", "2026-11")].quality_status == "missing"  # 'NA'
    assert v.raw_snapshots[0]["url"] == f"https:{LINK}"  # 记录实际下载的带版本号地址
    assert v.series["SHILLER_D"]["column"] == "D"

    r = ingest(registry, store, "shiller_real", {}, _connector())
    df, _ = store.load("shiller_real")
    tr = df[df.series_id == "SHILLER_REAL_TR_PRICE"]
    tr = tr.set_index(tr.observation_at.dt.strftime("%Y-%m"))
    assert tr.loc["2026-10"].value == pytest.approx(77227.0)  # 第 9 列，不是同名的第 7 列


def test_page_must_have_exactly_one_link(registry, store, book):
    r = ingest(registry, store, "shiller_price", {}, _connector(page=b"<html>no data link</html>"))
    assert r.status == "failed" and "找到 0 个" in r.message
    two = PAGE + LINK.replace("ver=123", "ver=999").encode()
    r = ingest(registry, store, "shiller_price", {}, _connector(page=two))
    assert r.status == "failed" and "找到 2 个" in r.message
    r = ingest(registry, store, "shiller_price", {}, _connector(body=b"<html>gone</html>"))
    assert r.status == "failed" and "不是 .xls" in r.message


def test_layout_and_date_checks(registry, store, book):
    _columns(registry, "shiller_cape", {"CAPE": {"col": 13, "label": "CAPE"}})
    r = ingest(registry, store, "shiller_cape", {}, _connector())
    assert r.status == "failed" and "第 13 列应为「CAPE」" in r.message

    _columns(registry, "shiller_cape", {"CAPE": {"col": 12, "label": "CAPE"}})
    book["rows"][3][5] = frac(2026, 1)  # 如果把 2026.1 误读成 1 月，Date Fraction 对不上
    r = ingest(registry, store, "shiller_cape", {}, _connector())
    assert r.status == "failed" and "Date Fraction" in r.message

    book["rows"][3][5] = frac(2026, 10)
    del book["rows"][3]  # 少了 10 月：月份不连续
    r = ingest(registry, store, "shiller_cape", {}, _connector())
    assert r.status == "failed" and "不连续" in r.message
    assert store.latest("shiller_cape") is None


def test_registered_datasets_are_monthly_local_and_scheduled(registry):
    for dataset_id in ("shiller_price", "shiller_fundamentals", "shiller_cape", "shiller_real"):
        spec = registry.datasets[dataset_id]
        assert spec.frequency == "monthly" and spec.scheduled_fetch == {} and not spec.archive_data
    assert registry.datasets["shiller_fundamentals"].availability.days == 180  # 股息与盈利滞后补上
