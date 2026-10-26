"""取得 → 原始快照 → 解析 → 标准化 → 质量 → 版本化。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from ..connectors import Connector, FetchError, get_connector
from ..connectors.base import now_utc, redact
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
    clock: Callable[[], datetime] = now_utc,
) -> IngestResult:
    """取得一次并版本化。

    开始即写入 started 记录；任何阶段失败都写入 failed 终态（含阶段与已保存的原始快照），
    旧版本保持不变。失败结果如实返回，不吞掉异常冒充成功。
    """
    spec = registry.dataset(dataset_id)
    connector = connector or get_connector(spec.connector)
    started = clock()
    previous = store.latest(dataset_id)
    attempt_id = uuid.uuid4().hex[:12]
    log: dict[str, Any] = {"attempt_id": attempt_id, "dataset_id": dataset_id,
                           "started_at": started.isoformat(), "connector": connector.name,
                           "request": {k: v for k, v in request.items() if k != "path"}}
    store.log_fetch({**log, "status": "started"})
    raw_refs: list[dict[str, Any]] = []
    stage = "fetch"

    def finish(status: str, **extra: Any) -> None:
        store.log_fetch({**log, "status": status, "finished_at": clock().isoformat(),
                         "raw_snapshots": raw_refs, **extra})

    try:
        payloads = connector.fetch(spec, request)
        if not payloads:
            raise FetchError("接入器未返回任何资料")

        stage = "snapshot"
        raw_refs = [store.save_raw(dataset_id, p) for p in payloads]

        stage = "parse"
        staged, series_meta = [], {}
        for p in payloads:
            parsed = connector.parse(spec, p)
            staged.append(parsed.staging)
            series_meta.update(parsed.series)
        staging = pd.concat(staged, ignore_index=True)
        if staging.empty:
            raise FetchError("取得的资料不含任何观测")

        stage = "normalize"
        retrieved_at = max(p.retrieved_at for p in payloads)
        new = normalize(spec, staging, pd.Timestamp(retrieved_at),
                        f"{LOCAL_VINTAGE_PREFIX}{compact(retrieved_at)}")
        new, dup_stats = resolve_duplicates(new, ["series_id", "observation_at", "vintage_id"])

        stage = "merge"
        prev_df = None
        # Evidence bundles are authoritative full snapshots. Older versions and
        # their raw files stay in the catalog, but removed observations must not
        # be carried into the next snapshot or accumulate indefinitely.
        replace_snapshot = bool(spec.params.get("replace_snapshot", False))
        if previous is not None and not replace_snapshot:
            prev_df, _ = store.load(dataset_id, previous.version_id)
            series_meta = {**previous.series, **series_meta}
        merged = _merge(prev_df, new)
        report = dataset_report(merged, spec.frequency)
        report["duplicates"] = dup_stats
        report["availability_rule"] = spec.availability.describe()
        report["time_precision"] = "day"  # 可用与发布时间均只精确到日
        report["vintages"] = spec.vintages.value

        if previous is not None and content_hash(merged) == previous.content_hash:
            finish("unchanged", kept_version=previous.version_id)
            return IngestResult(dataset_id, "unchanged", "内容与最新版本相同，未创建新版本", previous)

        stage = "save"
        version = store.save_version(
            dataset_id, merged,
            raw_snapshots=([*previous.raw_snapshots] if previous and not replace_snapshot else []) + raw_refs,
            transform=TRANSFORM_ID,
            quality=report,
            series=series_meta,
            parent_version=previous.version_id if previous else None,
            created_at=clock(),
        )
    except Exception as e:  # noqa: BLE001 - 任何阶段的失败都要留下终态记录
        message = redact(f"{stage} 阶段失败：{type(e).__name__}: {e}")
        if raw_refs:
            message += "（原始快照已保存供诊断）"
        finish("failed", stage=stage, error=message,
               kept_version=previous.version_id if previous else None)
        return IngestResult(dataset_id, "failed", message, previous)

    finish("created", version_id=version.version_id)
    return IngestResult(dataset_id, "created", f"已创建版本 {version.version_id}（{version.rows} 行）",
                        version)
