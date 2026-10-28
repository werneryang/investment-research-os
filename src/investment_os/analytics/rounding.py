"""按公布精度做区间比较：复算值与公布值是否在舍入误差内相容（不凭经验设容差）。"""

from __future__ import annotations

import math


def decimals_ok(value: float, decimals: int, tol: float = 1e-9) -> bool:
    """value 是否恰好保留 decimals 位小数（公布值的显示精度）。"""
    scaled = value * 10 ** decimals
    return abs(scaled - round(scaled)) <= tol * max(1.0, abs(scaled))


def half_step(decimals: int) -> float:
    return 0.5 * 10 ** (-decimals)


def ratio_interval(num: float, num_decimals: int, den: float, den_decimals: int,
                   scale: float = 1.0) -> tuple[float, float]:
    """num ÷ den × scale 在两者各自舍入误差下的取值区间；只适用于正分子与正分母。"""
    hn, hd = half_step(num_decimals), half_step(den_decimals)
    if num - hn < 0 or den - hd <= 0:
        raise ValueError("区间比较只适用于正分子与正分母")
    return scale * (num - hn) / (den + hd), scale * (num + hn) / (den - hd)


def compatible(interval: tuple[float, float], published: float, published_decimals: int,
               tol: float = 1e-9) -> bool:
    """复算区间与公布值的舍入区间 [p − h, p + h] 是否相交。"""
    h = half_step(published_decimals)
    lo, hi = interval
    if any(math.isnan(x) for x in (lo, hi, published)):
        return False
    return hi >= published - h - tol and lo <= published + h + tol
