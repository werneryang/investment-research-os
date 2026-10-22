"""两条序列的一致性比较。是否构成独立验证由调用方按来源关系说明。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def compare_series(a: pd.Series, b: pd.Series, tolerance: float) -> dict[str, Any]:
    """按日期对齐比较；只比较两边都有有效值的日期。"""
    a, b = a.dropna(), b.dropna()
    joined = pd.concat({"a": a, "b": b}, axis=1, join="inner")
    if joined.empty:
        return {"status": "skipped", "reason": "没有共同日期", "matched": 0}
    diff = (joined["a"] - joined["b"]).abs()
    bad = diff[diff > tolerance + 1e-12]
    return {
        "status": "pass" if bad.empty else "fail",
        "matched": int(len(joined)),
        "only_in_primary": int(len(a.index.difference(b.index))),
        "only_in_other": int(len(b.index.difference(a.index))),
        "max_abs_diff": float(diff.max()),
        "tolerance": tolerance,
        "mismatches": [{"date": d.date().isoformat(), "primary": float(joined.at[d, "a"]),
                        "other": float(joined.at[d, "b"])} for d in bad.index[:10]],
    }
