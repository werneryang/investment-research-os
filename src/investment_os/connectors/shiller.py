"""Robert J. Shiller 美国股市月度数据（ie_data.xls）接入：只有当前版本。

文件托管在带版本号的地址上，地址随更新变化，所以每次先读 shillerdata.com 页面找到 ie_data.xls 的链接，
再下载文件；页面上必须恰好有一个这样的链接，否则报错。

工作表「Data」的表头分散在几行里，最后一行（首列为 Date，即第 8 行）是各列的短名称；同一名称会重复出现
（如两个 Price、两个 Earnings），所以每个序列按列位置登记，并与该位置的短名称逐字核对：

    columns   序列代码 → {col: 列位置（0 起）, label: 第 8 行的短名称}

日期写成小数「年.月」：2026.01 是 1 月，2026.1 是 10 月（Excel 中两者都是浮点数），按 round((x − 年) × 100)
取月份；再用表中的 Date Fraction 列（年 + (月 − 0.5) / 12）逐行核对，并要求月份连续。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pandas as pd
import xlrd

from ..contracts import DatasetSpec
from .base import (
    STAGING_COLUMNS,
    FetchError,
    HttpGet,
    ParsedPayload,
    RawPayload,
    fetch_with_retry,
    now_utc,
    urllib_get,
)

PAGE_URL = "https://shillerdata.com/"
_LINK = re.compile(r"(?:https:)?//img1\.wsimg\.com/[^\"'\s<>]*/ie_data\.xls[^\"'\s<>]*")
SHEET = "Data"
FRACTION_COL = 5  # Date Fraction：年 + (月 − 0.5) / 12


def year_month(value: float) -> tuple[int, int]:
    """2026.01 → (2026, 1)；2026.1 → (2026, 10)；2026.12 → (2026, 12)。"""
    year = int(value)
    month = round((value - year) * 100)
    if not 1 <= month <= 12:
        raise FetchError(f"日期 {value!r} 的月份 {month} 不在 1–12 之间")
    return year, month


class ShillerXlsConnector:
    """shillerdata.com 的 ie_data.xls；只支持月度数据。"""

    name = "shiller_xls"

    def __init__(self, http_get: HttpGet = urllib_get, **retry: Any) -> None:
        self.http_get = http_get
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        page = fetch_with_retry(PAGE_URL, self.http_get, **self.retry).decode("utf-8", "replace")
        links = sorted(set(_LINK.findall(page)))
        if len(links) != 1:
            raise FetchError(f"{PAGE_URL} 上应恰有一个 ie_data.xls 链接，实际找到 {len(links)} 个")
        url = links[0] if links[0].startswith("https:") else f"https:{links[0]}"
        content = fetch_with_retry(url, self.http_get, **self.retry)
        if not content.startswith(b"\xd0\xcf\x11\xe0"):
            raise FetchError(f"{url} 返回的不是 .xls 文件（可能是错误页）")
        return [RawPayload(content=content, url=url, request={"page": PAGE_URL}, retrieved_at=now_utc(),
                           extension="xls")]

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        if dataset.frequency != "monthly":
            raise ValueError(f"数据集 {dataset.id} 的频率 {dataset.frequency} 不受 Shiller 接入器支持")
        columns: dict[str, dict[str, Any]] = dict(dataset.params.get("columns") or {})
        if not columns:
            raise ValueError(f"数据集 {dataset.id} 未在 params.columns 中声明")
        prefix = dataset.params.get("prefix", "")
        try:
            sheet = xlrd.open_workbook(file_contents=payload.content).sheet_by_name(SHEET)
        except xlrd.XLRDError as e:
            raise FetchError(f"无法读取工作表「{SHEET}」：{e}") from None
        header = next((r for r in range(sheet.nrows) if str(sheet.cell_value(r, 0)).strip() == "Date"), None)
        if header is None:
            raise FetchError(f"工作表「{SHEET}」中找不到首列为 Date 的表头行")
        labels = [str(sheet.cell_value(header, c)).strip() for c in range(sheet.ncols)]
        for code, spec in {**columns, "_fraction": {"col": FRACTION_COL, "label": "Fraction"}}.items():
            col, label = int(spec["col"]), spec["label"]
            found = labels[col] if col < len(labels) else None
            if found != label:
                raise FetchError(f"第 {header + 1} 行第 {col} 列应为「{label}」（{code}），实际为「{found}」")
        rows, previous = [], None
        for r in range(header + 1, sheet.nrows):
            cell = sheet.cell_value(r, 0)
            if not isinstance(cell, float):
                break
            year, month = year_month(cell)
            fraction = sheet.cell_value(r, FRACTION_COL)
            if not isinstance(fraction, float) or abs(fraction - (year + (month - 0.5) / 12)) > 0.001:
                raise FetchError(f"日期 {cell!r} 解析为 {year}-{month:02d}，与 Date Fraction {fraction!r} 不符")
            current = year * 12 + month
            if previous is not None and current != previous + 1:
                raise FetchError(f"{year}-{month:02d} 与上一行不连续")
            previous = current
            obs = date(year, month, 1)
            for code, spec in columns.items():
                value = sheet.cell_value(r, int(spec["col"]))
                raw = repr(float(value)) if isinstance(value, float) else ""  # 'NA' 与空单元格为缺失
                rows.append((f"{prefix}{code}", obs, raw, None, None))
        if not rows:
            raise FetchError(f"工作表「{SHEET}」的表头下没有数据")
        meta = {"shiller_url": payload.url, "sheet": SHEET}
        return ParsedPayload(pd.DataFrame(rows, columns=STAGING_COLUMNS),
                             {f"{prefix}{c}": {**meta, "column": s["label"], "col": int(s["col"])}
                              for c, s in columns.items()})
