"""FRED 接入：图表 CSV 导出（无 key，仅当前版本）、API 当前版本（需 key）与 API 历史版本（需 key）。

2026-11-06 起 fred.stlouisfed.org 的图表导出不再响应本项目的请求（读取超时），定时取得的
当前版本序列改走官方 API（fred_api_current）。图表导出接入器保留，供已有记录复查与降级。
"""

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


def _api_key(explicit: str | None, fallback_hint: str) -> str:
    key = explicit or os.environ.get("FRED_API_KEY")
    if not key:
        raise FetchError(f"未设置 FRED_API_KEY；{fallback_hint}")
    return key


def _fetch_api_pages(http_get: HttpGet, retry: dict[str, Any], base: dict[str, str], key: str,
                     max_pages: int) -> list[RawPayload]:
    """按 offset 逐页取得 series/observations，核对总数与 count 一致；不完整时失败。

    key 只用于请求：快照与记录里的 URL、错误消息都不含 key。
    """
    payloads: list[RawPayload] = []
    received = 0
    expected: int | None = None
    for _ in range(max_pages):
        query = {**base, "offset": str(received)}
        public_url = f"{API_URL}?{urllib.parse.urlencode(query)}"
        url = f"{API_URL}?{urllib.parse.urlencode({**query, 'api_key': key})}"
        try:
            content = fetch_with_retry(url, http_get, display_url=public_url, **retry)
        except FetchError as e:
            raise FetchError(str(e).replace(key, "***")) from None
        page = _api_page(content)
        count = int(page.get("count", -1))
        if expected is None:
            expected = count
        elif count != expected:
            raise FetchError(f"分页过程中 count 由 {expected} 变为 {count}，结果可能不一致")
        n = len(page["observations"])
        payloads.append(RawPayload(content=content, url=public_url, request=query,
                                   retrieved_at=now_utc(), extension="json"))
        received += n
        if expected < 0:
            raise FetchError("FRED API 返回缺少 count，无法核对完整性")
        if received >= expected:
            break
        if n == 0:
            raise FetchError(f"只取得 {received}/{expected} 条后返回空页，结果不完整")
    else:
        raise FetchError(f"超过 {max_pages} 页仍未取完（{received}/{expected}）")
    if received != expected:
        raise FetchError(f"取得 {received} 条，与 count={expected} 不一致")
    return payloads


class FredApiCurrentConnector:
    """FRED API series/observations，不带 realtime 参数：只返回当前修订版本，与图表导出同口径。

    需要环境变量 FRED_API_KEY。版本由本系统按取得时间记为本地快照（vintages: local），
    不把当前值当作历史上当时公布的值。
    """

    name = "fred_api_current"
    PAGE_LIMIT = 100_000  # 官方上限
    MAX_PAGES = 1_000

    def __init__(self, http_get: HttpGet = urllib_get, api_key: str | None = None,
                 page_limit: int | None = None, **retry: Any) -> None:
        self.http_get = http_get
        self.api_key = api_key
        self.page_limit = page_limit or self.PAGE_LIMIT
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        key = _api_key(self.api_key, "当前版本序列需要 key；本机写在 .env，CI 用仓库 secret")
        base = {"series_id": _series_of(dataset), "file_type": "json", "limit": str(self.page_limit)}
        if request.get("start"):
            base["observation_start"] = str(request["start"])
        if request.get("end"):
            base["observation_end"] = str(request["end"])
        return _fetch_api_pages(self.http_get, self.retry, base, key, self.MAX_PAGES)

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        series = _series_of(dataset)
        doc = _api_page(payload.content)
        rows = [
            (series, date.fromisoformat(o["date"]), str(o.get("value", "")).strip(), None, None)
            for o in doc["observations"]
        ]
        staging = pd.DataFrame(rows, columns=STAGING_COLUMNS) if rows else empty_staging()
        return ParsedPayload(staging, {series: {"fred_series": series}})


class FredApiVintagesConnector:
    """FRED API（ALFRED）：取得全部历史版本，realtime_start 作为该版本的发布日期。

    需要环境变量 FRED_API_KEY。key 只用于请求，不写入快照、日志或错误消息。
    API 单次最多返回 ``limit`` 条，按 offset 逐页取得，并核对总数与 count 一致；
    无法取得完整结果时失败，不把截断的数据称为「全部历史版本」。
    """

    name = "fred_api_vintages"
    PAGE_LIMIT = 100_000  # 官方上限
    MAX_PAGES = 1_000

    def __init__(self, http_get: HttpGet = urllib_get, api_key: str | None = None,
                 page_limit: int | None = None, **retry: Any) -> None:
        self.http_get = http_get
        self.api_key = api_key
        self.page_limit = page_limit or self.PAGE_LIMIT
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        key = _api_key(self.api_key, "可改用无需 key 的 fred_graph 数据集（仅当前版本）")
        base = {
            "series_id": _series_of(dataset),
            "file_type": "json",
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "limit": str(self.page_limit),
        }
        if request.get("start"):
            base["observation_start"] = str(request["start"])
        if request.get("end"):
            base["observation_end"] = str(request["end"])
        return _fetch_api_pages(self.http_get, self.retry, base, key, self.MAX_PAGES)

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        series = _series_of(dataset)
        doc = _api_page(payload.content)
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


def _api_page(content: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise FetchError(f"FRED API 返回内容不是 JSON：{e}") from e
    if "observations" not in doc:
        raise FetchError(f"FRED API 返回错误：{doc.get('error_message', '未知错误')}")
    return doc
