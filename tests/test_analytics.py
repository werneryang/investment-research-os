import math

import pandas as pd
import pytest

from investment_os.analytics import rates, returns, risk


@pytest.fixture
def curve():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame({"2Y": [4.33, 4.33, 4.38], "5Y": [3.93, 3.90, 3.99],
                         "10Y": [3.95, 3.91, float("nan")]}, index=idx)


def test_spread_and_curvature_in_bp(curve):
    s = rates.spread_bp(curve, "2Y", "10Y")
    assert s.iloc[0] == pytest.approx(-38)
    assert math.isnan(s.iloc[2])  # 缺失不插值
    c = rates.curvature_bp(curve, "2Y", "5Y", "10Y")
    assert c.iloc[0] == pytest.approx((2 * 3.93 - 4.33 - 3.95) * 100)


def test_level_summary_uses_first_and_last_valid(curve):
    out = rates.level_summary(curve["10Y"], "percent")
    assert out["observations"] == 2
    assert out["end_date"] == "2024-01-03"
    assert out["change_bp"] == pytest.approx(-4)
    assert out["min_date"] == "2024-01-03"


def test_inversion_stats(curve):
    stats = rates.inversion_stats(rates.spread_bp(curve, "2Y", "10Y"))
    assert stats == {"observations": 2, "inverted_days": 2, "inverted_share": 1.0}


def test_curve_frame_pivots_long_table():
    long = pd.DataFrame({
        "series_id": ["UST_PAR_2Y", "UST_PAR_10Y", "OTHER"],
        "observation_at": pd.to_datetime(["2024-01-02"] * 3),
        "value": [4.33, 3.95, 1.0],
    })
    wide = rates.curve_frame(long, {"UST_PAR_2Y": "2Y", "UST_PAR_10Y": "10Y"})
    assert list(wide.columns) == ["10Y", "2Y"]
    assert wide.loc["2024-01-02", "2Y"] == 4.33


def test_total_return_refuses_double_counting():
    prices = pd.Series([100.0, 101.0])
    with pytest.raises(ValueError, match="已包含分配"):
        returns.total_returns(prices, "adjusted_close", distributions=pd.Series([0.0, 1.0]))
    with pytest.raises(ValueError, match="未含分配"):
        returns.total_returns(prices, "close")
    r = returns.total_returns(prices, "close", distributions=pd.Series([0.0, 1.0]))
    assert r.iloc[1] == pytest.approx(0.02)


def test_currency_conversion_is_multiplicative():
    # 当地 +10%，当地货币对基准货币 -5%
    assert returns.to_base_currency(0.10, -0.05) == pytest.approx(1.10 * 0.95 - 1)


def test_cumulative_does_not_skip_missing():
    assert returns.cumulative(pd.Series([0.1, -0.1])) == pytest.approx(1.1 * 0.9 - 1)
    assert math.isnan(returns.cumulative(pd.Series([0.1, float("nan")])))


def test_annualized_geometric():
    assert returns.annualized_geometric(0.21, 2) == pytest.approx(0.10)


def test_volatility_states_scaling_assumption():
    r = pd.Series([0.01, -0.01, 0.02, -0.02])
    raw = risk.volatility(r)
    ann = risk.volatility(r, 12)
    assert ann["volatility"] == pytest.approx(raw["volatility"] * math.sqrt(12))
    assert "√12" in ann["assumption"]


def test_max_drawdown():
    levels = pd.Series([100, 120, 90, 130], index=list("abcd"))
    out = risk.max_drawdown(levels)
    assert out["max_drawdown"] == pytest.approx(-0.25)
    assert (out["peak"], out["trough"]) == ("b", "c")
