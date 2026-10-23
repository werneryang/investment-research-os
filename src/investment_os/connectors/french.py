"""Kenneth R. French Data Library 接入：因子与组合收益（zip 内的 CSV，只有当前版本）。

每个文件是一个 zip，内含一个 CSV，CSV 里依次有多段表格：例如因子文件先是月度表、再是年度表；
行业组合文件有价值加权与等权的月度、年度收益，以及公司数、平均规模等。数据集用 params 指明：

    file      文件名（不含 _CSV.zip），如 F-F_Research_Data_Factors
    section   表格标题（表头行之前的那一行文字）；不写表示文件中的第一段
    columns   预期的列名，与表头逐一核对，文件版式变化时报错而不是读错表
    prefix    序列 ID 前缀，序列 ID 为 前缀 + 列名

缺失值在文件中写作 -99.99 或 -999，解析时转为空值；-99.99 看起来像一个合法收益，不能交给取值范围判断。
"""

from __future__ import annotations

import io
import re
import zipfile
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

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
MISSING = {"-99.99", "-999"}
# 各频率对应的日期格式：月度 YYYYMM，年度 YYYY，日度 YYYYMMDD
DATE_DIGITS = {"monthly": 6, "annual": 4, "daily": 8}
_ROW = re.compile(r"^\s*(\d{4,8})\s*,")
_CRSP = re.compile(r"created (?:by .+ )?using the (\d{6}) CRSP database")


def _param(dataset: DatasetSpec, key: str) -> Any:
    value = dataset.params.get(key)
    if not value:
        raise ValueError(f"数据集 {dataset.id} 未在 params.{key} 中声明")
    return value


def _sections(lines: list[str]) -> list[tuple[str, list[str], list[list[str]]]]:
    """拆出 (标题, 表头列名, 数据行)。标题是表头行之前最近的一行非空文字。"""
    out: list[tuple[str, list[str], list[list[str]]]] = []
    title, current = "", None
    for raw in lines:
        line = raw.strip()
        if not line:
            current = None
            continue
        if line.startswith(","):  # 表头行：首格为空
            current = (title, [c.strip() for c in line.split(",")[1:]], [])
            out.append(current)
        elif _ROW.match(line):
            if current is not None:
                current[2].append([c.strip() for c in line.split(",")])
        else:
            title, current = line, None
    return out


def _observation(text: str, frequency: str) -> date:
    if frequency == "monthly":
        return date(int(text[:4]), int(text[4:6]), 1)
    if frequency == "annual":
        return date(int(text), 1, 1)
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


class FrenchLibraryConnector:
    """French Data Library 的 zip/CSV；只返回当前版本（数据会随 CRSP 更新与方法调整整体重算）。"""

    name = "french_csv"

    def __init__(self, http_get: HttpGet = urllib_get, **retry: Any) -> None:
        self.http_get = http_get
        self.retry = retry

    def fetch(self, dataset: DatasetSpec, request: dict[str, Any]) -> list[RawPayload]:
        file = _param(dataset, "file")
        url = f"{BASE_URL}/{file}_CSV.zip"
        content = fetch_with_retry(url, self.http_get, **self.retry)
        if not content.startswith(b"PK"):
            raise FetchError(f"{url} 返回的不是 zip 文件（可能是错误页）")
        return [RawPayload(content=content, url=url, request={"file": file}, retrieved_at=now_utc(),
                           extension="zip")]

    def parse(self, dataset: DatasetSpec, payload: RawPayload) -> ParsedPayload:
        columns = list(_param(dataset, "columns"))
        prefix = dataset.params.get("prefix", "")
        wanted = dataset.params.get("section")
        digits = DATE_DIGITS.get(dataset.frequency)
        if digits is None:
            raise ValueError(f"数据集 {dataset.id} 的频率 {dataset.frequency} 不受 French 接入器支持")
        try:
            with zipfile.ZipFile(io.BytesIO(payload.content)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if len(names) != 1:
                    raise FetchError(f"zip 中应只有一个 CSV，实际为 {names}")
                text = zf.read(names[0]).decode("latin-1")
        except zipfile.BadZipFile as e:
            raise FetchError(f"zip 无法读取：{e}") from None
        lines = text.replace("\r", "").split("\n")
        sections = _sections(lines)
        if wanted:
            matches = [s for s in sections if s[0] == wanted]
            if len(matches) != 1:
                raise FetchError(f"找到 {len(matches)} 段标题为「{wanted}」的表格；"
                                 f"文件中的标题：{[s[0] for s in sections]}")
            section = matches[0]
        elif sections:
            section = sections[0]
        else:
            raise FetchError("文件中没有表格")
        title, header, data = section
        if header != columns:
            raise FetchError(f"表头 {header} 与登记的列 {columns} 不一致")
        crsp = next((m.group(1) for m in map(_CRSP.search, lines[:3]) if m), None)
        rows = []
        for r in data:
            if len(r[0]) != digits:
                raise FetchError(f"「{title or '第一段'}」中的日期 {r[0]} 与频率 {dataset.frequency} 不符")
            if len(r) != len(columns) + 1:
                raise FetchError(f"{r[0]} 行有 {len(r) - 1} 个值，预期 {len(columns)} 个")
            obs = _observation(r[0], dataset.frequency)
            for col, value in zip(columns, r[1:]):
                rows.append((f"{prefix}{col}", obs, "" if value in MISSING else value, None, None))
        staging = pd.DataFrame(rows, columns=STAGING_COLUMNS) if rows else empty_staging()
        # 第一段没有标题，表头前一行是文件说明，不记作标题
        meta = {"french_file": dataset.params["file"], "section": wanted or "（第一段）", "crsp_database": crsp}
        return ParsedPayload(staging, {f"{prefix}{c}": {**meta, "column": c} for c in columns})
