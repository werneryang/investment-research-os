"""数据质量检查（模块 V 的数据层部分，architecture §7.2）。

缺失与异常显式标记，不以零、前值或替代来源静默填补。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contracts import QualityStatus

# 来源用来表示「无数值」的写法
MISSING_TOKENS = {"", ".", "n/a", "na", "nd", "null", "none", "#n/a"}

# 低频数据允许的最大期间间隔；超过即报告缺口
_EXPECTED_STEP = {"monthly": "MS", "quarterly": "QS", "annual": "YS"}


def classify_values(raw: pd.Series, value_range: tuple[float, float] | None) -> pd.DataFrame:
    """把原始字符串转为数值，并逐行给出质量状态与理由。"""
    text = raw.fillna("").astype(str).str.strip()
    is_missing = text.str.lower().isin(MISSING_TOKENS)
    value = pd.to_numeric(text.where(~is_missing), errors="coerce")
    unparseable = ~is_missing & value.isna()

    status = pd.Series(QualityStatus.OK.value, index=raw.index, dtype="object")
    reason = pd.Series("", index=raw.index, dtype="object")
    status[is_missing] = QualityStatus.MISSING.value
    reason[is_missing] = "source_missing:" + text[is_missing]
    status[unparseable] = QualityStatus.QUARANTINED.value
    reason[unparseable] = "unparseable:" + text[unparseable]
    if value_range is not None:
        lo, hi = value_range
        out = value.notna() & ((value < lo) | (value > hi))
        status[out] = QualityStatus.QUARANTINED.value
        reason[out] = f"out_of_range:[{lo},{hi}]"
    return pd.DataFrame({"value": value.astype("float64"), "quality_status": status, "reason": reason})


def resolve_duplicates(df: pd.DataFrame, key: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    """完全相同的重复只保留一条；同键不同值的冲突全部隔离。"""
    exact = df.duplicated(subset=key + ["value", "quality_status"], keep="first")
    df = df[~exact].copy()
    conflict = df.duplicated(subset=key, keep=False)
    df.loc[conflict, "quality_status"] = QualityStatus.QUARANTINED.value
    df.loc[conflict, "reason"] = "conflicting_duplicate"
    return df, {"exact_duplicates_dropped": int(exact.sum()), "conflicting_rows": int(conflict.sum())}


def dataset_report(df: pd.DataFrame, frequency: str) -> dict[str, Any]:
    """数据集级质量报告：计数、各序列覆盖与缺口。"""
    counts = df["quality_status"].value_counts().to_dict()
    issues: list[dict[str, Any]] = []
    series: dict[str, Any] = {}
    for sid, g in df.groupby("series_id", sort=True):
        ok = g[g["quality_status"] == QualityStatus.OK.value]
        obs = pd.to_datetime(ok["observation_at"]).drop_duplicates().sort_values()
        entry = {
            "rows": int(len(g)),
            "ok": int(len(ok)),
            "missing": int((g["quality_status"] == QualityStatus.MISSING.value).sum()),
            "quarantined": int((g["quality_status"] == QualityStatus.QUARANTINED.value).sum()),
            "first": obs.iloc[0].date().isoformat() if len(obs) else None,
            "last": obs.iloc[-1].date().isoformat() if len(obs) else None,
        }
        if frequency in _EXPECTED_STEP and len(obs) > 1:
            expected = pd.date_range(obs.iloc[0], obs.iloc[-1], freq=_EXPECTED_STEP[frequency])
            gaps = expected.difference(pd.DatetimeIndex(obs))
            if len(gaps):
                entry["gaps"] = int(len(gaps))
                issues.append({"series_id": sid, "type": "gap", "periods": int(len(gaps)),
                               "examples": [d.date().isoformat() for d in gaps[:5]]})
        elif frequency == "daily" and len(obs) > 1:
            max_gap = int(obs.diff().dt.days.max())
            entry["max_gap_days"] = max_gap
            if max_gap > 7:
                issues.append({"series_id": sid, "type": "gap", "max_gap_days": max_gap})
        if entry["quarantined"]:
            reasons = g.loc[g["quality_status"] == QualityStatus.QUARANTINED.value, "reason"]
            issues.append({"series_id": sid, "type": "quarantined",
                           "reasons": reasons.value_counts().to_dict()})
        series[str(sid)] = entry
    return {
        "rows": int(len(df)),
        "status_counts": {k: int(v) for k, v in counts.items()},
        "series": series,
        "issues": issues,
    }


def ok_rows(df: pd.DataFrame) -> pd.DataFrame:
    """下游分析唯一允许使用的行。"""
    return df[(df["quality_status"] == QualityStatus.OK.value) & np.isfinite(df["value"])]
