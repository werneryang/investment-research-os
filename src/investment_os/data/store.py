"""原始快照、标准化版本与目录（模块 S）。

布局（均在 <root>/data 下，默认不提交 Git）：
    raw/<dataset>/<时间>_<sha8>.<ext>      原始字节，原样保存；内容相同的再次取得不另存（2026-10-23 起）
    raw/<dataset>/<时间>_<sha8>.meta.json  首次取得该内容的记录
    normalized/<dataset>/<version>.parquet 标准化版本，只追加不覆盖
    catalog/<dataset>.jsonl                版本目录（含血缘与质量报告）
    catalog/fetch_log.jsonl                每次取得尝试，含失败

单写入者流程：同一时间只运行一个写入命令。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..connectors.base import RawPayload
from ..contracts import (
    SERIES_COLUMNS,
    SERIES_SCHEMA_VERSION,
    DatasetVersion,
    VintageSupport,
)

LOCAL_VINTAGE_PREFIX = "local:"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso(series: pd.Series) -> pd.Series:
    return series.map(lambda v: "" if pd.isna(v) else pd.Timestamp(v).isoformat())


def content_hash(df: pd.DataFrame) -> str:
    """数据内容校验值。

    不含取得时间与本地快照编号：内容相同的再次取得不产生新版本。
    供应方历史版本编号属于内容，保留。
    """
    canon = df[SERIES_COLUMNS].copy()
    canon["retrieved_at"] = ""
    vint = canon["vintage_id"].fillna("").astype(str)
    canon["vintage_id"] = vint.where(~vint.str.startswith(LOCAL_VINTAGE_PREFIX), "")
    for col in ("observation_at", "published_at", "available_at"):
        canon[col] = _iso(canon[col])
    canon["value"] = canon["value"].map(lambda v: "" if pd.isna(v) else repr(float(v)))
    canon = canon.fillna("").astype(str)
    canon = canon.sort_values(["series_id", "observation_at", "vintage_id"]).reset_index(drop=True)
    return sha256_bytes(canon.to_csv(index=False).encode("utf-8"))


class DataStore:
    def __init__(self, root: Path) -> None:
        self.base = Path(root) / "data"

    # ---- 原始快照 -------------------------------------------------------
    def save_raw(self, dataset_id: str, payload: RawPayload) -> dict[str, Any]:
        """保存原始字节并返回引用。

        同一数据集已有内容完全相同的文件时不再另存，引用指向已有文件（reused: true）；
        本次取得的时间、地址与请求仍记在返回的引用里，由取得记录保存。
        """
        digest = sha256_bytes(payload.content)
        folder = self.base / "raw" / dataset_id
        folder.mkdir(parents=True, exist_ok=True)
        ref = {
            "sha256": digest,
            "bytes": len(payload.content),
            "url": payload.url,
            "request": payload.request,
            "retrieved_at": payload.retrieved_at.isoformat(),
        }
        existing = self.find_raw(folder, digest, payload.extension)
        if existing is not None:
            return {"path": str(existing.relative_to(self.base)), **ref, "reused": True}
        stem = f"{compact(payload.retrieved_at)}_{digest[:8]}"
        path = folder / f"{stem}.{payload.extension}"
        if not path.exists():
            path.write_bytes(payload.content)
        ref = {"path": str(path.relative_to(self.base)), **ref}
        (folder / f"{stem}.meta.json").write_text(
            json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")
        return ref

    def find_raw(self, folder: Path, digest: str, extension: str) -> Path | None:
        """同一文件夹中内容校验值为 digest 的最早文件；按完整校验值确认，不只看文件名中的前缀。"""
        for path in sorted(folder.glob(f"*_{digest[:8]}.{extension}")):
            if sha256_bytes(path.read_bytes()) == digest:
                return path
        return None

    def read_raw(self, ref: dict[str, Any]) -> bytes:
        data = (self.base / ref["path"]).read_bytes()
        if sha256_bytes(data) != ref["sha256"]:
            raise ValueError(f"原始快照校验失败：{ref['path']}")
        return data

    # ---- 标准化版本 -----------------------------------------------------
    def _catalog_path(self, dataset_id: str) -> Path:
        return self.base / "catalog" / f"{dataset_id}.jsonl"

    def versions(self, dataset_id: str) -> list[DatasetVersion]:
        path = self._catalog_path(dataset_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [DatasetVersion.from_dict(json.loads(line)) for line in lines if line.strip()]

    def latest(self, dataset_id: str) -> DatasetVersion | None:
        versions = self.versions(dataset_id)
        return versions[-1] if versions else None

    def get_version(self, dataset_id: str, version_id: str | None = None) -> DatasetVersion:
        if version_id is None:
            v = self.latest(dataset_id)
            if v is None:
                raise LookupError(f"数据集 {dataset_id} 尚无标准化版本；请先运行 iros fetch {dataset_id}")
            return v
        for v in self.versions(dataset_id):
            if v.version_id == version_id:
                return v
        raise LookupError(f"数据集 {dataset_id} 没有版本 {version_id}")

    def load(self, dataset_id: str, version_id: str | None = None) -> tuple[pd.DataFrame, DatasetVersion]:
        v = self.get_version(dataset_id, version_id)
        df = pd.read_parquet(self.base / v.path)
        if content_hash(df) != v.content_hash:
            raise ValueError(f"版本 {v.version_id} 内容与目录校验值不一致，可能被改动")
        return df, v

    def save_version(
        self,
        dataset_id: str,
        df: pd.DataFrame,
        *,
        raw_snapshots: list[dict[str, Any]],
        transform: str,
        quality: dict[str, Any],
        series: dict[str, dict[str, Any]],
        parent_version: str | None,
        created_at: datetime,
    ) -> DatasetVersion:
        df = df[SERIES_COLUMNS].sort_values(["series_id", "observation_at", "vintage_id"],
                                            na_position="first").reset_index(drop=True)
        digest = content_hash(df)
        version_id = f"v{compact(created_at)}-{digest[:8]}"
        rel = Path("normalized") / dataset_id / f"{version_id}.parquet"
        (self.base / rel).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(self.base / rel, index=False)
        version = DatasetVersion(
            dataset_id=dataset_id,
            version_id=version_id,
            schema_version=SERIES_SCHEMA_VERSION,
            content_hash=digest,
            created_at=created_at.isoformat(),
            rows=int(len(df)),
            path=str(rel),
            raw_snapshots=raw_snapshots,
            transform=transform,
            quality=quality,
            series=series,
            parent_version=parent_version,
        )
        self._append(self._catalog_path(dataset_id), version.to_dict())
        return version

    # ---- 取得记录 -------------------------------------------------------
    def log_fetch(self, entry: dict[str, Any]) -> None:
        self._append(self.base / "catalog" / "fetch_log.jsonl", entry)

    def fetch_log(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        path = self.base / "catalog" / "fetch_log.jsonl"
        if not path.exists():
            return []
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        return [e for e in entries if dataset_id is None or e.get("dataset_id") == dataset_id]

    @staticmethod
    def _append(path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def to_utc(at: datetime | pd.Timestamp | str) -> pd.Timestamp:
    ts = pd.Timestamp(at)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def eligibility_as_of(df: pd.DataFrame, at: datetime | pd.Timestamp,
                      vintages: VintageSupport) -> pd.DataFrame:
    """逐行判断能否证明「在 at 时已知」，返回 eligible 与 reason 两列。

    - available_at 未知：不能证明，排除
    - available_at 晚于 at：当时尚未可用，排除
    - 供应方历史版本（有发布日期的非本地版本）：available_at 即为证据
    - 其他（当前修订版本、本地快照）：还需 retrieved_at ≤ at，即本系统当时确已取得；
      可用时间规则只表达假定的发布延迟，不能证明修订值当时已知
    """
    at = to_utc(at)
    avail_known = df["available_at"].notna()
    avail_ok = avail_known & (df["available_at"] <= at)
    supplier = pd.Series(False, index=df.index)
    if vintages is VintageSupport.SUPPLIER:
        vint = df["vintage_id"].fillna("").astype(str)
        supplier = ~vint.str.startswith(LOCAL_VINTAGE_PREFIX) & df["published_at"].notna()
    retrieved_ok = df["retrieved_at"].notna() & (df["retrieved_at"] <= at)
    eligible = avail_ok & (supplier | retrieved_ok)
    reason = pd.Series("", index=df.index, dtype="object")
    reason[~avail_known] = "available_at_unknown"
    reason[avail_known & ~avail_ok] = "not_yet_available"
    reason[avail_ok & ~supplier & ~retrieved_ok] = "no_evidence_known_then"
    return pd.DataFrame({"eligible": eligible, "reason": reason})


def as_of(df: pd.DataFrame, at: datetime | pd.Timestamp,
          vintages: VintageSupport = VintageSupport.NONE) -> pd.DataFrame:
    """时点视图：只保留能证明在 at 时已知的行，每个观测取当时最新的版本。"""
    known = df[eligibility_as_of(df, at, vintages)["eligible"]]
    known = known.sort_values(["series_id", "observation_at", "available_at", "retrieved_at"])
    return known.groupby(["series_id", "observation_at"], as_index=False, sort=False).tail(1)


def version_as_of(versions: list[DatasetVersion], at: datetime | pd.Timestamp) -> DatasetVersion | None:
    """at 时本系统已有的最新版本；当前修订数据集的时点重放只能用它。"""
    at = to_utc(at)
    earlier = [v for v in versions if to_utc(v.created_at) <= at]
    return earlier[-1] if earlier else None
