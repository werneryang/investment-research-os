import json
import urllib.error
from pathlib import Path

import pandas as pd
import pytest

from investment_os.connectors.base import FetchError, fetch_with_retry
from investment_os.connectors.fred import FredApiVintagesConnector
from investment_os.connectors.manual import ManualCsvConnector
from investment_os.contracts import VintageSupport
from investment_os.data import as_of, ingest, normalize
from investment_os.data.store import eligibility_as_of
from investment_os.registry import Registry

from .conftest import (
    NO_RETRY,
    PROJECT_ROOT,
    TREASURY_2024,
    TREASURY_2025,
    FakeHttp,
    dgs10_connector,
    treasury_connector,
)


def test_fetch_with_retry_is_bounded():
    http = FakeHttp({})
    sleeps = []
    with pytest.raises(FetchError, match="3 次尝试"):
        fetch_with_retry("https://x", http, attempts=3, sleep=sleeps.append)
    assert len(http.calls) == 3
    assert sleeps == [2.0, 4.0]


def test_treasury_parse_handles_changing_columns(registry):
    conn = treasury_connector({2024: TREASURY_2024, 2025: TREASURY_2025})
    spec = registry.dataset("ust_par_yield_curve")
    payloads = conn.fetch(spec, {"start": 2024, "end": 2025})
    p24, p25 = (conn.parse(spec, p) for p in payloads)
    assert "UST_PAR_1.5M" not in p24.series
    assert p25.series["UST_PAR_1.5M"] == {"tenor": "1.5M", "tenor_months": 1.5,
                                           "source_label": "1.5 Month"}
    assert len(p24.staging) == 4 * 13
    row = p24.staging[(p24.staging.series_id == "UST_PAR_10Y")
                      & (p24.staging.observation_at == pd.Timestamp("2024-01-05").date())]
    assert row["raw_value"].item() == "4.05"


def test_treasury_rejects_html_error_page(registry):
    conn = treasury_connector({2024: "<html>maintenance</html>"})
    with pytest.raises(FetchError, match="不是预期的 CSV"):
        conn.fetch(registry.dataset("ust_par_yield_curve"), {"start": 2024, "end": 2024})


def test_ingest_creates_then_dedupes_unchanged(registry, store):
    r1 = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
                treasury_connector({2024: TREASURY_2024}))
    assert r1.status == "created"
    assert r1.version.rows == 52
    assert r1.version.quality["status_counts"] == {"ok": 52}
    r2 = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
                treasury_connector({2024: TREASURY_2024}))
    assert r2.status == "unchanged"
    assert r2.version.version_id == r1.version.version_id
    assert len(store.versions("ust_par_yield_curve")) == 1
    log = store.fetch_log("ust_par_yield_curve")
    assert [e["status"] for e in log] == ["started", "created", "started", "unchanged"]
    # 每次尝试都有开始与终态，按 attempt_id 成对
    assert log[0]["attempt_id"] == log[1]["attempt_id"] != log[2]["attempt_id"]
    # 内容相同的原始文件只存一份；第二次取得的记录指向已有文件，并保留自己的取得时间
    first, again = log[1]["raw_snapshots"][0], log[3]["raw_snapshots"][0]
    assert again["path"] == first["path"] and again["reused"] is True and "reused" not in first
    assert again["sha256"] == first["sha256"] and again["retrieved_at"] >= first["retrieved_at"]
    raw = store.base / "raw" / "ust_par_yield_curve"
    assert len(list(raw.glob("*.csv"))) == 1 and len(list(raw.glob("*.meta.json"))) == 1
    assert store.read_raw(again) == TREASURY_2024.encode()


def test_changed_raw_content_is_stored_separately(registry, store):
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: TREASURY_2024}))
    revised = TREASURY_2024.replace("01/05/2024,5.54", "01/05/2024,5.53")
    r = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
               treasury_connector({2024: revised}))
    assert r.status == "created"
    raw = store.base / "raw" / "ust_par_yield_curve"
    assert len(list(raw.glob("*.csv"))) == 2
    assert not r.version.raw_snapshots[-1].get("reused")


