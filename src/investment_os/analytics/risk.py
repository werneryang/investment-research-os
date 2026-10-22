"""风险计算。跨频率缩放的假设写在返回结果里，而不是隐含使用。"""

from __future__ import annotations

import math

import pandas as pd


def volatility(returns: pd.Series, periods_per_year: int | None = None) -> dict[str, float | str]:
    """样本标准差；给出 periods_per_year 时按 √时间 年化并注明假设。"""
    s = returns.dropna()
    sd = float(s.std(ddof=1)) if len(s) > 1 else float("nan")
    if periods_per_year is None:
        return {"volatility": sd, "observations": len(s), "assumption": "未年化"}
    return {
        "volatility": sd * math.sqrt(periods_per_year),
        "observations": len(s),
        "assumption": f"按 √{periods_per_year} 年化，假设各期收益独立同分布",
    }


def drawdown(levels: pd.Series) -> pd.Series:
    """相对历史最高点的回撤（≤ 0）。"""
    s = levels.dropna()
    return s / s.cummax() - 1


def max_drawdown(levels: pd.Series) -> dict[str, float | str | None]:
    dd = drawdown(levels)
    if dd.empty:
        return {"max_drawdown": float("nan"), "peak": None, "trough": None}
    trough = dd.idxmin()
    peak = levels.loc[:trough].idxmax()
    return {"max_drawdown": float(dd.min()), "peak": str(peak), "trough": str(trough)}
