"""SEC EDGAR 接入：Financial Statement Data Sets（FSDS，季度 ZIP）与 Company Facts API（docs/edgar-design.md）。

访问规则：
- www.sec.gov 上的文件（FSDS）要求 User-Agent 写明联系邮箱：取自环境变量 SEC_USER_AGENT（项目根目录的 .env），
  未设置时拒绝取得并说明原因；data.sec.gov 有它时也用它。值不写进日志或快照。
- 串行请求，间隔不少于 0.2 秒（SEC 上限为每秒 10 次）。

解析只保留登记公司的定期报告（10-K、10-Q、20-F 等及其修正），不含员工持股计划报告（11-K）等；
财报事实只保留合并口径（无分部、无共同申报人）。FSDS 的数值表每个季度约 900 MB，逐行流式过滤，不整表载入。
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from typing import Any, Callable

import pandas as pd

from ..contracts import FACT_COLUMNS, FILING_COLUMNS, SEGMENT_FACT_COLUMNS
from .base import FetchError, fetch_with_retry

FSDS_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
MIN_INTERVAL = 0.2
TZ = "America/New_York"
# 定期报告；员工持股计划（11-K）等其他表格的数字不是公司财报
PERIODIC_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}

csv.field_size_limit(10_000_000)  # tag.txt 等文件中有很长的说明文字


class SecClient:
    """带联系标识与限速的 SEC 请求。get/head 可替换，供离线测试使用。"""

    def __init__(self, user_agent: str | None = None, get: Callable[[str, dict[str, str], float], bytes] | None = None,
                 head: Callable[[str, dict[str, str], float], dict[str, Any] | None] | None = None,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic,
                 **retry: Any) -> None:
        self.user_agent = user_agent if user_agent is not None else os.environ.get("SEC_USER_AGENT", "")
        self._get, self._head = get or _urllib_get, head or _urllib_head
        self.sleep, self.monotonic, self.retry = sleep, monotonic, retry
        self._last = None

    def _headers(self, url: str) -> dict[str, str]:
        if not self.user_agent:
            if "www.sec.gov" in url:
                raise FetchError("未设置 SEC_USER_AGENT：www.sec.gov 要求在请求标识中写明联系邮箱"
                                 "（在项目根目录的 .env 中设置，如 SEC_USER_AGENT=项目名 邮箱）")
            from .base import USER_AGENT
            return {"User-Agent": USER_AGENT}
        return {"User-Agent": self.user_agent}

    def _wait(self) -> None:
        now = self.monotonic()
        if self._last is not None and now - self._last < MIN_INTERVAL:
            self.sleep(MIN_INTERVAL - (now - self._last))
        self._last = self.monotonic()

    def get(self, url: str) -> bytes:
        headers = self._headers(url)

        def http_get(u: str, timeout: float) -> bytes:
            self._wait()
            return self._get(u, headers, timeout)
        return fetch_with_retry(url, http_get, **self.retry)

    def head(self, url: str) -> dict[str, Any] | None:
        """文件大小与修改时间；文件不存在（如当季尚未发布）返回 None。"""
        headers = self._headers(url)
        self._wait()
        return self._head(url, headers, 60.0)


def _urllib_get(url: str, headers: dict[str, str], timeout: float) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def _urllib_head(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            size = resp.headers.get("Content-Length")
            return {"size": int(size) if size else None, "last_modified": resp.headers.get("Last-Modified")}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise FetchError(f"HEAD {url} 失败：HTTP {e.code}") from None


def fsds_quarters(today: date, first: str = "2009q1") -> list[str]:
    """从 2009q1 到当前季度的全部季度名（当前季度的文件通常尚未发布）。"""
    year, q = int(first[:4]), int(first[-1])
    out = []
    while (year, q) <= (today.year, (today.month - 1) // 3 + 1):
        out.append(f"{year}q{q}")
        year, q = (year + 1, 1) if q == 4 else (year, q + 1)
    return out


def _yyyymmdd(text: str) -> date | None:
    text = (text or "").strip()
    return date(int(text[:4]), int(text[4:6]), int(text[6:8])) if len(text) == 8 else None


def available_after(moment: pd.Series) -> pd.Series:
    """接受时间（或申报日期）的次日 0 点（美东），转为 UTC。"""
    local = pd.to_datetime(moment)
    if getattr(local.dt, "tz", None) is None:
        local = local.dt.tz_localize(TZ)
    else:
        local = local.dt.tz_convert(TZ)
    return (local.dt.normalize() + pd.Timedelta(days=1)).dt.tz_convert("UTC")


def parse_fsds(content: bytes, ciks: set[int], retrieved_at: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """FSDS 季度 ZIP → (申报表, 财报事实表)，只含登记公司的定期报告与合并口径数字。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise FetchError(f"FSDS 文件不是有效的 zip：{e}") from None
    names = set(zf.namelist())
    if not {"sub.txt", "num.txt"} <= names:
        raise FetchError(f"FSDS zip 缺少 sub.txt 或 num.txt：{sorted(names)}")
    wanted = {str(c) for c in ciks}
    with zf.open("sub.txt") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t")
        missing = {"adsh", "cik", "name", "sic", "fye", "form", "period", "fy", "fp", "filed", "accepted",
                   "prevrpt"} - set(reader.fieldnames or [])
        if missing:
            raise FetchError(f"sub.txt 缺少字段：{sorted(missing)}")
        subs = [s for s in reader if s["cik"] in wanted and s["form"] in PERIODIC_FORMS]
    retrieved = pd.Timestamp(retrieved_at).tz_convert("UTC")
    filings = pd.DataFrame({
        "accession": [s["adsh"] for s in subs],
        "cik": [int(s["cik"]) for s in subs],
        "name": [s["name"] for s in subs],
        "form": [s["form"] for s in subs],
        "fiscal_year": pd.array([int(s["fy"]) if s["fy"] else None for s in subs], dtype="Int64"),
        "fiscal_period": [s["fp"] for s in subs],
        "period_end": pd.to_datetime([_yyyymmdd(s["period"]) for s in subs]),
        "fye": [s["fye"] for s in subs],
        "filed": pd.to_datetime([_yyyymmdd(s["filed"]) for s in subs]),
        # 接受时间为美东时间，形如 2026-08-04 17:40:00.0
        "accepted_at": pd.to_datetime([s["accepted"] for s in subs]).tz_localize(TZ).tz_convert("UTC")
        if subs else pd.Series([], dtype="datetime64[ns, UTC]"),
        "prevrpt": [s["prevrpt"] == "1" for s in subs],
        "sic": [s["sic"] for s in subs],
        "source": "fsds",
        "retrieved_at": retrieved,
    }, columns=FILING_COLUMNS)
    accessions = set(filings["accession"])
    available = dict(zip(filings["accession"], available_after(filings["accepted_at"])))
    rows = []
    with zf.open("num.txt") as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t")
        header = next(reader, [])
        idx = {k: i for i, k in enumerate(header)}
        missing = {"adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value"} - set(idx)
        if missing:
            raise FetchError(f"num.txt 缺少字段：{sorted(missing)}")
        a, t, v, d, q, u, s, c, val = (idx[k] for k in ("adsh", "tag", "version", "ddate", "qtrs", "uom",
                                                          "segments", "coreg", "value"))
        for r in reader:
            if r[a] not in accessions or r[s] or r[c]:
                continue
            version = r[v]
            taxonomy = version.split("/")[0] if "/" in version else "custom"
            rows.append((r[a], r[t], taxonomy, _yyyymmdd(r[d]), int(r[q]), r[u],
                         float(r[val]) if r[val] else None))
    facts = pd.DataFrame(rows, columns=["accession", "tag", "taxonomy", "period_end", "duration_quarters",
                                        "unit", "value"])
    facts["cik"] = facts["accession"].map(dict(zip(filings["accession"], filings["cik"]))).astype("int64")
    facts["period_start"] = pd.NaT
    facts["period_end"] = pd.to_datetime(facts["period_end"])
    facts["available_at"] = facts["accession"].map(available)
    facts["source"], facts["retrieved_at"] = "fsds", retrieved
    return filings, facts[FACT_COLUMNS]


