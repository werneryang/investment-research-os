"""收益计算，按 architecture §7.1 统一口径。

所有函数以小数表示收益（0.05 即 5%）。调用方需声明价格类型，
避免把已含分红的复权价格再加一次分红。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_TYPES = ("close", "adjusted_close", "nav", "total_return_index")


def simple_returns(prices: pd.Series) -> pd.Series:
    """相邻观测的简单收益；缺失价格产生缺失收益，不前值填补。"""
    return prices / prices.shift(1) - 1


def total_returns(prices: pd.Series, price_type: str,
                  distributions: pd.Series | None = None,
                  events_complete: bool = False) -> pd.Series:
    """持有期总收益。

    - ``close`` / ``nav``：未含分配，需给出 ``distributions``（除息日对齐的每单位现金分配）
    - ``adjusted_close`` / ``total_return_index``：已含分配，再给出分配视为重复计算并报错

    ``distributions`` 中显式的 NaN 表示未知，对应期间的收益为 NaN，绝不当作零。
    分配序列未列出的日期默认也是未知；只有调用方声明 ``events_complete=True``
    （事件表已核验完整、未列出即无分配）时才按零处理。
    """
    if price_type not in PRICE_TYPES:
        raise ValueError(f"未知价格类型：{price_type}")
    if price_type in ("adjusted_close", "total_return_index"):
        if distributions is not None:
            raise ValueError(f"{price_type} 已包含分配，不能再加一次")
        return simple_returns(prices)
    if distributions is None:
        raise ValueError(f"{price_type} 未含分配；计算总收益需给出分配序列，"
                         "或明确改用 simple_returns 计算价格收益")
    dist = distributions.reindex(prices.index)
    if events_complete:
        dist[~prices.index.isin(distributions.index)] = 0.0
    return (prices + dist) / prices.shift(1) - 1


def to_base_currency(local: pd.Series | float, fx: pd.Series | float) -> pd.Series | float:
    """1 + r_base = (1 + r_local) × (1 + r_fx)。

    ``fx`` 为「一单位当地货币值多少基准货币」的变化率。已含汇率影响的收益不要再换算。
    """
    return (1 + local) * (1 + fx) - 1


def cumulative(returns: pd.Series) -> float:
    """几何累计收益；存在缺失时返回 NaN，而不是跳过缺失期。"""
    if returns.isna().any():
        return float("nan")
    return float(np.prod(1 + returns.to_numpy()) - 1)


def annualized_geometric(total_return: float, years: float) -> float:
    """几何年化（CAGR）。不能直接当作单期算术预期收益。"""
    if years <= 0:
        raise ValueError("年数必须为正")
    return (1 + total_return) ** (1 / years) - 1


def arithmetic_mean(returns: pd.Series, periods_per_year: int | None = None) -> float:
    """算术平均；给出 periods_per_year 时线性放大为年化算术均值。"""
    m = float(returns.dropna().mean())
    return m * periods_per_year if periods_per_year else m
