"""固定现金流债券的定价与利率敏感性（公共分析，模块 A）。

约定：收益率与票息为年化小数（0.04 即 4%），按每年 ``freq`` 次复利与付息（债券等价收益率）；
期限为整数个付息期，估值日恰在付息日（无应计利息）。久期以年为单位，凸性以年² 为单位。

这些函数只描述给定现金流在给定收益率下的数学性质，不代表任何真实债券或基金的风险。
"""

from __future__ import annotations

import math


def _periods(years: float, freq: int) -> int:
    n = years * freq
    if abs(n - round(n)) > 1e-9 or round(n) < 1:
        raise ValueError(f"期限 {years} 年在每年 {freq} 次付息下不是整数个付息期")
    return int(round(n))


def cash_flows(coupon: float, years: float, freq: int = 2, face: float = 100.0) -> list[tuple[float, float]]:
    """[(时间（年）, 现金流)]，最后一期含本金。"""
    n = _periods(years, freq)
    c = face * coupon / freq
    return [(k / freq, c + (face if k == n else 0.0)) for k in range(1, n + 1)]


def price(coupon: float, ytm: float, years: float, freq: int = 2, face: float = 100.0) -> float:
    """完整重新定价：按收益率贴现全部现金流。"""
    r = ytm / freq
    return sum(cf / (1 + r) ** (t * freq) for t, cf in cash_flows(coupon, years, freq, face))


def macaulay_duration(coupon: float, ytm: float, years: float, freq: int = 2, face: float = 100.0) -> float:
    r = ytm / freq
    flows = cash_flows(coupon, years, freq, face)
    p = sum(cf / (1 + r) ** (t * freq) for t, cf in flows)
    return sum(t * cf / (1 + r) ** (t * freq) for t, cf in flows) / p


def modified_duration(coupon: float, ytm: float, years: float, freq: int = 2, face: float = 100.0) -> float:
    return macaulay_duration(coupon, ytm, years, freq, face) / (1 + ytm / freq)


def convexity(coupon: float, ytm: float, years: float, freq: int = 2, face: float = 100.0) -> float:
    """解析凸性 (1/P)·d²P/dy²（按每年 freq 次复利的收益率求导）。"""
    r = ytm / freq
    flows = cash_flows(coupon, years, freq, face)
    p = sum(cf / (1 + r) ** (t * freq) for t, cf in flows)
    s = sum(cf * (t * freq) * (t * freq + 1) / (1 + r) ** (t * freq + 2) for t, cf in flows)
    return s / (p * freq**2)


def dv01(coupon: float, ytm: float, years: float, freq: int = 2, face: float = 100.0) -> float:
    """收益率下降 1 bp 时价格的近似上升额（每 face 面值）。"""
    return modified_duration(coupon, ytm, years, freq, face) * price(coupon, ytm, years, freq, face) * 1e-4


def par_modified_duration_closed_form(ytm: float, years: float, freq: int = 2) -> float:
    """平价债券（票息 = 收益率）修正久期的封闭解：(1 − (1 + y/f)^(−n)) / y。"""
    n = _periods(years, freq)
    if ytm == 0:
        return years  # 极限情形
    return (1 - (1 + ytm / freq) ** (-n)) / ytm


def effective_duration(coupon: float, ytm: float, years: float, freq: int = 2, h: float = 1e-4) -> float:
    """有效久期：用 ±h 完整重新定价的中心差分，作为解析久期的独立核对。"""
    p0, up, down = (price(coupon, y, years, freq) for y in (ytm, ytm + h, ytm - h))
    return (down - up) / (2 * p0 * h)


def effective_convexity(coupon: float, ytm: float, years: float, freq: int = 2, h: float = 1e-4) -> float:
    p0, up, down = (price(coupon, y, years, freq) for y in (ytm, ytm + h, ytm - h))
    return (up + down - 2 * p0) / (p0 * h * h)


def scenario(coupon: float, ytm: float, years: float, shock_bp: float, freq: int = 2) -> dict[str, float]:
    """收益率平移 shock_bp 后的价格变化（%）：完整重新定价、久期近似、久期 + 凸性近似及其误差。

    误差 = 近似 − 完整重新定价，单位为百分点（价格变化率之差）。
    """
    dy = shock_bp / 1e4
    if ytm + dy <= -freq:
        raise ValueError("冲击后收益率不在可定价范围内")
    p0 = price(coupon, ytm, years, freq)
    p1 = price(coupon, ytm + dy, years, freq)
    d = modified_duration(coupon, ytm, years, freq)
    c = convexity(coupon, ytm, years, freq)
    full = (p1 / p0 - 1) * 100
    dur = -d * dy * 100
    dur_conv = (-d * dy + 0.5 * c * dy * dy) * 100
    return {"shock_bp": shock_bp, "full_pct": full, "duration_pct": dur, "duration_convexity_pct": dur_conv,
            "duration_error_pp": dur - full, "duration_convexity_error_pp": dur_conv - full}


def is_close(a: float, b: float, rel: float = 1e-9, abs_tol: float = 1e-12) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
