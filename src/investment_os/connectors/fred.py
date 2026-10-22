"""FRED 接入：图表 CSV 导出（无 key，仅当前版本）与 API 历史版本（需 key）。"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
from datetime import date
from typing import Any

import pandas as pd

from ..contracts import DatasetSpec
from .base import (
    STAGING_COLUMNS,
    FetchError,
    HttpGet,
    ParsedPayload,
    RawPayload,
    empty_staging,
    fetch_with_retry,
    now_utc,
    urllib_get,
)

GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
API_URL = "https://api.stlouisfed.org/fred/series/observations"


def _series_of(dataset: DatasetSpec) -> str:
    series = dataset.params.get("series")
    if not series:
        raise ValueError(f"数据集 {dataset.id} 未在 params.series 中声明 FRED 序列")
    return series


class FredGraphCsvConnector:
    """fredgraph.csv：只返回当前修订版本，适合描述性研究。"""

    name = "fred_graph_csv"

    def __init__(self, http_get: HttpGet = urllib_get, **retry: Any) -> None:
        self.http_get = http_get
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        series = _series_of(dataset)
        query = {"id": series}
        if request.get("start"):
            query["cosd"] = str(request["start"])
        if request.get("end"):
            query["coed"] = str(request["end"])
        url = f"{GRAPH_URL}?{urllib.parse.urlencode(query)}"
        content = fetch_with_retry(url, self.http_get, **self.retry)
        return [RawPayload(content=content, url=url, request=query, retrieved_at=now_utc())]

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        series = _series_of(dataset)
        reader = csv.reader(io.StringIO(payload.content.decode("utf-8-sig")))
        header = next(reader, None)
        if not header or len(header) < 2 or header[0] not in ("observation_date", "DATE"):
            raise FetchError(f"FRED CSV 表头不符合预期：{header}")
        if header[1] != series:
            raise FetchError(f"FRED CSV 序列为 {header[1]}，登记为 {series}")
        rows = [
            (series, date.fromisoformat(r[0]), r[1].strip() if len(r) > 1 else "", None, None)
            for r in reader if r and r[0].strip()
        ]
        staging = pd.DataFrame(rows, columns=STAGING_COLUMNS) if rows else empty_staging()
        return ParsedPayload(staging, {series: {"fred_series": series}})


class FredApiVintagesConnector:
    """FRED API（ALFRED）：取得全部历史版本，realtime_start 作为该版本的发布日期。

    需要环境变量 FRED_API_KEY。key 不写入快照元数据或运行记录。
    """

    name = "fred_api_vintages"

    def __init__(self, http_get: HttpGet = urllib_get, api_key: str | None = None, **retry: Any) -> None:
        self.http_get = http_get
        self.api_key = api_key
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        key = self.api_key or os.environ.get("FRED_API_KEY")
        if not key:
            raise FetchError("未设置 FRED_API_KEY；可改用无需 key 的 fred_graph 数据集（仅当前版本）")
        series = _series_of(dataset)
        query = {
            "series_id": series,
            "file_type": "json",
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
        }
        if request.get("start"):
            query["observation_start"] = str(request["start"])
        if request.get("end"):
            query["observation_end"] = str(request["end"])
        url = f"{API_URL}?{urllib.parse.urlencode({**query, 'api_key': key})}"
        content = fetch_with_retry(url, self.http_get, **self.retry)
        public_url = f"{API_URL}?{urllib.parse.urlencode(query)}"
        return [RawPayload(content=content, url=public_url, request=query,
                           retrieved_at=now_utc(), extension="json")]

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        series = _series_of(dataset)
        try:
            doc = json.loads(payload.content)
        except json.JSONDecodeError as e:
            raise FetchError(f"FRED API 返回内容不是 JSON：{e}") from e
        if "observations" not in doc:
            raise FetchError(f"FRED API 返回错误：{doc.get('error_message', doc)}")
        rows = [
            (
                series,
                date.fromisoformat(o["date"]),
                str(o.get("value", "")).strip(),
                date.fromisoformat(o["realtime_start"]),
                f"alfred:{o['realtime_start']}",
            )
            for o in doc["observations"]
        ]
        staging = pd.DataFrame(rows, columns=STAGING_COLUMNS) if rows else empty_staging()
        return ParsedPayload(staging, {series: {"fred_series": series}})
