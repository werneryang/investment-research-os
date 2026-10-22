"""资源接入的公共接口（模块 D）。

接入器只负责取得原始字节与解析为暂存表；数值转换、时间规则、
质量检查与版本化统一在 data.normalize 中完成，保证各来源行为一致。
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import pandas as pd

from ..contracts import DatasetSpec

USER_AGENT = "investment-research-os/0.1 (personal research; contact via project owner)"

# 暂存表的列：原始值保持字符串，由标准化步骤统一判定缺失与异常
STAGING_COLUMNS = ["series_id", "observation_at", "raw_value", "published_at", "vintage_label"]

HttpGet = Callable[[str, float], bytes]


class FetchError(RuntimeError):
    """取得失败。调用方保留旧版本并记录，不生成虚假的更新。"""


def urllib_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 登记的 https 来源
        return resp.read()


def fetch_with_retry(
    url: str,
    http_get: HttpGet = urllib_get,
    *,
    attempts: int = 3,
    timeout: float = 60.0,
    backoff: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """有界重试；最终失败抛出 FetchError。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return http_get(url, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if i < attempts - 1:
                sleep(backoff * (2**i))
    raise FetchError(f"{attempts} 次尝试后仍无法取得 {url}：{last}")


@dataclass
class RawPayload:
    """一次取得的原始资料；原样保存为快照。"""

    content: bytes
    url: str
    request: dict[str, Any]
    retrieved_at: datetime
    extension: str = "csv"


@dataclass
class ParsedPayload:
    staging: pd.DataFrame
    series: dict[str, dict[str, Any]] = field(default_factory=dict)


class Connector(Protocol):
    name: str

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]: ...

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload: ...


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def empty_staging() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in STAGING_COLUMNS})
