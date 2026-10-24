"""SEC EDGAR 财报：FSDS 解析与过滤、增量同步、指标别名、修正申报与时点视图（docs/edgar-design.md）。"""

import io
import json
import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from investment_os.connectors.base import FetchError
from investment_os.connectors.sec import FSDS_URL, SecClient, fsds_quarters, parse_fsds
from investment_os.contracts import CompanySpec, FundamentalsSpec, MetricSpec
from investment_os.data.fundamentals import EdgarStore, annual_metric, source_agreement, sync_companyfacts, \
    sync_fsds
from investment_os.registry import Registry, RegistryError, load_fundamentals

from .conftest import PROJECT_ROOT

T0 = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
SUB_HEADER = ["adsh", "cik", "name", "sic", "fye", "form", "period", "fy", "fp", "filed", "accepted", "prevrpt"]
NUM_HEADER = ["adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value", "footnote"]


def fsds_zip(subs, nums) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sub.txt", "\n".join("\t".join(map(str, r)) for r in [SUB_HEADER, *subs]) + "\n")
        zf.writestr("num.txt", "\n".join("\t".join(map(str, r)) for r in [NUM_HEADER, *nums]) + "\n")
    return buf.getvalue()


# 2018 年的 10-K 用旧科目 SalesRevenueNet；2020 年的 10-K 用新科目，并重述了 2019 财年；
# 2021 年初的 10-K/A 修正了 2020 财年。另有 11-K、10-Q、分部与共同申报人的行，都不应进入年度指标。
SUBS_2018 = [
    ["A-2018", 1, "Acme", 3571, "0930", "10-K", 20180930, 2018, "FY", 20181102, "2018-11-02 16:30:00.0", 0],
    ["P-2018", 1, "Acme Plan", 3571, "1231", "11-K", 20171231, 2017, "FY", 20180601, "2018-06-01 09:00:00.0", 0],
    ["X-2018", 2, "Other", 1000, "1231", "10-K", 20181231, 2018, "FY", 20190201, "2019-02-01 09:00:00.0", 0],
]
NUMS_2018 = [
    ["A-2018", "SalesRevenueNet", "us-gaap/2018", 20180930, 4, "USD", "", "", "100.0", ""],
    ["A-2018", "SalesRevenueNet", "us-gaap/2018", 20180930, 4, "USD", "Segment=X", "", "60.0", ""],
    ["A-2018", "SalesRevenueNet", "us-gaap/2018", 20180930, 4, "USD", "", "Sub Inc", "40.0", ""],
    ["A-2018", "Assets", "us-gaap/2018", 20180930, 0, "USD", "", "", "500.0", ""],
    ["A-2018", "Assets", "us-gaap/2018", 20180630, 0, "USD", "", "", "450.0", ""],   # 非财年末余额
    ["P-2018", "NetAssets", "us-gaap/2018", 20171231, 0, "USD", "", "", "9.0", ""],
    ["X-2018", "Revenues", "us-gaap/2018", 20181231, 4, "USD", "", "", "7.0", ""],
]
SUBS_2020 = [
    ["A-2020", 1, "Acme", 3571, "0930", "10-K", 20200930, 2020, "FY", 20201030, "2020-10-30 18:05:00.0", 1],
    ["Q-2020", 1, "Acme", 3571, "0930", "10-Q", 20200630, 2020, "Q3", 20200731, "2020-07-31 16:00:00.0", 0],
]
NUMS_2020 = [
    ["A-2020", "RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap/2020", 20200930, 4, "USD", "", "", "130.0", ""],
    ["A-2020", "RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap/2020", 20190930, 4, "USD", "", "", "115.0", ""],
    ["A-2020", "Revenues", "us-gaap/2020", 20200930, 4, "USD", "", "", "999.0", ""],  # 别名靠后，不取
    ["Q-2020", "RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap/2020", 20200630, 3, "USD", "", "", "90.0", ""],
]
SUBS_2021 = [
    ["AMEND-2021", 1, "Acme", 3571, "0930", "10-K/A", 20200930, 2020, "FY", 20210115, "2021-01-15 10:00:00.0", 0],
]
NUMS_2021 = [
    ["AMEND-2021", "RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap/2020", 20200930, 4, "USD", "", "", "128.0", ""],
]
QUARTERS = {"2018q4": fsds_zip(SUBS_2018, NUMS_2018), "2020q4": fsds_zip(SUBS_2020, NUMS_2020),
            "2021q1": fsds_zip(SUBS_2021, NUMS_2021)}

