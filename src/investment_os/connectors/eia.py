"""EIA 石油数据浏览器（dnav/pet）的 .xls 文件下载，无需 key；只有当前修订版本。

工作表结构：第 1 行「Back to Contents」，第 2 行「Sourcekey」及各列序列代码，第 3 行「Date」及各列标题，
其下逐行为 Excel 日期序号与数值。数据集用 params 指明：

    file      文件名，如 PET_PNP_WIUP_DCU_NUS_W.xls（位于 dnav/pet/xls/）
    sheet     工作表名称
    series    序列代码 → 列标题（逐字核对，空白折叠；标题含单位，定义或单位变化时报错）

按 Sourcekey 定位列，不按列位置。数值原样保留，空单元格为缺失。
"""

from __future__ import annotations

import re
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

BASE_URL = "https://www.eia.gov/dnav/pet/xls"
XLS_MAGIC = b"\xd0\xcf\x11\xe0"


def _param(dataset: DatasetSpec, key: str) -> Any:
    value = dataset.params.get(key)
    if not value:
        raise ValueError(f"数据集 {dataset.id} 未在 params.{key} 中声明")
    return value


def _squash(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


class EiaPetXlsConnector:
    """EIA 石油数据浏览器的 .xls 序列表。"""

    name = "eia_pet_xls"

    def __init__(self, http_get: HttpGet = urllib_get, **retry: Any) -> None:
        self.http_get = http_get
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        file = _param(dataset, "file")
        url = f"{BASE_URL}/{file}"
        content = fetch_with_retry(url, self.http_get, **self.retry)
        # 旧版 Excel 以 OLE 复合文档签名开头；错误页（HTML）会在这里被拒绝
        if not content.startswith(XLS_MAGIC):
            raise FetchError(f"{url} 返回的不是 .xls 文件（可能是错误页）")
        return [RawPayload(content=content, url=url, request={"file": file}, retrieved_at=now_utc(),
                           extension="xls")]

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        sheet_name = _param(dataset, "sheet")
        wanted: dict[str, str] = dict(_param(dataset, "series"))
        try:
            book = xlrd.open_workbook(file_contents=payload.content)
        except xlrd.XLRDError as e:
            raise FetchError(f".xls 无法读取：{e}") from None
        try:
            sheet = book.sheet_by_name(sheet_name)
        except xlrd.XLRDError:
            raise FetchError(f"找不到工作表「{sheet_name}」；现有：{book.sheet_names()}") from None
        if sheet.nrows < 3 or _squash(sheet.cell_value(1, 0)) != "Sourcekey" \
                or _squash(sheet.cell_value(2, 0)) != "Date":
            raise FetchError(f"工作表「{sheet_name}」的第 2、3 行不是 Sourcekey / Date 表头，版式可能已变化")
        keys = [_squash(sheet.cell_value(1, c)) for c in range(sheet.ncols)]
        positions: dict[str, int] = {}
        for code, title in wanted.items():
            if code not in keys:
                raise FetchError(f"Sourcekey 行中找不到 {code}；现有：{keys[1:]}")
            c = keys.index(code)
            actual = _squash(sheet.cell_value(2, c))
            if actual != _squash(title):
                raise FetchError(f"{code} 的列标题为「{actual}」，与登记的「{_squash(title)}」不一致")
            positions[code] = c
        rows = []
        for r in range(3, sheet.nrows):
            stamp = sheet.cell_value(r, 0)
            if stamp in ("", None):
                continue
            if not isinstance(stamp, float):
                raise FetchError(f"第 {r + 1} 行的日期单元格不是 Excel 日期：{stamp!r}")
            obs = xlrd.xldate_as_datetime(stamp, book.datemode).date()
            for code, c in positions.items():
                value = sheet.cell_value(r, c)
                raw = repr(float(value)) if isinstance(value, float) else str(value).strip()
                rows.append((code, obs, raw, None, None))
        if not rows:
            raise FetchError(f"工作表「{sheet_name}」的表头下没有数据")
        meta = {"eia_file": dataset.params["file"], "sheet": sheet_name}
        return ParsedPayload(pd.DataFrame(rows, columns=STAGING_COLUMNS),
                             {code: {**meta, "sourcekey": code, "column": _squash(title)}
                              for code, title in wanted.items()})
