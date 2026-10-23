"""Damodaran（NYU Stern）数据接入：旧版 Excel（.xls）中的年度表格，只有当前版本。

表格是人工排版的：说明文字、表头行、逐年数据，之后还有平均值等汇总。数据集用 params 指明：

    file      文件名，如 histretSP.xls（位于 datasets 目录）
    sheet     工作表名称
    columns   序列代码 → 表头文字（逐字核对；同一表头在右侧重复出现时取第一个）
    prefix    序列 ID 前缀

表头行以首列「Year」识别；其下逐行读取，直到首列不再是年份。数值原样保留（年度收益为小数，0.05 即 5%）。
"""

from __future__ import annotations

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
    empty_staging,
    fetch_with_retry,
    now_utc,
    urllib_get,
)

BASE_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets"


def _param(dataset: DatasetSpec, key: str) -> Any:
    value = dataset.params.get(key)
    if not value:
        raise ValueError(f"数据集 {dataset.id} 未在 params.{key} 中声明")
    return value


def _year(value: Any) -> int | None:
    if isinstance(value, float) and value.is_integer() and 1800 <= value <= 2200:
        return int(value)
    return None


class DamodaranXlsConnector:
    """Damodaran 的 .xls 数据表；只支持年度数据。"""

    name = "damodaran_xls"

    def __init__(self, http_get: HttpGet = urllib_get, **retry: Any) -> None:
        self.http_get = http_get
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        file = _param(dataset, "file")
        url = f"{BASE_URL}/{file}"
        content = fetch_with_retry(url, self.http_get, **self.retry)
        # 旧版 Excel 以 OLE 复合文档签名开头；错误页（HTML）会在这里被拒绝
        if not content.startswith(b"\xd0\xcf\x11\xe0"):
            raise FetchError(f"{url} 返回的不是 .xls 文件（可能是错误页）")
        return [RawPayload(content=content, url=url, request={"file": file}, retrieved_at=now_utc(),
                           extension="xls")]

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        if dataset.frequency != "annual":
            raise ValueError(f"数据集 {dataset.id} 的频率 {dataset.frequency} 不受 Damodaran 接入器支持")
        sheet_name = _param(dataset, "sheet")
        columns: dict[str, str] = dict(_param(dataset, "columns"))
        prefix = dataset.params.get("prefix", "")
        try:
            book = xlrd.open_workbook(file_contents=payload.content)
        except xlrd.XLRDError as e:
            raise FetchError(f".xls 无法读取：{e}") from None
        try:
            sheet = book.sheet_by_name(sheet_name)
        except xlrd.XLRDError:
            raise FetchError(f"找不到工作表「{sheet_name}」；现有：{book.sheet_names()}") from None
        header_row = next((r for r in range(sheet.nrows)
                           if str(sheet.cell_value(r, 0)).strip() == "Year"), None)
        if header_row is None:
            raise FetchError(f"工作表「{sheet_name}」中找不到首列为 Year 的表头行")
        header = [str(sheet.cell_value(header_row, c)).strip() for c in range(sheet.ncols)]
        positions: dict[str, int] = {}
        for code, title in columns.items():
            if title not in header:
                raise FetchError(f"表头中找不到「{title}」（{code}）；表头为 {header}")
            positions[code] = header.index(title)
        rows = []
        for r in range(header_row + 1, sheet.nrows):
            year = _year(sheet.cell_value(r, 0))
            if year is None:
                break
            obs = date(year, 1, 1)
            for code, c in positions.items():
                value = sheet.cell_value(r, c)
                raw = repr(float(value)) if isinstance(value, float) else str(value).strip()
                rows.append((f"{prefix}{code}", obs, raw, None, None))
        if not rows:
            raise FetchError(f"工作表「{sheet_name}」的表头下没有年份数据")
        staging = pd.DataFrame(rows, columns=STAGING_COLUMNS) if rows else empty_staging()
        meta = {"damodaran_file": dataset.params["file"], "sheet": sheet_name}
        return ParsedPayload(staging, {f"{prefix}{code}": {**meta, "column": title}
                                       for code, title in columns.items()})