SPEC = FundamentalsSpec(
    companies=(CompanySpec(1, "Acme"),),
    metrics={
        "revenue": MetricSpec("revenue", "duration", "USD", (
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"), ("us-gaap", "Revenues"),
            ("us-gaap", "SalesRevenueNet"))),
        "total_assets": MetricSpec("total_assets", "instant", "USD", (("us-gaap", "Assets"),)),
    })


class FakeSec:
    """按 URL 返回内容与文件头；记录请求，用来确认没有多余的下载。"""

    def __init__(self, files: dict[str, bytes], modified: dict[str, str] | None = None):
        self.files, self.modified, self.gets, self.heads = files, modified or {}, [], []

    def get(self, url, headers, timeout):
        self.gets.append(url)
        if url not in self.files:
            import urllib.error
            raise urllib.error.URLError(f"no route to {url}")
        return self.files[url]

    def head(self, url, headers, timeout):
        self.heads.append(url)
        if url not in self.files:
            return None
        return {"size": len(self.files[url]), "last_modified": self.modified.get(url, "Mon, 01 Jan 2024")}


def _client(fake, user_agent):
    return SecClient(user_agent=user_agent, get=fake.get, head=fake.head, sleep=lambda s: None, attempts=1)


def _fake(quarters=QUARTERS, modified=None):
    return FakeSec({FSDS_URL.format(quarter=q): b for q, b in quarters.items()}, modified)


def test_parse_keeps_registered_periodic_consolidated_rows():
    filings, facts = parse_fsds(QUARTERS["2018q4"], {1}, T0)
    assert list(filings["accession"]) == ["A-2018"]  # 11-K 与其他公司都不进入
    assert len(facts) == 3  # 分部与共同申报人的行不进入
    assert facts["taxonomy"].unique().tolist() == ["us-gaap"]
    # 接受时间 2018-11-02 16:30（美东）→ 次日 0 点（美东）= 04:00 UTC（夏令时）
    assert facts["available_at"].iloc[0] == pd.Timestamp("2018-11-03 04:00", tz="UTC")


def test_sync_downloads_once_then_only_checks_headers(tmp_path):
    fake = _fake()
    res = sync_fsds(tmp_path, SPEC, _client(fake, "ua"), quarters=list(QUARTERS) + ["2026q4"], clock=lambda: T0)
    assert [r["action"] for r in res] == ["downloaded", "downloaded", "downloaded", "not_published"]
    assert len(fake.gets) == 3
    res = sync_fsds(tmp_path, SPEC, _client(fake, "ua"), quarters=list(QUARTERS), clock=lambda: T0)
    assert [r["action"] for r in res] == ["unchanged"] * 3 and len(fake.gets) == 3  # 只发 HEAD，不再下载

    # 远端修改时间变了：重新下载；内容相同则原始文件复用、分区不建新版本
    fake.modified[FSDS_URL.format(quarter="2018q4")] = "Fri, 27 Dec 2024"
    res = sync_fsds(tmp_path, SPEC, _client(fake, "ua"), quarters=["2018q4"], clock=lambda: T0)
    assert res[0]["action"] == "downloaded" and res[0]["facts"] == "unchanged" and len(fake.gets) == 4
    assert len(list((tmp_path / "data/edgar/raw/fsds").glob("2018q4_*.zip"))) == 1

    # 内容变了但大小与修改时间都没变：HEAD 发现不了，只有 refresh 会重新下载
    url = FSDS_URL.format(quarter="2018q4")
    fake.files[url] = fsds_zip(SUBS_2018, [r[:8] + ["101.0", ""] if r[1] == "SalesRevenueNet" and not r[6] and not r[7]
                                           else r for r in NUMS_2018])
    res = sync_fsds(tmp_path, SPEC, _client(fake, "ua"), quarters=["2018q4"], clock=lambda: T0)
    assert res[0]["action"] == "unchanged"
    res = sync_fsds(tmp_path, SPEC, _client(fake, "ua"), quarters=["2018q4"], clock=lambda: T0.replace(hour=13),
                    refresh=True)
    assert res[0]["action"] == "downloaded" and res[0]["facts"] == "created"
    store = EdgarStore(tmp_path)
    assert len(list((store.base / "superseded/facts/source=fsds/key=2018q4").glob("*.parquet"))) == 1
    assert store.current("facts", "fsds", "2018q4")["parent_version"] is not None


