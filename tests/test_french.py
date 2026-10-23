"""Kenneth French Data Library 接入：多段 CSV 的分段、表头核对、缺失值与频率。"""

import dataclasses
import io
import zipfile

import pytest

from investment_os.connectors.french import BASE_URL, FrenchLibraryConnector
from investment_os.data import ingest

from .conftest import NO_RETRY, FakeHttp

# 三因子文件的版式：说明文字 → 月度表（无标题）→ 年度表 → 版权行；202402 的 HML 用 -99.99 表示缺失
FACTORS = """This file was created using the 202403 CRSP database.
The 1-month TBill rate data until 202405 are from Ibbotson Associates.

,Mkt-RF,SMB,HML,RF
202401,   0.70,  -5.09,  -2.38,   0.47
202402,   5.06,  -0.27, -99.99,   0.42
202403,   2.83,  -2.48,   4.21,   0.43

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RF
  2023,  21.69,  -3.34,  -1.08,   5.03

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

INDUSTRY = """This file was created using the 202402 CRSP database.
Missing data are indicated by -99.99 or -999.

  Average Value Weighted Returns -- Monthly
,NoDur,Money
202401,   1.10,   2.20
202402,   3.30,  -999

  Average Equal Weighted Returns -- Monthly
,NoDur,Money
202401,   9.10,   9.20
202402,   9.30,   9.40
"""


def _zip(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}.csv", text.replace("\n", "\r\n"))
    return buf.getvalue()


def _connector(file: str, body: bytes) -> FrenchLibraryConnector:
    return FrenchLibraryConnector(http_get=FakeHttp({f"{BASE_URL}/{file}_CSV.zip": body}), **NO_RETRY)


def _rows(store, dataset_id):
    df, version = store.load(dataset_id)
    return {(r.series_id, r.observation_at.strftime("%Y-%m")): r for r in df.itertuples()}, version


def test_factors_take_the_monthly_section_and_mark_sentinels_missing(registry, store):
    r = ingest(registry, store, "french_ff3", {},
               _connector("F-F_Research_Data_Factors", _zip("F-F_Research_Data_Factors", FACTORS)))
    assert r.status == "created" and r.version.rows == 12  # 3 个月 × 4 列；年度表不读入
    rows, v = _rows(store, "french_ff3")
    assert rows[("FF3_Mkt-RF", "2024-02")].value == 5.06
    assert rows[("FF3_RF", "2024-03")].value == 0.43
    hml = rows[("FF3_HML", "2024-02")]
    assert hml.quality_status == "missing"  # -99.99 是缺失，不是 -99.99% 的收益
    assert v.series["FF3_HML"]["crsp_database"] == "202403"
    assert v.series["FF3_HML"]["section"] == "（第一段）"
    assert v.raw_snapshots[0]["path"].endswith(".zip")


def test_industry_reads_the_named_section(registry, store):
    spec = registry.datasets["french_ind12_vw"]
    registry.datasets["french_ind12_vw"] = dataclasses.replace(
        spec, params={**spec.params, "columns": ["NoDur", "Money"]})
    r = ingest(registry, store, "french_ind12_vw", {},
               _connector("12_Industry_Portfolios", _zip("12_Industry_Portfolios", INDUSTRY)))
    assert r.status == "created"
    rows, _ = _rows(store, "french_ind12_vw")
    assert rows[("IND12VW_NoDur", "2024-02")].value == 3.30  # 价值加权，不是等权段的 9.30
    assert rows[("IND12VW_Money", "2024-02")].quality_status == "missing"  # -999


def test_layout_changes_fail_instead_of_reading_the_wrong_table(registry, store):
    renamed = FACTORS.replace(",Mkt-RF,SMB,HML,RF\n202401", ",Mkt-RF,SMB,HML,RMW\n202401")
    r = ingest(registry, store, "french_ff3", {},
               _connector("F-F_Research_Data_Factors", _zip("F-F_Research_Data_Factors", renamed)))
    assert r.status == "failed" and "表头" in r.message
    assert store.latest("french_ff3") is None

    spec = registry.datasets["french_ind12_vw"]
    registry.datasets["french_ind12_vw"] = dataclasses.replace(
        spec, params={**spec.params, "section": "Average Value Weighted Returns -- Daily",
                      "columns": ["NoDur", "Money"]})
    r = ingest(registry, store, "french_ind12_vw", {},
               _connector("12_Industry_Portfolios", _zip("12_Industry_Portfolios", INDUSTRY)))
    assert r.status == "failed" and "找到 0 段" in r.message


def test_error_page_and_wrong_frequency_are_rejected(registry, store):
    r = ingest(registry, store, "french_mom", {},
               _connector("F-F_Momentum_Factor", b"<html>Not Found</html>"))
    assert r.status == "failed" and "不是 zip" in r.message

    annual_first = "x\n\n,Mom\n  2023,  1.0\n"
    r = ingest(registry, store, "french_mom", {},
               _connector("F-F_Momentum_Factor", _zip("F-F_Momentum_Factor", annual_first)))
    assert r.status == "failed" and "与频率 monthly 不符" in r.message


@pytest.mark.parametrize("dataset_id", ["french_ff3", "french_ff5", "french_mom", "french_ind12_vw"])
def test_french_datasets_are_scheduled_and_local_only(registry, dataset_id):
    spec = registry.datasets[dataset_id]
    assert spec.scheduled_fetch == {} and not spec.archive_data  # 未见再分发许可，不进公开存档
