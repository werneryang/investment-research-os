"""scripts/market_drawdown_replay.py 的时点规则与计算（不联网）。"""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "scripts/market_drawdown_replay.py"))


def test_cutoff_daily_uses_asof():
    assert M["cutoff_for"]("daily", 0, None, "2020-03-18") == ("2020-03-18", "current")


def test_cutoff_vintaged_after_first_vintage_uses_alfred():
    assert M["cutoff_for"]("vintaged", 5, "2011-05-25", "2020-03-18") == ("2020-03-18", "alfred")


def test_cutoff_before_first_vintage_truncates_and_flags():
    assert M["cutoff_for"]("vintaged", 6, "2022-11-10", "2020-03-18") == ("2020-03-12", "post_hoc_vintage")


def test_parse_and_last_on_or_before_skip_missing():
    rows = M["parse_obs"]({"observations": [
        {"date": "2020-03-16", "value": "1.0"}, {"date": "2020-03-17", "value": "."},
        {"date": "2020-03-19", "value": "2.0"}]})
    assert rows == [("2020-03-16", 1.0), ("2020-03-19", 2.0)]
    assert M["last_on_or_before"](rows, "2020-03-18") == ("2020-03-16", 1.0)
    assert M["last_on_or_before"](rows, "2020-03-01") is None


def test_stale_and_changes():
    assert M["is_stale"]("2022-01-21", "2022-06-16")
    assert not M["is_stale"]("2020-03-13", "2020-03-23")
    assert M["pct_change"](100, 90) == -10.0
    assert M["diff"](1.56, 1.18, 100) == -38.0
    assert M["percentile_rank"]([("a", 1), ("b", 2), ("c", 3), ("d", 4)], "z", 3) == 75.0
    assert M["max_drawdown_to"]([("2020-02-19", 100), ("2020-03-01", 70), ("2020-03-05", 80)],
                                "2020-02-19", "2020-03-05") == -30.0


def test_ice_series_excluded():
    assert not (set(M["SERIES"]) & M["EXCLUDED"])


def test_committed_metrics_match_records_and_omit_local_levels():
    out = json.loads((ROOT / "methodology/records/market-drawdown-replay-metrics.json").read_text())
    assert [e["id"] for e in out["events"]] == ["E1", "E2", "E3", "E4", "E5"]
    for e in out["events"]:
        for p in e["points"]:
            for s in M["LEVELS_LOCAL_ONLY"]:
                v = p["values"].get(s, {})
                assert "value" not in v and "at_peak" not in v
    e3 = {p["as_of"]: p for p in out["events"][2]["points"]}
    assert e3["2020-03-18"]["values"]["DGS10"]["chg_1w_bp"] == 36.0
    assert e3["2020-03-23"]["values"]["NFCI"]["obs_date"] == "2020-03-13"  # 当日版本只到 3-13 那周


def test_down_day_stats_ratio_and_share():
    base = {"d1": -0.02, "d2": 0.01, "d3": -0.01}
    other = {"d1": -0.01, "d2": 0.02, "d3": 0.0}
    out = M["down_day_stats"](base, {"X": other}, "d3", n=20)
    assert out["down_days"] == 2
    assert out["X"]["ratio_to_base"] == 0.33  # (-0.005) / (-0.015)
    assert out["X"]["share_also_down"] == 0.5


def test_finra_month_respects_publication_lag():
    months = ["2020-01", "2020-02", "2020-03"]
    assert M["latest_published_month"](months, "2020-03-23") == "2020-01"
    assert M["latest_published_month"](months, "2020-04-01") == "2020-02"
    assert M["shift_month"]("2020-01", -3) == "2019-10"


def test_manual_block_has_no_levels():
    out = json.loads((ROOT / "methodology/records/market-drawdown-replay-metrics.json").read_text())
    for e in out["events"]:
        for p in e["points"]:
            for k, v in p.get("manual", {}).items():
                if isinstance(v, dict):
                    assert "value" not in v and "at_peak" not in v, k


def test_splits_adjust_pre_split_nav():
    rows = [("2025-12-04", 291.0), ("2025-12-05", 146.6)]
    adj = M["apply_splits"](rows, [("2025-12-05", 2.0)])
    assert adj == [("2025-12-04", 145.5), ("2025-12-05", 146.6)]


def test_window_return_counts_trading_days():
    rows = [("d1", 100.0), ("d2", 110.0), ("d3", 99.0)]
    assert M["window_return"](rows, "d2", 0, 0) == 10.0
    assert M["window_return"](rows, "d2", 0, 1) == -1.0
    assert M["window_return"](rows, "d1", 0, 0) is None


def test_ice_values_never_in_public_output():
    text = (ROOT / "methodology/records/market-drawdown-replay-metrics.json").read_text()
    for s in M["ICE_SERIES"]:
        assert s not in text