def test_company_list_change_reparses_saved_raw_without_downloading(tmp_path):
    fake = _fake()
    sync_fsds(tmp_path, SPEC, _client(fake, "ua"), quarters=["2018q4"], clock=lambda: T0)
    wider = FundamentalsSpec(companies=SPEC.companies + (CompanySpec(2, "Other"),), metrics=SPEC.metrics)
    res = sync_fsds(tmp_path, wider, _client(fake, "ua"), quarters=["2018q4"], clock=lambda: T0)
    assert res[0]["action"] == "reparsed" and len(fake.gets) == 1
    assert res[0]["rows"]["filings"] == 2


def test_annual_metric_aliases_amendments_and_as_of(tmp_path):
    sync_fsds(tmp_path, SPEC, _client(_fake(), "ua"), quarters=list(QUARTERS), clock=lambda: T0)
    rev = annual_metric(tmp_path, SPEC, "revenue")
    by_year = {r.fiscal_year_end.year: r for r in rev.itertuples()}
    assert set(by_year) == {2018, 2019, 2020}  # 10-Q 的年初至今数字不进入
    assert by_year[2018].tag == "us-gaap:SalesRevenueNet" and by_year[2018].value == 100.0
    assert by_year[2019].value == 115.0  # 只在 2020 年报中作为对比数据出现
    # 2020 财年：原 10-K 为 130（不取靠后的 Revenues 999），10-K/A 修正为 128
    assert by_year[2020].value == 128.0 and by_year[2020].form == "10-K/A"
    assert by_year[2020].first_value == 130.0 and by_year[2020].filings == 2

    before = annual_metric(tmp_path, SPEC, "revenue", as_of=datetime(2020, 12, 1, tzinfo=timezone.utc))
    fy2020 = before[before["fiscal_year_end"] == pd.Timestamp("2020-09-30")]
    assert fy2020["value"].tolist() == [130.0]  # 修正申报之前只知道原值
    same_day = annual_metric(tmp_path, SPEC, "revenue", as_of=datetime(2020, 10, 30, 23, tzinfo=timezone.utc))
    assert set(same_day["fiscal_year_end"].dt.year) == {2018}  # 2019、2020 财年都只在 2020 年报中，接受当天尚不可用
    next_day = annual_metric(tmp_path, SPEC, "revenue", as_of=datetime(2020, 10, 31, 4, tzinfo=timezone.utc))
    assert 2020 in set(next_day["fiscal_year_end"].dt.year)

    assets = annual_metric(tmp_path, SPEC, "total_assets")
    assert assets["fiscal_year_end"].dt.strftime("%Y-%m-%d").tolist() == ["2018-09-30"]  # 只取财年末余额


def test_companyfacts_sync_and_agreement_with_fsds(tmp_path):
    sync_fsds(tmp_path, SPEC, _client(_fake(), "ua"), quarters=["2020q4"], clock=lambda: T0)
    doc = {"cik": 1, "entityName": "Acme", "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            {"start": "2019-10-01", "end": "2020-09-30", "val": 130, "accn": "A-2020", "fy": 2020, "fp": "FY",
             "form": "10-K", "filed": "2020-10-30"},
            {"start": "2018-10-01", "end": "2019-09-30", "val": 116, "accn": "A-2020", "fy": 2020, "fp": "FY",
             "form": "10-K", "filed": "2020-10-30"},
            {"start": "2020-10-01", "end": "2021-09-30", "val": 150, "accn": "A-2021", "fy": 2021, "fp": "FY",
             "form": "10-K", "filed": "2021-11-01"},
            {"start": "2020-10-01", "end": "2020-12-31", "val": 40, "accn": "S-1", "form": "S-1", "filed": "2021-02-01"},
        ]}}}}}
    fake = FakeSec({"https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json": json.dumps(doc).encode()})
    res = sync_companyfacts(tmp_path, SPEC, _client(fake, ""), clock=lambda: T0)  # data.sec.gov 不强制联系邮箱
    assert res[0]["status"] == "ok"
    store = EdgarStore(tmp_path)
    api = store.query("facts", "source = 'companyfacts'")
    assert set(api["duration_quarters"]) == {4} and "S-1" not in set(api["accession"])  # 非定期报告不进入
    rev = annual_metric(tmp_path, SPEC, "revenue")
    fy2021 = rev[rev["fiscal_year_end"] == pd.Timestamp("2021-09-30")].iloc[0]
    assert fy2021.value == 150.0  # FSDS 尚未收录的新申报由 API 补上
    # 只用申报日期时，可用时间为申报日次日 0 点（美东）
    assert fy2021.available_at == pd.Timestamp("2021-11-02 04:00", tz="UTC")
    agree = source_agreement(tmp_path, SPEC)
    assert len(agree) == 2 and agree["diff"].max() == 1.0  # 2019 财年 115 vs 116 被发现


