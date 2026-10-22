"""时间契约：观测期间、发布时间与可用时间（architecture §6.2）。"""

from __future__ import annotations

import pandas as pd

from ..contracts import AvailabilityRule


def period_end(observation_at: pd.Series, frequency: str) -> pd.Series:
    """观测期间的最后一天（观测日期表示期间起点）。"""
    obs = pd.to_datetime(observation_at)
    if frequency == "daily":
        return obs
    if frequency == "weekly":
        return obs + pd.Timedelta(days=6)
    offsets = {"monthly": pd.offsets.MonthEnd(0), "quarterly": pd.offsets.QuarterEnd(0),
               "annual": pd.offsets.YearEnd(0)}
    if frequency not in offsets:
        raise ValueError(f"未知频率：{frequency}")
    return obs + offsets[frequency]


def _local_midnight_utc(days: pd.Series, tz: str) -> pd.Series:
    return pd.to_datetime(days).dt.normalize().dt.tz_localize(tz).dt.tz_convert("UTC")


def published_to_utc(published: pd.Series, tz: str) -> pd.Series:
    """来源只给出发布日期时，以来源时区当日 0 点表示（精度为日）。"""
    out = pd.Series(pd.NaT, index=published.index, dtype="datetime64[ns, UTC]")
    mask = published.notna()
    if mask.any():
        out[mask] = _local_midnight_utc(published[mask], tz)
    return out


def available_at(
    observation_at: pd.Series,
    published_at: pd.Series,
    frequency: str,
    rule: AvailabilityRule,
    tz: str,
) -> pd.Series:
    """按明示规则计算最早可用时点；无法确定时留空，不猜测。"""
    out = pd.Series(pd.NaT, index=observation_at.index, dtype="datetime64[ns, UTC]")
    if rule.type == "unknown" or observation_at.empty:
        return out
    if rule.type == "next_day":
        return _local_midnight_utc(period_end(observation_at, "daily") + pd.Timedelta(days=1), tz)
    if rule.type == "period_end_lag_days":
        end = period_end(observation_at, frequency)
        return _local_midnight_utc(end + pd.Timedelta(days=rule.days + 1), tz)
    # published_next_day：没有发布日期的行保持未知
    pub = published_at.notna()
    if pub.any():
        local_pub = published_at[pub].dt.tz_convert(tz).dt.tz_localize(None)
        out[pub] = _local_midnight_utc(local_pub + pd.Timedelta(days=1), tz)
    return out
