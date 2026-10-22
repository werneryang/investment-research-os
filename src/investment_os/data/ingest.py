"""取得 → 原始快照 → 解析 → 标准化 → 质量 → 版本化。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..connectors import Connector, FetchError, get_connector
from ..connectors.base import now_utc
from ..contracts import SERIES_COLUMNS, DatasetSpec, DatasetVersion
from ..quality import classify_values, dataset_report, resolve_duplicates
from ..registry import Registry
from .store import LOCAL_VINTAGE_PREFIX, DataStore, compact, content_hash
from .timing import available_at, published_to_utc

TRANSFORM_ID = "normalize.v1"


@dataclass
class IngestResult:
    dataset_id: str
    status: str  # created | unchanged | failed
    message: str
    version: DatasetVersion | None  # 新版本，或失败/未变化时仍可用的已有版本


def normalize(spec: DatasetSpec, staging: pd.DataFrame, retrieved_at: pd.Timestamp,
              local_vintage: str) -> pd.DataFrame:
    """暂存表 → 标准化序列表（SERIES_COLUMNS）。"""
    df = staging.reset_index(drop=True)
    quality = classify_values(df["raw_value"], spec.value_range)
    obs = pd.to_datetime(df["observation_at"])
    published = published_to_utc(df["published_at"], spec.timezone)
    vintage = df["vintage_label"].where(df["vintage_label"].notna(), local_vintage)
    out = pd.DataFrame({
        "series_id": df["series_id"].astype(str),
        "observation_at": obs,
        "value": quality["value"],
        "unit": spec.unit,
        "frequency": spec.frequency,
        "currency": spec.currency,
        "published_at": published,
        "available_at": available_at(obs, published, spec.frequency, spec.availability, spec.timezone),
        "retrieved_at": pd.Timestamp(retrieved_at).tz_convert("UTC"),
        "vintage_id": vintage.astype(str),
        "source_id": spec.source_id,
        "upstream_id": spec.upstream_id,
        "quality_status": quality["quality_status"],
        "reason": quality["reason"],
    })
    return out[SERIES_COLUMNS]


def _merge(previous: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """新取得的观测替换旧版本中的同一观测；供应方历史版本按版本号并存。"""
    if previous is None or previous.empty:
        return new
    supplier_vintages = not new["vintage_id"].str.startswith(LOCAL_VINTAGE_PREFIX).all()
    key = ["series_id", "observation_at"] + (["vintage_id"] if supplier_vintages else [])
    new_keys = pd.MultiIndex.from_frame(new[key])
    keep = ~pd.MultiIndex.from_frame(previous[key]).isin(new_keys)
    return pd.concat([previous[keep], new], ignore_index=True)


def ingest(
    registry: Registry,
    store: DataStore,
    dataset_id: str,
    request: dict[str, Any],
    connector: Connector | None = None,
) -> IngestResult:
    spec = registry.dataset(dataset_id)
    connector = connector or get_connector(spec.connector)
    started = now_utc()
    previous = store.latest(dataset_id)
    log: dict[str, Any] = {"dataset_id": dataset_id, "started_at": started.isoformat(),
                           "connector": connector.name,
                           "request": {k: v for k, v in request.items() if k != "path"}}

    def fail(message: str, raw_refs: list[dict[str, Any]] | None = None) -> IngestResult:
        # 失败时保留旧版本并记录，不生成新的更新时间
        store.log_fetch({**log, "status": "failed", "error": message, "raw_snapshots": raw_refs or [],
                         "kept_version": previous.version_id if previous else None})
        return IngestResult(dataset_id, "failed", message, previous)

    try:
        payloads = connector.fetch(spec, request)
    except (FetchError, ValueError, OSError) as e:
        return fail(str(e))
    if not payloads:
        return fail("接入器未返回任何资料")

    raw_refs = [store.save_raw(dataset_id, p) for p in payloads]
    staged, series_meta = [], {}
    try:
        for p in payloads:
            parsed = connector.parse(spec, p)
            staged.append(parsed.staging)
            series_meta.update(parsed.series)
    except (FetchError, ValueError, KeyError, IndexError) as e:
        return fail(f"解析失败（原始快照已保存供诊断）：{e}", raw_refs)

    retrieved_at = max(p.retrieved_at for p in payloads)
    staging = pd.concat(staged, ignore_index=True)
    if staging.empty:
        return fail("取得的资料不含任何观测", raw_refs)

    new = normalize(spec, staging, pd.Timestamp(retrieved_at),
                    f"{LOCAL_VINTAGE_PREFIX}{compact(retrieved_at)}")
    new, dup_stats = resolve_duplicates(new, ["series_id", "observation_at", "vintage_id"])

    prev_df = None
    if previous is not None:
        prev_df, _ = store.load(dataset_id, previous.version_id)
        series_meta = {**previous.series, **series_meta}
    merged = _merge(prev_df, new)
    report = dataset_report(merged, spec.frequency)
    report["duplicates"] = dup_stats
    report["availability_rule"] = spec.availability.describe()

    if previous is not None and content_hash(merged) == previous.content_hash:
        store.log_fetch({**log, "status": "unchanged", "raw_snapshots": raw_refs,
                         "kept_version": previous.version_id})
        return IngestResult(dataset_id, "unchanged", "内容与最新版本相同，未创建新版本", previous)

    version = store.save_version(
        dataset_id, merged,
        raw_snapshots=([*previous.raw_snapshots] if previous else []) + raw_refs,
        transform=TRANSFORM_ID,
        quality=report,
        series=series_meta,
        parent_version=previous.version_id if previous else None,
        created_at=now_utc(),
    )
    store.log_fetch({**log, "status": "created", "raw_snapshots": raw_refs,
                     "version_id": version.version_id})
    return IngestResult(dataset_id, "created", f"已创建版本 {version.version_id}（{version.rows} 行）",
                        version)