def test_ingest_failure_keeps_previous_version(registry, store):
    ok = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
                treasury_connector({2024: TREASURY_2024}))
    bad = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
                 treasury_connector({2024: urllib.error.URLError("timeout")}))
    assert bad.status == "failed"
    assert bad.version.version_id == ok.version.version_id
    log = store.fetch_log("ust_par_yield_curve")[-1]
    assert log["status"] == "failed" and log["kept_version"] == ok.version.version_id
    assert len(store.versions("ust_par_yield_curve")) == 1


def test_ingest_merges_years_and_records_revisions(registry, store):
    v1 = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
                treasury_connector({2024: TREASURY_2024})).version
    v2 = ingest(registry, store, "ust_par_yield_curve", {"start": 2025, "end": 2025},
                treasury_connector({2025: TREASURY_2025})).version
    assert v2.parent_version == v1.version_id
    assert v2.rows == 52 + 2 * 14  # 2024 年数据保留
    assert len(v2.raw_snapshots) == 2

    revised = TREASURY_2024.replace("01/05/2024,5.54", "01/05/2024,5.60")
    v3 = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
                treasury_connector({2024: revised})).version
    df3, _ = store.load("ust_par_yield_curve", v3.version_id)
    df1, _ = store.load("ust_par_yield_curve", v1.version_id)
    pick = lambda df: df[(df.series_id == "UST_PAR_1M")  # noqa: E731
                         & (df.observation_at == pd.Timestamp("2024-01-05"))]["value"].item()
    assert pick(df3) == 5.60
    assert pick(df1) == 5.54  # 旧版本不被改写


def test_load_detects_tampered_version(registry, store):
    v = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
               treasury_connector({2024: TREASURY_2024})).version
    path = store.base / v.path
    df = pd.read_parquet(path)
    df.loc[0, "value"] = 99.0
    df.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="校验值不一致"):
        store.load("ust_par_yield_curve")


def test_fred_graph_marks_holidays_missing(registry, store):
    body = "observation_date,DGS10\n2024-01-12,3.94\n2024-01-15,\n2024-01-16,4.07\n"
    v = ingest(registry, store, "fred_dgs10", {"start": "2024-01-12", "end": "2024-01-16"},
               dgs10_connector("2024-01-12", "2024-01-16", body)).version
    assert v.quality["status_counts"] == {"ok": 2, "missing": 1}


def test_fred_graph_rejects_wrong_series(registry, store):
    body = "observation_date,DGS2\n2024-01-12,4.14\n"
    r = ingest(registry, store, "fred_dgs10", {"start": "2024-01-12", "end": "2024-01-12"},
               dgs10_connector("2024-01-12", "2024-01-12", body))
    assert r.status == "failed" and "DGS2" in r.message
    # 原始快照仍保存供诊断
    assert store.fetch_log("fred_dgs10")[-1]["raw_snapshots"]


ALFRED = {"count": 3, "offset": 0, "limit": 100000, "observations": [
    {"realtime_start": "2024-02-13", "realtime_end": "2025-02-11", "date": "2024-01-01", "value": "308.417"},
    {"realtime_start": "2025-02-12", "realtime_end": "9999-12-31", "date": "2024-01-01", "value": "309.685"},
    {"realtime_start": "2024-03-12", "realtime_end": "9999-12-31", "date": "2024-02-01", "value": "310.326"},
]}


