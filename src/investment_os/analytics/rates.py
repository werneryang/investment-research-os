"""收益率曲线的公共计算。输入为百分比收益率，利差与变化以基点（bp）表示。"""

from __future__ import annotations

import pandas as pd

BP_PER_PERCENT = 100.0


def curve_frame(long: pd.DataFrame, tenor_of: dict[str, str]) -> pd.DataFrame:
    """长表 → 宽表：行为观测日，列为期限代码。

    只使用调用方已筛选为合格的行；缺失保持 NaN，不插值。
    """
    df = long[long["series_id"].isin(tenor_of)].copy()
    df["tenor"] = df["series_id"].map(tenor_of)
    wide = df.pivot(index="observation_at", columns="tenor", values="value").sort_index()
    wide.columns.name = None
    return wide


def spread_bp(curve: pd.DataFrame, short: str, long: str) -> pd.Series:
    """长端减短端，单位 bp；为负即倒挂。"""
    return (curve[long] - curve[short]) * BP_PER_PERCENT


def curvature_bp(curve: pd.DataFrame, short: str, mid: str, long: str) -> pd.Series:
    """蝶式曲率 2×中端 − 短端 − 长端，单位 bp；为正即中段相对隆起。"""
    return (2 * curve[mid] - curve[short] - curve[long]) * BP_PER_PERCENT


def level_summary(series: pd.Series, unit: str) -> dict[str, float | str | None]:
    """期初、期末、变化、最小、最大、均值与对应日期。

    ``unit`` 为 "percent" 时变化换算为 bp；为 "bp" 时直接相减。
    """
    s = series.dropna()
    if s.empty:
        return {"unit": unit, "observations": 0}
    scale = BP_PER_PERCENT if unit == "percent" else 1.0
    return {
        "unit": unit,
        "observations": int(len(s)),
        "start_date": s.index[0].date().isoformat(),
        "start": float(s.iloc[0]),
        "end_date": s.index[-1].date().isoformat(),
        "end": float(s.iloc[-1]),
        "change_bp": float(s.iloc[-1] - s.iloc[0]) * scale,
        "min": float(s.min()),
        "min_date": s.idxmin().date().isoformat(),
        "max": float(s.max()),
        "max_date": s.idxmax().date().isoformat(),
        "mean": float(s.mean()),
    }


def inversion_stats(spread: pd.Series) -> dict[str, float | int]:
    """倒挂（利差 < 0）天数与占比，只计有效观测。"""
    s = spread.dropna()
    inverted = int((s < 0).sum())
    return {"observations": int(len(s)), "inverted_days": inverted,
            "inverted_share": inverted / len(s) if len(s) else float("nan")}
