"""美国主要资产的长期回报与风险（docs/study-long-run-assets.md）：统计量、实际回报、相关时期、核对与发现。"""

import numpy as np
import pandas as pd
import pytest
import yaml

from investment_os.contracts import DatasetVersion
from investment_os.registry import parse_study
from investment_os.research.asset_history import run
from investment_os.research.base import StudyInput
from investment_os.research.findings import asset_history_findings, asset_history_state, interpret

from .conftest import PROJECT_ROOT

YEARS = list(range(1930, 1970))  # 40 年
STUDY = {
    "study_id": "asset_test", "title": "t", "question": "q", "result_type": "descriptive", "branch": "asset_history",
    "scope": {"market": "US", "currency": "USD", "start": "1930-01-01", "end": "1969-12-31", "frequency": "annual",
              "vintage_policy": "latest"},
    "data": {"annual": "damodaran_histret"},
    "method": {"assets": ["SP500", "TBOND10Y", "TBILL3M"], "real_start_year": 1940,
               "periods": [[1930, 1949], [1950, 1969]], "period_shift_years": 5, "rolling_years": 20},
}


def _version(dataset_id):
    return DatasetVersion(dataset_id=dataset_id, version_id=f"v-{dataset_id}", schema_version="series.v1",
                          content_hash="0" * 64, created_at="2026-10-25T00:00:00+00:00", rows=0, path="",
                          raw_snapshots=[], transform="normalize.v1", quality={}, series={})


def _input(role, dataset_id, rows):
    frame = pd.DataFrame([{"series_id": s, "observation_at": pd.Timestamp(d), "value": v, "quality_status": "ok",
                           "source_id": "test"} for s, d, v in rows])
    return StudyInput(role=role, dataset_id=dataset_id, frame=frame, version=_version(dataset_id),
                      source_status="access_verified")


rng = np.random.default_rng(7)
SP = {y: float(v) for y, v in zip(YEARS, rng.normal(0.10, 0.18, len(YEARS)))}
SP[1931] = -0.45  # 一次深度下跌
# 前 20 年股债同向、后 20 年反向，用来检验分时期相关系数
BOND = {y: 0.04 + (0.3 if y < 1950 else -0.3) * (SP[y] - 0.10) + float(rng.normal(0, 0.01)) for y in YEARS}
BILL = {y: 0.02 + 0.0005 * (y - 1930) for y in YEARS}


def _annual(extra_years=()):
    rows = []
    for y in YEARS:
        rows += [("DAM_SP500", f"{y}-01-01", SP[y]), ("DAM_TBOND10Y", f"{y}-01-01", BOND[y]),
                 ("DAM_TBILL3M", f"{y}-01-01", BILL[y])]
    return _input("annual", "damodaran_histret", rows)


def _cpi():
    # 每年 12 月的 CPI 按 3% 增长：年通胀恰为 3%
    rows = [("CPIAUCSL", f"{y}-12-01", 100 * 1.03 ** (y - 1925)) for y in range(1925, 1970)]
    return _input("cpi", "fred_cpiaucsl", rows)


def test_statistics_match_hand_calculation():
    res = run(parse_study(STUDY), {"annual": _annual()}, None).to_dict()
    r = res["results"]
    sp = pd.Series(SP)
    n = r["nominal"]["SP500"]
    assert (r["first_year"], r["last_year"], n["years"]) == (1930, 1969, 40)
    assert n["arithmetic"] == pytest.approx(sp.mean())
    assert n["geometric"] == pytest.approx((1 + sp).prod() ** (1 / 40) - 1)
    assert n["volatility"] == pytest.approx(sp.std(ddof=1))
    assert (n["worst"], n["worst_year"]) == (pytest.approx(-0.45), 1931)
    wealth = (1 + sp).cumprod()
    assert n["max_drawdown"] == pytest.approx((wealth / wealth.cummax() - 1).min())
    assert r["equity_risk_premium"]["TBILL3M"] == pytest.approx(n["geometric"] - r["nominal"]["TBILL3M"]["geometric"])
    assert r["rolling"]["windows"] == 21 and r["rolling"]["window_years"] == 20
    assert not r["real"] and res["validation"] == {}  # 没有 CPI 与核对输入时不计算，也不冒充


def test_real_returns_use_december_inflation_from_the_start_year():
    res = run(parse_study(STUDY), {"annual": _annual(), "cpi": _cpi()}, None).to_dict()
    real = res["results"]["real"]["SP500"]
    assert (real["first_year"], real["last_year"], real["years"]) == (1940, 1969, 30)
    expected = (1 + pd.Series(SP).loc[1940:]) / 1.03 - 1
    assert real["geometric"] == pytest.approx((1 + expected).prod() ** (1 / 30) - 1)
    assert res["results"]["inflation"]["mean"] == pytest.approx(0.03)