def test_fred_api_requires_key(registry, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(FetchError, match="FRED_API_KEY"):
        FredApiVintagesConnector().fetch(registry.dataset("alfred_cpiaucsl"), {})


def test_alfred_vintages_support_point_in_time(registry, store):
    class AnyUrl(FakeHttp):
        def __call__(self, url, timeout):
            self.calls.append(url)
            return json.dumps(ALFRED).encode()

    http = AnyUrl({})
    conn = FredApiVintagesConnector(http_get=http, api_key="secret-key", **NO_RETRY)
    v = ingest(registry, store, "alfred_cpiaucsl", {}, conn).version
    assert v.rows == 3
    # key 只用于请求，不进入快照或记录
    assert "secret-key" in http.calls[0]
    assert "secret-key" not in json.dumps(v.raw_snapshots)
    assert "secret-key" not in (store.base / "catalog" / "fetch_log.jsonl").read_text()

    df, _ = store.load("alfred_cpiaucsl")
    jan = lambda view: view[view.observation_at == pd.Timestamp("2024-01-01")]  # noqa: E731
    # 2024-03-01 时只能看到 1 月首发值，2 月数据尚未发布
    view = as_of(df, pd.Timestamp("2024-03-01", tz="UTC"), VintageSupport.SUPPLIER)
    assert jan(view)["value"].item() == 308.417
    assert pd.Timestamp("2024-02-01") not in set(view.observation_at)
    # 2025 年修订后看到修订值
    assert jan(as_of(df, pd.Timestamp("2025-06-01", tz="UTC"), VintageSupport.SUPPLIER))["value"].item() == 309.685
    # 不声明供应方历史版本时，同样的行没有「当时已知」的证据
    assert as_of(df, pd.Timestamp("2025-06-01", tz="UTC")).empty


def test_manual_import_requires_declared_source(registry, store, tmp_path: Path):
    f = tmp_path / "x.csv"
    f.write_text("observation_at,value\n2024-01-01,1.5\n2024-02-01,\n", encoding="utf-8")
    r = ingest(registry, store, "manual_example", {"path": str(f), "declared_source": ""},
               ManualCsvConnector())
    assert r.status == "failed" and "声明原始来源" in r.message

    r = ingest(registry, store, "manual_example",
               {"path": str(f), "declared_source": "某机构年报 PDF 第 3 页，2026-10-22 手工录入"},
               ManualCsvConnector())
    assert r.status == "created"
    df, v = store.load("manual_example")
    assert v.series["manual_example"]["declared_source"].startswith("某机构年报")
    # 可用时间未知：留空，并被时点视图排除
    assert df["available_at"].isna().all()
    assert as_of(df, pd.Timestamp("2030-01-01", tz="UTC")).empty


class PagedAlfred(FakeHttp):
    """按 offset/limit 切片返回 ALFRED 观测；``count`` 可声明为大于实际条数以模拟截断。"""

    def __init__(self, observations, count=None):
        super().__init__({})
        self.observations = observations
        self.count = len(observations) if count is None else count

    def __call__(self, url, timeout):
        import urllib.parse
        self.calls.append(url)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        off, lim = int(q["offset"]), int(q["limit"])
        return json.dumps({"count": self.count, "offset": off, "limit": lim,
                           "observations": self.observations[off:off + lim]}).encode()


def test_alfred_fetches_all_pages(registry, store):
    http = PagedAlfred(ALFRED["observations"])
    conn = FredApiVintagesConnector(http_get=http, api_key="k", page_limit=2, **NO_RETRY)
    r = ingest(registry, store, "alfred_cpiaucsl", {}, conn)
    assert r.status == "created" and r.version.rows == 3
    assert len(http.calls) == 2
    assert len(r.version.raw_snapshots) == 2


def test_alfred_truncated_result_fails(registry, store):
    http = PagedAlfred(ALFRED["observations"], count=100_001)
    conn = FredApiVintagesConnector(http_get=http, api_key="k", page_limit=2, **NO_RETRY)
    r = ingest(registry, store, "alfred_cpiaucsl", {}, conn)
    assert r.status == "failed" and "不完整" in r.message
    assert store.versions("alfred_cpiaucsl") == []


def test_fred_api_failure_does_not_leak_key(registry, store):
    key = "FAKEKEY1234567890"
    http = FakeHttp({})  # 所有请求都失败，异常文本含完整 URL
    def failing(url, timeout):
        http.calls.append(url)
        raise urllib.error.URLError(f"timed out while fetching {url}")
    conn = FredApiVintagesConnector(http_get=failing, api_key=key, **NO_RETRY)
    r = ingest(registry, store, "alfred_cpiaucsl", {}, conn)
    assert r.status == "failed"
    assert key in http.calls[0]  # key 确实用于请求
    assert key not in r.message
    assert key not in (store.base / "catalog" / "fetch_log.jsonl").read_text()


def test_normalize_stage_failure_is_logged(registry, store, monkeypatch):
    import sys
    ingest_mod = sys.modules["investment_os.data.ingest"]  # 包内同名函数会遮蔽子模块属性

    def boom(*a, **k):
        raise ValueError("synthetic normalize failure")
    monkeypatch.setattr(ingest_mod, "normalize", boom)
    r = ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
               treasury_connector({2024: TREASURY_2024}))
    assert r.status == "failed"
    last = store.fetch_log("ust_par_yield_curve")[-1]
    assert last["status"] == "failed" and last["stage"] == "normalize"
    assert last["raw_snapshots"]  # 原始快照已保存且被引用