# 分部事实只保留这些维度的组合；权益构成、公允价值层级等其他维度不属于业务或客户结构
SEGMENT_AXES = frozenset({"BusinessSegments", "ProductOrService", "Geographical", "ConsolidationItems",
                          "ConcentrationRiskByBenchmark", "ConcentrationRiskByType", "MajorCustomers"})


def segment_axes(segments: str) -> dict[str, str]:
    """FSDS 的 segments 文本 → {维度: 成员}；空文本为合并口径。"""
    out = {}
    for part in filter(None, (segments or "").split(";")):
        axis, _, member = part.partition("=")
        if not member:
            raise FetchError(f"无法解析的 segments：{segments!r}")
        out[axis] = member
    return out


def parse_fsds_segments(content: bytes, ciks: set[int], retrieved_at: datetime,
                        axes: frozenset[str] = SEGMENT_AXES) -> pd.DataFrame:
    """FSDS 季度 ZIP → 指定公司定期报告中的分部与维度事实（只含 axes 内的维度组合，无共同申报人）。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise FetchError(f"FSDS 文件不是有效的 zip：{e}") from None
    if not {"sub.txt", "num.txt"} <= set(zf.namelist()):
        raise FetchError("FSDS zip 缺少 sub.txt 或 num.txt")
    wanted = {str(c) for c in ciks}
    with zf.open("sub.txt") as f:
        subs = {s["adsh"]: s for s in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                                                      delimiter="\t")
                if s["cik"] in wanted and s["form"] in PERIODIC_FORMS}
    rows = []
    with zf.open("num.txt") as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t")
        idx = {k: i for i, k in enumerate(next(reader, []))}
        missing = {"adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value"} - set(idx)
        if missing:
            raise FetchError(f"num.txt 缺少字段：{sorted(missing)}")
        a, t, v, d, q, u, s, c, val = (idx[k] for k in ("adsh", "tag", "version", "ddate", "qtrs", "uom",
                                                          "segments", "coreg", "value"))
        for r in reader:
            if r[a] not in subs or not r[s] or r[c]:
                continue
            if not set(segment_axes(r[s])) <= axes:
                continue
            version = r[v]
            rows.append((r[a], r[t], version.split("/")[0] if "/" in version else "custom", r[s],
                         _yyyymmdd(r[d]), int(r[q]), r[u], float(r[val]) if r[val] else None))
    facts = pd.DataFrame(rows, columns=["accession", "tag", "taxonomy", "segments", "period_end",
                                        "duration_quarters", "unit", "value"])
    sub = pd.DataFrame([{"accession": k, "cik": int(x["cik"]), "name": x["name"], "form": x["form"],
                         "fiscal_year": int(x["fy"]) if x["fy"] else None, "fiscal_period": x["fp"],
                         "filing_period_end": _yyyymmdd(x["period"]), "accepted": x["accepted"]}
                        for k, x in subs.items()],
                       columns=["accession", "cik", "name", "form", "fiscal_year", "fiscal_period",
                                "filing_period_end", "accepted"])
    facts = facts.merge(sub, on="accession", how="left")
    facts["fiscal_year"] = pd.array(facts["fiscal_year"], dtype="Int64")
    facts["period_end"] = pd.to_datetime(facts["period_end"])
    facts["filing_period_end"] = pd.to_datetime(facts["filing_period_end"])
    facts["accepted_at"] = pd.to_datetime(facts["accepted"]).dt.tz_localize(TZ).dt.tz_convert("UTC") \
        if len(facts) else pd.Series([], dtype="datetime64[ns, UTC]")
    facts["available_at"] = available_after(facts["accepted_at"]) if len(facts) else facts["accepted_at"]
    facts["source"], facts["retrieved_at"] = "fsds", pd.Timestamp(retrieved_at).tz_convert("UTC")
    return facts[SEGMENT_FACT_COLUMNS]


def parse_companyfacts(content: bytes, cik: int, retrieved_at: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Company Facts API 的 JSON → (申报表, 财报事实表)；只有申报日期，没有接受时间。"""
    try:
        doc = json.loads(content)
    except json.JSONDecodeError as e:
        raise FetchError(f"Company Facts 不是有效的 JSON：{e}") from None
    if int(doc.get("cik", -1)) != cik:
        raise FetchError(f"Company Facts 的 CIK 为 {doc.get('cik')}，登记为 {cik}")
    rows, filings = [], {}
    for taxonomy, tags in (doc.get("facts") or {}).items():
        for tag, body in tags.items():
            for unit, items in (body.get("units") or {}).items():
                for x in items:
                    form = x.get("form", "")
                    if form not in PERIODIC_FORMS:
                        continue
                    start = date.fromisoformat(x["start"]) if x.get("start") else None
                    end = date.fromisoformat(x["end"])
                    quarters = round(((end - start).days + 1) / 91.31) if start else 0
                    rows.append((x["accn"], taxonomy, tag, start, end, quarters, unit, float(x["val"]), x["filed"]))
                    filings.setdefault(x["accn"], (form, x.get("fy"), x.get("fp"), x["filed"]))
    retrieved = pd.Timestamp(retrieved_at).tz_convert("UTC")
    facts = pd.DataFrame(rows, columns=["accession", "taxonomy", "tag", "period_start", "period_end",
                                        "duration_quarters", "unit", "value", "filed"])
    facts["cik"] = cik
    facts["period_start"] = pd.to_datetime(facts["period_start"])
    facts["period_end"] = pd.to_datetime(facts["period_end"])
    facts["available_at"] = available_after(pd.to_datetime(facts["filed"]))
    facts["source"], facts["retrieved_at"] = "companyfacts", retrieved
    f = pd.DataFrame([(acc, cik, doc.get("entityName", ""), form, fy, fp, pd.NaT, "", pd.Timestamp(filed),
                       pd.NaT, False, "", "companyfacts", retrieved)
                      for acc, (form, fy, fp, filed) in filings.items()], columns=FILING_COLUMNS)
    f["fiscal_year"] = pd.array(f["fiscal_year"], dtype="Int64")
    f["accepted_at"] = pd.to_datetime(f["accepted_at"], utc=True)
    return f, facts[FACT_COLUMNS]
