"""Damodaran 接入：表头识别、重复表头取第一个、汇总行之前停止、错误页与版式变化报错。

xlrd 只能读取 .xls，测试用一个假的工作簿对象代替文件格式，只检验接入器自己的逻辑。
"""

import dataclasses

import pytest
import xlrd

from investment_os.connectors import damodaran
from investment_os.connectors.damodaran import BASE_URL, DamodaranXlsConnector
from investment_os.data import ingest

from .conftest import NO_RETRY, FakeHttp

XLS_MAGIC = b"\xd0\xcf\x11\xe0" + b"\0" * 60

# 与 histretSP.xls 相同的结构：说明行 → 表头（右侧重复出现「$100 价值」同名列）→ 逐年数据 → 汇总
ROWS = [
    ["Date updated:", 44561.0, "", "", ""],
    ["", "Annual Returns on Investments in", "", "Value of $100 invested", ""],
    ["Year", "S&P 500 (includes dividends)", " Baa Corporate Bond", "S&P 500 (includes dividends)", "Gold*"],
    [2023.0, 0.2606, 0.0874, 126.06, 0.13],
    [2024.0, 0.2488, "", 157.42, 0.26],
    [2025.0, 0.1772, 0.0696, 185.32, 0.66],
    ["", "", "", "", ""],
    ["Arithmetic Average Historical Return", "", "", "", ""],
    ["1928-2025", 0.1185, 0.07, "", ""],
]


class FakeSheet:
    def __init__(self, rows):
        self.rows, self.nrows, self.ncols = rows, len(rows), len(rows[0])

    def cell_value(self, r, c):
        return self.rows[r][c]


class FakeBook:
    def __init__(self, sheets):
        self.sheets = sheets

    def sheet_by_name(self, name):
        if name not in self.sheets:
            raise xlrd.XLRDError(f"No sheet named <{name}>")
        return self.sheets[name]

    def sheet_names(self):
        return list(self.sheets)


@pytest.fixture
def fake_book(monkeypatch):
    book = FakeBook({"Returns by year": FakeSheet(ROWS)})
    monkeypatch.setattr(damodaran.xlrd, "open_workbook", lambda **kw: book)
    return book


def _connector(body: bytes = XLS_MAGIC) -> DamodaranXlsConnector:
    return DamodaranXlsConnector(http_get=FakeHttp({f"{BASE_URL}/histretSP.xls": body}), **NO_RETRY)


def _with_columns(registry, columns):
    spec = registry.datasets["damodaran_histret"]
    registry.datasets["damodaran_histret"] = dataclasses.replace(spec, params={**spec.params, "columns": columns})


def test_reads_year_rows_under_the_header_and_stops_at_summaries(registry, store, fake_book):
    _with_columns(registry, {"SP500": "S&P 500 (includes dividends)", "BAA": "Baa Corporate Bond", "GOLD": "Gold*"})
    r = ingest(registry, store, "damodaran_histret", {}, _connector())
    assert r.status == "created" and r.version.rows == 9  # 3 年 × 3 列；汇总行不读入
    df, v = store.load("damodaran_histret")
    rows = {(x.series_id, x.observation_at.year): x for x in df.itertuples()}
    assert rows[("DAM_SP500", 2025)].value == 0.1772  # 取左侧年度回报，不是右侧同名的「$100 价值」列
    assert rows[("DAM_BAA", 2024)].quality_status == "missing"  # 空单元格
    assert v.series["DAM_GOLD"]["column"] == "Gold*"
    assert v.raw_snapshots[0]["path"].endswith(".xls")


def test_layout_changes_and_error_pages_fail(registry, store, fake_book):
    _with_columns(registry, {"SP500": "S&P 500 (incl. dividends)"})
    r = ingest(registry, store, "damodaran_histret", {}, _connector())
    assert r.status == "failed" and "表头中找不到" in r.message

    _with_columns(registry, {"SP500": "S&P 500 (includes dividends)"})
    spec = registry.datasets["damodaran_histret"]
    registry.datasets["damodaran_histret"] = dataclasses.replace(spec, params={**spec.params, "sheet": "Returns"})
    r = ingest(registry, store, "damodaran_histret", {}, _connector())
    assert r.status == "failed" and "找不到工作表" in r.message

    r = ingest(registry, store, "damodaran_histret", {}, _connector(b"<html>moved</html>"))
    assert r.status == "failed" and "不是 .xls" in r.message
    assert store.latest("damodaran_histret") is None


def test_registered_dataset_is_annual_local_and_scheduled(registry):
    spec = registry.datasets["damodaran_histret"]
    assert spec.frequency == "annual" and spec.scheduled_fetch == {} and not spec.archive_data
    assert len(spec.params["columns"]) == 7