def test_www_sec_gov_requires_a_contact_user_agent():
    fake = _fake()
    client = SecClient(user_agent="", get=fake.get, head=fake.head, sleep=lambda s: None, attempts=1)
    with pytest.raises(FetchError, match="SEC_USER_AGENT"):
        client.head(FSDS_URL.format(quarter="2018q4"))


def test_requests_are_spaced_out():
    waits, clock = [], iter([0.0, 0.0, 0.05, 0.2])
    fake = _fake()
    client = SecClient(user_agent="ua", get=fake.get, head=fake.head, sleep=waits.append,
                       monotonic=lambda: next(clock), attempts=1)
    client.head(FSDS_URL.format(quarter="2018q4"))
    client.head(FSDS_URL.format(quarter="2020q4"))
    assert waits == [pytest.approx(0.15)]


def test_quarter_list_and_registry():
    assert fsds_quarters(date(2009, 8, 1)) == ["2009q1", "2009q2", "2009q3"]
    spec = Registry.load(PROJECT_ROOT).fundamentals
    assert len(spec.companies) == 15 and len(spec.metrics) == 8
    assert spec.metrics["revenue"].tags[0] == ("us-gaap", "Revenues")  # 总营收科目在前（沃尔玛核对）


def test_fundamentals_registry_rejects_bad_entries(tmp_path):
    (tmp_path / "f.yaml").write_text("metrics:\n  x: {period: quarterly, unit: USD, tags: [us-gaap:A]}\n",
                                     encoding="utf-8")
    with pytest.raises(RegistryError, match="duration 或 instant"):
        load_fundamentals(tmp_path / "f.yaml")
    (tmp_path / "f.yaml").write_text("metrics:\n  x: {period: instant, unit: USD, tags: [Assets]}\n",
                                     encoding="utf-8")
    with pytest.raises(RegistryError, match="taxonomy:tag"):
        load_fundamentals(tmp_path / "f.yaml")


def test_fsds_month_end_dates_match_api_actual_dates(tmp_path):
    """FSDS 把期末日取整到月末（如 2020-09-30），API 给实际日期（2020-09-26）：应对应同一财年，显示实际日期。"""
    sync_fsds(tmp_path, SPEC, _client(_fake(), "ua"), quarters=["2020q4"], clock=lambda: T0)
    doc = {"cik": 1, "entityName": "Acme", "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            {"start": "2019-09-29", "end": "2020-09-26", "val": 130, "accn": "A-2020", "fy": 2020, "fp": "FY",
             "form": "10-K", "filed": "2020-10-30"}]}}}}}
    fake = FakeSec({"https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json": json.dumps(doc).encode()})
    sync_companyfacts(tmp_path, SPEC, _client(fake, ""), clock=lambda: T0)
    rev = annual_metric(tmp_path, SPEC, "revenue")
    fy = rev[rev["fiscal_year_end"].dt.year == 2020]
    assert len(fy) == 1  # 不因日期不同而算成两个财年
    assert fy.iloc[0]["fiscal_year_end"] == pd.Timestamp("2020-09-26") and bool(fy.iloc[0]["exact_end"])
    # 可用时间取 FSDS 的接受时间（18:05 美东 → 次日 0 点），比 API 的申报日期规则更精确
    assert fy.iloc[0]["available_at"] == pd.Timestamp("2020-10-31 04:00", tz="UTC")
    agree = source_agreement(tmp_path, SPEC)
    assert len(agree) == 1 and agree["diff"].iloc[0] == 0


def test_alias_switch_is_not_reported_as_a_revision(tmp_path):
    """较早的申报只有靠后的别名（SalesRevenueNet 100），较新的申报换成靠前的别名（102）：差异来自口径，不是重述。"""
    subs = [["B-2019", 1, "Acme", 3571, "0930", "10-K", 20190930, 2019, "FY", 20191101, "2019-11-01 09:00:00.0", 0]]
    nums = [["B-2019", "RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap/2019", 20180930, 4, "USD", "",
             "", "102.0", ""]]
    quarters = {"2018q4": QUARTERS["2018q4"], "2019q4": fsds_zip(subs, nums)}
    sync_fsds(tmp_path, SPEC, _client(_fake(quarters), "ua"), quarters=list(quarters), clock=lambda: T0)
    rev = annual_metric(tmp_path, SPEC, "revenue")
    fy2018 = rev[rev["fiscal_year_end"] == pd.Timestamp("2018-09-30")].iloc[0]
    assert fy2018.value == 102.0 and fy2018.filings == 2 and fy2018.tags_used == 2
    assert fy2018.first_value == 102.0  # 首次公布值只在同一科目内取，不报告为从 100 修订