def test_period_correlations_and_boundary_sensitivity():
    r = run(parse_study(STUDY), {"annual": _annual()}, None).to_dict()["results"]
    first, second = r["correlations"]["periods"]
    assert (first["first_year"], first["last_year"], second["first_year"]) == (1930, 1949, 1950)
    assert first["matrix"]["SP500"]["TBOND10Y"] > 0.8 and second["matrix"]["SP500"]["TBOND10Y"] < -0.8
    sens = r["period_sensitivity"]["stock_bond_correlation"]
    assert [x["period"] for x in sens] == [[1930, 1949], [1950, 1969]]
    assert all(x["min"] <= x["max"] for x in sens)
    texts = {f["id"]: f["text"] for f in asset_history_findings({"results": r})}
    assert "1930–1949 年 +" in texts["stock_bond_correlation"] and "1950–1969 年 −" in texts["stock_bond_correlation"]


def test_last_n_years_takes_the_most_recent_complete_years():
    study = {**STUDY, "method": {**STUDY["method"], "last_n_years": 10, "periods": []}}
    r = run(parse_study(study), {"annual": _annual()}, None).to_dict()["results"]
    assert (r["first_year"], r["last_year"]) == (1960, 1969) and r["correlations"]["periods"] == []
    assert r["rolling"] == {}  # 10 年不足 20 年窗口，不给滚动回报


def test_cross_checks_and_monthly_drawdown():
    months = pd.date_range("1930-01-01", "1969-12-01", freq="MS")
    # 月度市场收益：按年复利后等于年度回报（每月相同）；在年度回撤谷底那一年的 5 月深跌一半、6 月回升，
    # 年度回报不变，但月度回撤更深
    wealth = (1 + pd.Series(SP)).cumprod()
    trough = int((wealth / wealth.cummax() - 1).idxmin())
    rows = []
    for m in months:
        monthly = (1 + SP[m.year]) ** (1 / 12) - 1
        if m.year == trough and m.month in (5, 6):
            monthly = (1 + monthly) * 0.5 - 1 if m.month == 5 else (1 + monthly) / 0.5 - 1
        rows += [("FF3_Mkt-RF", m.strftime("%Y-%m-%d"), monthly * 100 - 0.1), ("FF3_RF", m.strftime("%Y-%m-%d"), 0.1)]
    ff = _input("monthly_market", "french_ff3", rows)
    tb_ok = _input("tbill_check", "fred_dtb3", [("DTB3", f"{y}-06-01", BILL[y] * 100 + 0.2) for y in YEARS])
    inputs = {"annual": _annual(), "monthly_market": ff, "tbill_check": tb_ok}
    v = run(parse_study(STUDY), inputs, None).to_dict()["validation"]
    assert v["cross_check_equity"]["status"] == "pass" and v["cross_check_equity"]["correlation"] > 0.999
    assert v["monthly_drawdown"]["status"] == "pass" and v["monthly_drawdown"]["monthly"] < v["monthly_drawdown"]["annual"]
    assert v["cross_check_tbill"]["status"] == "pass" and v["cross_check_tbill"]["max_abs_diff_pp"] == pytest.approx(0.2)

    tb_bad = _input("tbill_check", "fred_dtb3", [("DTB3", f"{y}-06-01", BILL[y] * 100 + 1.0) for y in YEARS])
    v = run(parse_study(STUDY), {**inputs, "tbill_check": tb_bad}, None).to_dict()["validation"]
    assert v["cross_check_tbill"]["status"] == "fail"


def test_findings_state_and_errors():
    res = run(parse_study(STUDY), {"annual": _annual(), "cpi": _cpi()}, None).to_dict()
    texts = {f["id"]: f["text"] for f in asset_history_findings(res)}
    assert texts["equity_long_run"].startswith("1930–1969 年，标普 500 年化回报")
    assert "扣除通胀（1940–1969 年）" in texts["equity_long_run"]
    assert "相对 3 个月国库券" in texts["equity_premium"]
    assert set(asset_history_state(res)) == {"实际回报最高的资产", "股债相关（最近时期）"}
    assert interpret(res)["rule_version"] == "asset_history-findings.v1"
    short = {**STUDY, "scope": {**STUDY["scope"], "start": "1969-01-01"}}
    with pytest.raises(ValueError, match="完整年度不足"):
        run(parse_study(short), {"annual": _annual()}, None)
    with pytest.raises(ValueError, match="描述与比较"):
        run(parse_study({**STUDY, "result_type": "explanatory"}), {"annual": _annual()}, None)


def test_registered_studies_fix_periods_in_advance():
    full = yaml.safe_load((PROJECT_ROOT / "config/studies/us_asset_history.yaml").read_text(encoding="utf-8"))
    recent = yaml.safe_load((PROJECT_ROOT / "config/studies/us_asset_history_last_25y.yaml").read_text(encoding="utf-8"))
    assert full["method"]["periods"] == [[1928, 1969], [1970, 1999], [2000, 2025]]
    assert full["method"]["real_start_year"] == 1948 and set(full["method"]["assets"]) >= {"REALESTATE", "GOLD"}
    assert recent["method"]["last_n_years"] == 25 and recent["method"]["periods"] == []
