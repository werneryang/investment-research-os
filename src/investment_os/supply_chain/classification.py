"""L1 官方行业分类：NAICS 2022 结构表（Census XLSX）的取得、解析与本地版本（classification.v1）。

布局（<root>/data/classification 下，默认不提交 Git）：
    raw/<system>-<version>_<sha8>.xlsx     原始文件，内容相同不另存
    <system>-<version>.parquet             当前解析结果
    catalog.jsonl                          每次导入：原始文件校验值、行数、取得方式与时间

只保存来源自身的代码、名称与层级；不推定公司映射或权重。标题末尾的「T」是 Census 的三国共同代码标记，
拆为 trilateral 字段，名称本身不改写。
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..connectors.base import FetchError, HttpGet, fetch_with_retry, now_utc, urllib_get
from ..contracts import CLASSIFICATION_COLUMNS, CLASSIFICATION_SCHEMA_VERSION
from ..data.store import compact, sha256_bytes

NAICS_2022_URL = "https://www.census.gov/naics/2022NAICS/2022_NAICS_Structure.xlsx"
XLSX_MAGIC = b"PK\x03\x04"
_TRILATERAL = re.compile(r"^(.*[a-z)\],])T\s*$")
_SECTOR_RANGE = re.compile(r"^(\d{2})-(\d{2})$")


def parse_naics_structure(content: bytes, version: str = "2022") -> pd.DataFrame:
    """结构表 → 每个代码一行；表头、层级或父代码不符时报错，不猜测。"""
    if not content.startswith(XLSX_MAGIC):
        raise FetchError("NAICS 结构表不是 .xlsx 文件（可能是错误页）")
    try:
        raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str)
    except (ValueError, KeyError) as e:
        raise FetchError(f"NAICS 结构表无法读取：{e}") from None
    header = next((i for i in range(min(len(raw), 10))
                   if str(raw.iat[i, 1]).strip() == f"{version} NAICS Code"), None)
    if header is None or str(raw.iat[header, 2]).strip() != f"{version} NAICS Title":
        raise FetchError(f"找不到「{version} NAICS Code / Title」表头，版式可能已变化")
    rows = []
    for _, r in raw.iloc[header + 1:].iterrows():
        code = str(r[1]).strip() if pd.notna(r[1]) else ""
        if not code:
            continue
        title = str(r[2]).strip() if pd.notna(r[2]) else ""
        m = _TRILATERAL.match(title)
        trilateral = bool(m)
        if m:
            title = m.group(1).rstrip()
        rng = _SECTOR_RANGE.match(code)
        if rng:
            level = 2
        elif code.isdigit() and 2 <= len(code) <= 6:
            level = len(code)
        else:
            raise FetchError(f"无法识别的 NAICS 代码：{code!r}")
        indicator = str(r[0]).strip() if pd.notna(r[0]) else ""
        rows.append({"system": "NAICS", "version": version, "code": code, "title": title, "level": level,
                     "parent": None, "trilateral": trilateral, "change_indicator": indicator})
    df = pd.DataFrame(rows, columns=CLASSIFICATION_COLUMNS)
    if df.empty:
        raise FetchError("NAICS 结构表的表头下没有代码")
    if df["code"].duplicated().any():
        raise FetchError(f"NAICS 代码重复：{sorted(df.loc[df['code'].duplicated(), 'code'])[:5]}")
    # 二位层可能是区间（31-33）；三位代码的父代码是包含其前两位的部门
    sectors: dict[str, str] = {}
    for code in df.loc[df["level"] == 2, "code"]:
        rng = _SECTOR_RANGE.match(code)
        lo, hi = (int(rng.group(1)), int(rng.group(2))) if rng else (int(code), int(code))
        for n in range(lo, hi + 1):
            sectors[f"{n:02d}"] = code
    codes = set(df["code"])
    parents = []
    for code, level in zip(df["code"], df["level"]):
        parent = None if level == 2 else (sectors.get(code[:2]) if level == 3 else code[:-1])
        if level > 2 and parent not in codes:
            raise FetchError(f"NAICS {code} 的上级 {parent} 不在表中")
        parents.append(parent)
    df["parent"] = parents
    return df


class ClassificationStore:
    def __init__(self, root: Path) -> None:
        self.base = Path(root) / "data" / "classification"

    def _table(self, system: str, version: str) -> Path:
        return self.base / f"{system.lower()}-{version}.parquet"

    def entries(self) -> list[dict[str, Any]]:
        path = self.base / "catalog.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x] if path.exists() else []

    def save(self, system: str, version: str, content: bytes, df: pd.DataFrame, origin: dict[str, Any],
             created_at: datetime) -> dict[str, Any]:
        digest = sha256_bytes(content)
        raw_dir = self.base / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw = raw_dir / f"{system.lower()}-{version}_{digest[:8]}.xlsx"
        if not raw.exists():
            raw.write_bytes(content)
        df[CLASSIFICATION_COLUMNS].to_parquet(self._table(system, version), index=False)
        entry = {"system": system, "version": version, "schema_version": CLASSIFICATION_SCHEMA_VERSION,
                 "version_id": f"v{compact(created_at)}-{digest[:8]}", "raw": str(raw.relative_to(self.base)),
                 "sha256": digest, "bytes": len(content), "rows": len(df),
                 "levels": {str(k): int(v) for k, v in df["level"].value_counts().sort_index().items()},
                 "created_at": created_at.isoformat(), **origin}
        with (self.base / "catalog.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def load(self, system: str = "NAICS", version: str = "2022") -> pd.DataFrame | None:
        path = self._table(system, version)
        return pd.read_parquet(path) if path.exists() else None


def import_naics(root: Path, path: Path | None = None, http_get: HttpGet = urllib_get,
                 clock=now_utc, **retry: Any) -> dict[str, Any]:
    """下载（或从本地文件导入）NAICS 2022 结构表，解析并保存一个版本。"""
    retrieved = clock()
    if path is not None:
        content = Path(path).read_bytes()
        origin = {"origin": "local_file", "path": str(path), "url": NAICS_2022_URL}
    else:
        content = fetch_with_retry(NAICS_2022_URL, http_get, **retry)
        origin = {"origin": "download", "url": NAICS_2022_URL, "retrieved_at": retrieved.isoformat()}
    df = parse_naics_structure(content)
    return ClassificationStore(root).save("NAICS", "2022", content, df, origin, retrieved)