def test_current_revision_cannot_enter_past_point_in_time_view(registry):
    """回归 F1：2026 年下载的当前修订 CPI，不能凭 45 天规则进入 2024 年的时点视图。"""
    spec = registry.dataset("fred_cpiaucsl")
    staging = pd.DataFrame({"series_id": ["CPIAUCSL"], "observation_at": [pd.Timestamp("2024-01-01").date()],
                            "raw_value": ["309.685"], "published_at": [None], "vintage_label": [None]})
    df = normalize(spec, staging, pd.Timestamp("2026-10-22", tz="UTC"), "local:20261022T000000Z")
    assert df["available_at"].iloc[0] == pd.Timestamp("2024-03-17 04:00", tz="UTC")
    at = pd.Timestamp("2024-04-01", tz="UTC")
    assert as_of(df, at, VintageSupport.NONE).empty
    assert eligibility_as_of(df, at, VintageSupport.NONE)["reason"].iloc[0] == "no_evidence_known_then"
    # 本系统在当时确已取得的快照则可以使用
    df_then = normalize(spec, staging, pd.Timestamp("2024-03-20", tz="UTC"), "local:20240320T000000Z")
    assert len(as_of(df_then, at, VintageSupport.NONE)) == 1


def test_scheduled_request_resolves_relative_dates(registry):
    from datetime import date

    from investment_os.registry import scheduled_request
    ust = registry.dataset("ust_par_yield_curve")
    # 一月初取最近 30 天，覆盖上一年末
    assert scheduled_request(ust, date(2027, 1, 10)) == {"start": "2026-12-11"}
    assert scheduled_request(registry.dataset("fred_dff"), date(2027, 1, 10)) == {}
    assert registry.dataset("alfred_cpiaucsl").scheduled_fetch is None  # 没有 key 时不参加定时取得


def test_scheduled_fetch_rejects_unknown_keys(tmp_path: Path):
    from investment_os.registry import RegistryError, load_datasets
    (tmp_path / "d.yaml").write_text("""
datasets:
  a: {source_id: s, upstream_id: u, connector: c, frequency: daily, unit: percent,
      timezone: UTC, availability: {type: unknown}, scheduled_fetch: {series: X}}
""", encoding="utf-8")
    src = Registry.load(PROJECT_ROOT).sources["fred_graph"]
    with pytest.raises(RegistryError, match="scheduled_fetch"):
        load_datasets(tmp_path / "d.yaml", {"s": src})


def test_fetch_all_runs_every_scheduled_dataset_and_reports_failure(project, monkeypatch, capsys):
    import investment_os.cli as cli
    from investment_os.data.ingest import IngestResult

    calls = []

    def fake_ingest(reg, store, dataset_id, request):
        calls.append((dataset_id, request))
        return IngestResult(dataset_id, "failed" if dataset_id == "fred_dff" else "unchanged", "x", None)

    monkeypatch.setattr(cli, "ingest", fake_ingest)
    assert cli.main(["--root", str(project), "fetch", "--all"]) == 1  # 一个失败不影响其他，但返回非零
    scheduled = {d.id for d in Registry.load(project).datasets.values() if d.scheduled_fetch is not None}
    assert {c[0] for c in calls} == scheduled and "fred_payems" in scheduled
    assert "manual_example" not in scheduled and "alfred_cpiaucsl" not in scheduled
    assert dict(calls)["ust_par_yield_curve"]["start"][:2] == "20"  # 相对日期已换算
    assert "[failed] fred_dff" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--root", str(project), "fetch", "--all", "--start", "2024"])


def test_env_file_sets_only_missing_variables(tmp_path: Path, monkeypatch):
    from investment_os.cli import load_env_file
    (tmp_path / ".env").write_text("# 注释\nexport FRED_API_KEY='abc'\nIROS_TEST_X=from-file\nNOT_A_PAIR\n",
                                   encoding="utf-8")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("IROS_TEST_X", "from-env")
    load_env_file(tmp_path / ".env")
    import os
    assert os.environ["FRED_API_KEY"] == "abc"  # 去掉 export 与引号
    assert os.environ["IROS_TEST_X"] == "from-env"  # 已有的环境变量优先
    load_env_file(tmp_path / "missing.env")  # 文件不存在时不报错
