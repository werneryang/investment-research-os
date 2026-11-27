"""scripts/event_window_returns.py 的第 0 天规则与市场模型计算（不读真实数据）。"""

import runpy
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "scripts/event_window_returns.py"))

DAYS = [date(2026, 11, d) for d in (19, 20, 23, 24, 25)]  # 11-21、22 是周末


def test_day0_before_open_is_same_day():
    assert M["day0_for"]("2026-11-23T08:57:54-05:00", DAYS) == date(2026, 11, 23)


def test_day0_during_session_is_same_day_and_after_close_is_next_day():
    assert M["day0_for"]("2026-11-20T11:00:00-05:00", DAYS) == date(2026, 11, 20)
    assert M["day0_for"]("2026-11-20T16:20:51-05:00", DAYS) == date(2026, 11, 23)


def test_day0_on_non_trading_day_is_next_trading_day():
    assert M["day0_for"]("2026-11-22T10:00:00-05:00", DAYS) == date(2026, 11, 23)


def test_market_model_recovers_parameters_and_injected_shock():
    rng = np.random.default_rng(0)
    rm = rng.normal(0, 0.01, 300)
    r = 0.001 + 1.5 * rm + rng.normal(0, 0.002, 300)
    mm = M["market_model"](r[:250], rm[:250])
    assert mm["beta"] == pytest.approx(1.5, abs=0.05) and mm["alpha"] == pytest.approx(0.001, abs=0.0005)
    shocked = r[250:253].copy()
    shocked[1] += 0.05  # 第 0 天注入 5% 的异常收益
    out = M["car_stats"](shocked, rm[250:253], mm)
    assert out["car"] == pytest.approx(0.05, abs=0.01) and out["theta"] > 5


def test_car_variance_includes_parameter_error():
    """Var(CAR) = σ²·(L2 + 1'X*(X'X)^-1X*'1)，应大于只计残差的 L2·σ²。"""
    rng = np.random.default_rng(1)
    rm = rng.normal(0, 0.01, 60)
    r = 0.5 * rm + rng.normal(0, 0.01, 60)
    mm = M["market_model"](r[:50], rm[:50])
    w = rm[50:55]
    X = np.column_stack([np.ones(5), w])
    expected = mm["sigma2"] * (5 + np.ones(5) @ X @ mm["xtx_inv"] @ X.T @ np.ones(5))
    out = M["car_stats"](r[50:55], w, mm)
    assert out["sd"] ** 2 == pytest.approx(expected) and out["sd"] ** 2 > 5 * mm["sigma2"]


def test_window_slice_returns_none_outside_data():
    idx = [date(2026, 1, 1) + timedelta(days=i) for i in range(10)]
    assert M["window_slice"](idx, idx[5], -2, 1) == idx[3:7]
    assert M["window_slice"](idx, idx[8], 0, 2) is None
    assert M["window_slice"](idx, idx[1], -2, 0) is None


def test_compute_on_synthetic_prices_uses_shared_estimation_window():
    rng = np.random.default_rng(2)
    days = pd.bdate_range("2026-04-01", "2026-11-25").date
    rm = rng.normal(0, 0.01, len(days))
    r = 1.2 * rm + rng.normal(0, 0.003, len(days))
    i0 = list(days).index(date(2026, 11, 12))
    r[i0] += -0.04
    prices = {"NVDA": pd.Series(100 * np.cumprod(1 + r), index=days),
              "SPY": pd.Series(100 * np.cumprod(1 + rm), index=days)}
    out = M["compute"](prices)
    assert out["day0"] == {"departure": "2026-11-12", "return": "2026-11-23"}
    assert out["estimation_window"]["days"] == 120
    spy = out["benchmarks"]["SPY"]
    assert spy["model"]["beta"] == pytest.approx(1.2, abs=0.1)
    assert spy["events"]["departure"]["car"]["[0,0]"]["car"] == pytest.approx(-0.04, abs=0.01)
    assert spy["events"]["return"]["car"]["[0,2]"] is not None
    assert spy["events"]["return"]["car"]["[-20,-1]"] is not None
    assert "QQQ" not in out["benchmarks"]  # 没给的基准不出现
