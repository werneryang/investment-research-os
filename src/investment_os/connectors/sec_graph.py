"""SEC 年报（10-K）Item 5 业绩图的数值表：累计股东总收益指数（基期 = 100，含股息再投资）。

只有把数值表以文字列出的申报可用；只有图片的申报（如 Phillips 66、Marathon Petroleum）不能逐值核对，不登记。
数据集用 params.filings 逐份声明：

    accession    申报编号
    url          原文地址（www.sec.gov/Archives/…）
    accepted_at  EDGAR 接受日期（美东），作为发布时间
    header       表头原文（去标签、空白折叠后逐字出现），如「As of December 31, 2015 2016 … 2020」
    dates        表头各列对应的观测日期（期末），个数即每行数值个数
    rows         序列键 → 行标签原文，如 company: Valero Common Stock、sp500: S&P 500

行标签必须在表头之后、按声明逐字出现，紧跟与日期个数相同的数值（允许美元符号）；第一个值必须是基期 100。
表头、行标签或数值个数不符即报错，不按位置猜测。序列 ID 为「键|申报编号」：各申报的基期不同，不能直接拼接。
"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

import pandas as pd

from ..contracts import DatasetSpec
from .base import STAGING_COLUMNS, FetchError, ParsedPayload, RawPayload, now_utc
from .sec import SecClient

# 表头之后在多长的文字范围内找行标签：数值表紧跟表头，超出范围说明版式不同
_WINDOW = 2000
_NUMBER = r"(?:\$\s*)?(-?\d[\d,]*\.\d+)"


def text_of(content: bytes) -> str:
    """原文去标签、反转义、空白折叠后的文字。"""
    t = re.sub(r"<[^>]+>", " ", content.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", html.unescape(t).replace("\xa0", " ")).strip()


def _squash(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def extract(text: str, filing: dict[str, Any]) -> dict[str, list[str]]:
    """按声明的表头与行标签取出各行数值（原样字符串）；不符即 FetchError。"""
    header = _squash(filing["header"])
    at = text.find(header)
    if at < 0:
        raise FetchError(f"{filing['accession']} 中找不到表头「{header}」，业绩图版式可能已变化")
    if text.find(header, at + 1) >= 0:
        raise FetchError(f"{filing['accession']} 中表头「{header}」出现不止一次，不能确定数值表")
    window = text[at + len(header): at + len(header) + _WINDOW]
    n = len(filing["dates"])
    out = {}
    for key, label in filing["rows"].items():
        m = re.search(r"(?<![\w&])" + re.escape(_squash(label)) + r"\s+" + r"\s+".join([_NUMBER] * n) + r"(?![\d.])",
                      window)
        if m is None:
            raise FetchError(f"{filing['accession']} 的表头之后找不到行「{label}」及 {n} 个数值")
        values = [g.replace(",", "") for g in m.groups()]
        if float(values[0]) != 100.0:
            raise FetchError(f"{filing['accession']} 的行「{label}」第一个值为 {values[0]}，不是基期 100")
        out[key] = values
    return out


class SecPerformanceGraphConnector:
    """10-K 业绩图数值表；每份申报一个原始快照。"""

    name = "sec_performance_graph"

    def __init__(self, client: SecClient | None = None, **retry: Any) -> None:
        self.client = client or SecClient(**retry)

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        filings = dataset.params.get("filings")
        if not filings:
            raise ValueError(f"数据集 {dataset.id} 未在 params.filings 中声明申报")
        out = []
        for f in filings:
            content = self.client.get(f["url"])
            if b"<html" not in content[:5000].lower():
                raise FetchError(f"{f['url']} 返回的不是 HTML 原文")
            out.append(RawPayload(content=content, url=f["url"], request={"accession": f["accession"]},
                                  retrieved_at=now_utc(), extension="htm"))
        return out

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        filing = next((f for f in dataset.params["filings"] if f["accession"] == payload.request["accession"]), None)
        if filing is None:
            raise FetchError(f"原始快照的申报 {payload.request['accession']} 未在数据集中声明")
        values = extract(text_of(payload.content), filing)
        dates = [date.fromisoformat(str(d)) for d in filing["dates"]]
        published = date.fromisoformat(str(filing["accepted_at"]))
        rows, series = [], {}
        for key, raw in values.items():
            sid = f"{key}|{filing['accession']}"
            rows += [(sid, d, v, published, None) for d, v in zip(dates, raw)]
            series[sid] = {"accession": filing["accession"], "url": filing["url"], "row": key,
                           "label": _squash(filing["rows"][key]), "header": _squash(filing["header"]),
                           "base_date": dates[0].isoformat(), "accepted_at": published.isoformat()}
        return ParsedPayload(pd.DataFrame(rows, columns=STAGING_COLUMNS), series)
