"""人工导入：本地 CSV 与导入声明一起作为正式接入路径（architecture §5.1）。"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..contracts import DatasetSpec
from .base import (
    STAGING_COLUMNS,
    FetchError,
    ParsedPayload,
    RawPayload,
    empty_staging,
    now_utc,
)


class ManualCsvConnector:
    """CSV 至少含 observation_at、value 列；可选 series_id、published_at。

    request 必须给出 ``path`` 与 ``declared_source``（原始发布者与取得方式），
    后者随快照保存，便于追溯。
    """

    name = "manual_csv"

    def __init__(self, **_: Any) -> None:
        pass  # 本地文件无需网络参数

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        path = request.get("path")
        declared = (request.get("declared_source") or "").strip()
        if not path:
            raise FetchError("人工导入需要文件路径")
        if not declared:
            raise FetchError("人工导入需要声明原始来源（发布者、取得方式与日期）")
        p = Path(path)
        if not p.is_file():
            raise FetchError(f"找不到导入文件：{p}")
        return [RawPayload(
            content=p.read_bytes(),
            url=f"file://{p.resolve()}",
            request={"filename": p.name, "declared_source": declared},
            retrieved_at=now_utc(),
            extension=p.suffix.lstrip(".") or "csv",
        )]

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        reader = csv.DictReader(io.StringIO(payload.content.decode("utf-8-sig")))
        fields = set(reader.fieldnames or [])
        if not {"observation_at", "value"} <= fields:
            raise FetchError(f"导入文件需含 observation_at 与 value 列，实际为 {sorted(fields)}")
        rows = []
        for r in reader:
            if not (r.get("observation_at") or "").strip():
                continue
            published = (r.get("published_at") or "").strip()
            rows.append((
                (r.get("series_id") or "").strip() or dataset.id,
                date.fromisoformat(r["observation_at"].strip()),
                (r.get("value") or "").strip(),
                date.fromisoformat(published) if published else None,
                None,
            ))
        staging = pd.DataFrame(rows, columns=STAGING_COLUMNS) if rows else empty_staging()
        series = {sid: {"declared_source": payload.request.get("declared_source")}
                  for sid in staging["series_id"].unique()}
        return ParsedPayload(staging, series)
