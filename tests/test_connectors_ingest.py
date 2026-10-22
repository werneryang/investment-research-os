import json
import urllib.error
from pathlib import Path

import pandas as pd
import pytest

from investment_os.connectors.base import FetchError, fetch_with_retry
from investment_os.connectors.fred import FredApiVintagesConnector
from investment_os.connectors.manual import ManualCsvConnector
from investment_os.data import as_of, ingest

from .conftest import (
    NO_RETRY,
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
    assert [e["status"] for e in store.fetch_log("ust_par_yield_curve")] == ["created", "unchanged"]


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


ALFRED = {"observations": [
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
    view = as_of(df, pd.Timestamp("2024-03-01", tz="UTC"))
    assert jan(view)["value"].item() == 308.417
    assert pd.Timestamp("2024-02-01") not in set(view.observation_at)
    # 2025 年修订后看到修订值
    assert jan(as_of(df, pd.Timestamp("2025-06-01", tz="UTC")))["value"].item() == 309.685


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
