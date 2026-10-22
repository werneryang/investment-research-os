"""标准化结果与原始快照的逐点抽查。

使用标准库 csv 独立读取原始文件，不复用接入器的解析代码，
用于发现解析、单位或日期对齐错误（architecture §8 数据与工程层）。
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

import pandas as pd

from ..contracts import DatasetVersion
from ..data.store import DataStore
from ..quality import ok_rows

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")


def _parse_date(text: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _raw_index(store: DataStore, version: DatasetVersion) -> dict[tuple[date, str], str]:
    """(日期, 原始列名) → 原始字符串；按快照顺序，后取得的覆盖先取得的。"""
    index: dict[tuple[date, str], str] = {}
    for ref in version.raw_snapshots:
        if not ref["path"].endswith(".csv"):
            continue
        reader = csv.reader(io.StringIO(store.read_raw(ref).decode("utf-8-sig")))
        header = next(reader, [])
        for row in reader:
            if not row:
                continue
            d = _parse_date(row[0])
            if d is None:
                continue
            for label, raw in zip(header[1:], row[1:], strict=False):  # 行可能短于表头
                index[(d, label.strip())] = raw.strip()
    return index


def spot_check(store: DataStore, version: DatasetVersion, frame: pd.DataFrame,
               samples: int = 12, tolerance: float = 1e-9) -> dict[str, Any]:
    """等距抽取合格观测，与原始快照中的同一单元格比较。"""
    labels = {sid: meta.get("source_label") or meta.get("fred_series")
              for sid, meta in version.series.items()}
    rows = ok_rows(frame).sort_values(["observation_at", "series_id"]).reset_index(drop=True)
    rows = rows[rows["series_id"].map(labels).notna()]
    if rows.empty:
        return {"status": "skipped", "reason": "没有可在原始 CSV 中定位的合格观测"}
    picks = sorted({round(i * (len(rows) - 1) / max(samples - 1, 1)) for i in range(samples)})
    index = _raw_index(store, version)
    checked, failures = [], []
    for i in picks:
        r = rows.iloc[i]
        key = (r["observation_at"].date(), labels[r["series_id"]])
        raw = index.get(key)
        item = {"series_id": r["series_id"], "date": key[0].isoformat(), "normalized": float(r["value"]),
                "raw": raw}
        checked.append(item)
        if raw is None or abs(float(raw) - float(r["value"])) > tolerance:
            failures.append(item)
    return {"status": "pass" if not failures else "fail", "checked": len(checked),
            "failures": failures, "samples": checked}
