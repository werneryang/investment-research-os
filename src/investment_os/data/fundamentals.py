"""财报事实的存储、同步与视图（docs/edgar-design.md §3–§5）。

布局（均在 <root>/data/edgar 下，默认不提交 Git）：
    raw/fsds/<季度>_<sha8>.zip                 FSDS 原始文件，内容相同不另存
    raw/companyfacts/<cik>/<时间>_<sha8>.json    Company Facts 原始文件，内容相同不另存
    <表>/source=<来源>/key=<季度或 cik>/part.parquet    当前分区（表为 filings 或 facts）
    superseded/<表>/source=<来源>/key=<…>/<版本>.parquet  被替换的旧分区，保留不删
    catalog/partitions.jsonl                   每个分区的每个版本：校验值、行数、原始文件、登记公司
    catalog/fsds_remote.jsonl                  每次对 FSDS 文件的 HEAD 检查：大小、修改时间、处理结果

一个分区变化只重写该分区；查询用 DuckDB 直接读取当前分区。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

from ..connectors.base import FetchError, now_utc
from ..connectors.sec import (
    COMPANYFACTS_URL,
    FSDS_URL,
    SecClient,
    fsds_quarters,
    parse_companyfacts,
    parse_fsds,
)
from ..contracts import FACT_COLUMNS, FILING_COLUMNS, FUNDAMENTALS_SCHEMA_VERSION, FundamentalsSpec
from .store import compact, sha256_bytes

TABLES = {"filings": FILING_COLUMNS, "facts": FACT_COLUMNS}


def _frame_hash(df: pd.DataFrame, columns: list[str]) -> str:
    """分区内容校验值：不含取得时间，内容相同的再次取得不产生新版本。"""
    canon = df[[c for c in columns if c != "retrieved_at"]].copy()
    canon = canon.astype(str).sort_values(list(canon.columns)).reset_index(drop=True)
    return sha256_bytes(canon.to_csv(index=False).encode("utf-8"))


def companies_hash(spec: FundamentalsSpec) -> str:
    return sha256_bytes(",".join(str(c.cik) for c in sorted(spec.companies, key=lambda c: c.cik)).encode())[:12]


class EdgarStore:
    def __init__(self, root: Path) -> None:
        self.base = Path(root) / "data" / "edgar"

    # ---- 原始文件 -------------------------------------------------------
    def save_raw(self, folder: str, stem: str, content: bytes, extension: str, url: str,
                 retrieved_at: datetime) -> dict[str, Any]:
        digest = sha256_bytes(content)
        target = self.base / "raw" / folder
        target.mkdir(parents=True, exist_ok=True)
        ref = {"sha256": digest, "bytes": len(content), "url": url, "retrieved_at": retrieved_at.isoformat()}
        for existing in sorted(target.glob(f"*_{digest[:8]}.{extension}")):
            if sha256_bytes(existing.read_bytes()) == digest:
                return {"path": str(existing.relative_to(self.base)), **ref, "reused": True}
        path = target / f"{stem}_{digest[:8]}.{extension}"
        path.write_bytes(content)
        return {"path": str(path.relative_to(self.base)), **ref}

    def read_raw(self, ref: dict[str, Any]) -> bytes:
        data = (self.base / ref["path"]).read_bytes()
        if sha256_bytes(data) != ref["sha256"]:
            raise ValueError(f"原始文件校验失败：{ref['path']}")
        return data

    # ---- 目录 -----------------------------------------------------------
    def _log(self, name: str, entry: dict[str, Any]) -> None:
        path = self.base / "catalog" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def _read(self, name: str) -> list[dict[str, Any]]:
        path = self.base / "catalog" / name
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x] if path.exists() else []

    def partitions(self) -> list[dict[str, Any]]:
        return self._read("partitions.jsonl")

    def current(self, table: str, source: str, key: str) -> dict[str, Any] | None:
        entries = [p for p in self.partitions() if (p["table"], p["source"], p["key"]) == (table, source, key)]
        return entries[-1] if entries else None

    def remote_checks(self) -> list[dict[str, Any]]:
        return self._read("fsds_remote.jsonl")

    # ---- 分区 -----------------------------------------------------------
    def _dir(self, table: str, source: str, key: str) -> Path:
        return self.base / table / f"source={source}" / f"key={key}"

    def write_partition(self, table: str, source: str, key: str, df: pd.DataFrame, meta: dict[str, Any],
                        created_at: datetime) -> str:
        """写入一个分区；内容未变返回 unchanged，否则旧分区移到 superseded/ 后写入新版本，返回 created。"""
        columns = TABLES[table]
        digest = _frame_hash(df, columns)
        previous = self.current(table, source, key)
        if previous is not None and previous["content_hash"] == digest and \
                previous.get("companies") == meta.get("companies"):
            return "unchanged"
        folder = self._dir(table, source, key)
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / "part.parquet"
        if previous is not None and part.exists():
            old = self.base / "superseded" / table / f"source={source}" / f"key={key}"
            old.mkdir(parents=True, exist_ok=True)
            part.replace(old / f"{previous['version_id']}.parquet")
        version_id = f"v{compact(created_at)}-{digest[:8]}"
        df[columns].to_parquet(part, index=False)
        self._log("partitions.jsonl", {
            "table": table, "source": source, "key": key, "version_id": version_id,
            "schema_version": FUNDAMENTALS_SCHEMA_VERSION, "content_hash": digest, "rows": len(df),
            "parent_version": previous["version_id"] if previous else None, "created_at": created_at.isoformat(),
            **meta})
        return "created"

    # ---- 查询（DuckDB 读取当前分区） ---------------------------------------
    def query(self, table: str, where: str = "", params: list[Any] | None = None) -> pd.DataFrame:
        files = sorted((self.base / table).glob("source=*/key=*/part.parquet"))
        if not files:
            return pd.DataFrame(columns=TABLES[table])
        sql = f"SELECT {', '.join(TABLES[table])} FROM read_parquet(?)" + (f" WHERE {where}" if where else "")
        with duckdb.connect() as con:
            # 经 Arrow 转为 pandas，避开 DuckDB 自带转换中已弃用的 pandas 用法
            return con.sql(sql, params=[[str(f) for f in files], *(params or [])]).to_arrow_table().to_pandas()


# ---- 同步 ------------------------------------------------------------------

def sync_fsds(root: Path, spec: FundamentalsSpec, client: SecClient, quarters: list[str] | None = None,
              today: date | None = None, clock: Callable[[], datetime] = now_utc,
              progress: Callable[[str], None] = lambda s: None, refresh: bool = False) -> list[dict[str, Any]]:
    """HEAD 检查各季度文件；只下载新出现或大小、修改时间变化的季度；登记公司变化时用已保存的原始文件重新解析。

    HEAD 只能发现大小或修改时间的变化。refresh=True 时不论文件头如何都重新下载（内容相同时去重，不占空间），
    用于偶尔的全面复核。
    """
    store = EdgarStore(root)
    chash = companies_hash(spec)
    ciks = {c.cik for c in spec.companies}
    seen = {}
    for c in store.remote_checks():
        if c.get("remote"):
            seen[c["quarter"]] = c
    results = []
    for q in quarters or fsds_quarters(today or datetime.now(timezone.utc).date()):
        url = FSDS_URL.format(quarter=q)
        remote = client.head(url)
        checked_at = clock()
        entry: dict[str, Any] = {"quarter": q, "checked_at": checked_at.isoformat(), "remote": remote}
        if remote is None:
            entry["action"] = "not_published"
            store._log("fsds_remote.jsonl", entry)
            results.append(entry)
            continue
        last = seen.get(q)
        current = store.current("facts", "fsds", q)
        same_remote = not refresh and last is not None and last.get("remote") == remote and current is not None
        if same_remote and current.get("companies") == chash:
            entry["action"] = "unchanged"
            store._log("fsds_remote.jsonl", entry)
            results.append(entry)
            continue
        try:
            if same_remote:  # 远端未变，只是登记公司变了：用已保存的原始文件重新解析
                ref = current["raw"]
                content = store.read_raw(ref)
                entry["action"] = "reparsed"
            else:
                content = client.get(url)
                ref = store.save_raw("fsds", q, content, "zip", url, checked_at)
                entry["action"] = "downloaded"
            filings, facts = parse_fsds(content, ciks, checked_at)
        except (FetchError, ValueError) as e:
            entry.update(action="failed", error=str(e))
            store._log("fsds_remote.jsonl", entry)
            results.append(entry)
            progress(f"[failed] fsds {q}：{e}")
            continue
        meta = {"raw": ref, "companies": chash}
        entry["filings"] = store.write_partition("filings", "fsds", q, filings, meta, checked_at)
        entry["facts"] = store.write_partition("facts", "fsds", q, facts, meta, checked_at)
        entry["rows"] = {"filings": len(filings), "facts": len(facts)}
        store._log("fsds_remote.jsonl", entry)
        results.append(entry)
        progress(f"[{entry['action']}] fsds {q}：申报 {len(filings)}，事实 {len(facts)}（{entry['facts']}）")
    return results


def sync_companyfacts(root: Path, spec: FundamentalsSpec, client: SecClient,
                      clock: Callable[[], datetime] = now_utc,
                      progress: Callable[[str], None] = lambda s: None) -> list[dict[str, Any]]:
    """逐家取得 Company Facts；内容未变不另存原始文件、不建新分区版本。"""
    store = EdgarStore(root)
    results = []
    for company in spec.companies:
        url = COMPANYFACTS_URL.format(cik=company.cik)
        retrieved = clock()
        entry: dict[str, Any] = {"cik": company.cik, "label": company.label}
        try:
            content = client.get(url)
            ref = store.save_raw(f"companyfacts/{company.cik}", compact(retrieved), content, "json", url, retrieved)
            filings, facts = parse_companyfacts(content, company.cik, retrieved)
        except (FetchError, ValueError) as e:
            entry.update(status="failed", error=str(e))
            results.append(entry)
            progress(f"[failed] companyfacts {company.label}：{e}")
            continue
        meta = {"raw": ref, "companies": None}
        entry["filings"] = store.write_partition("filings", "companyfacts", str(company.cik), filings, meta, retrieved)
        entry["facts"] = store.write_partition("facts", "companyfacts", str(company.cik), facts, meta, retrieved)
        entry["status"] = "ok"
        results.append(entry)
        progress(f"[{entry['facts']}] companyfacts {company.label}：事实 {len(facts)}")
    return results


# ---- 视图 ------------------------------------------------------------------

def period_key(period_end: pd.Series) -> pd.Series:
    """期末日四舍五入到最近的月末：FSDS 的期末日就是这样取整的（API 给出实际日期，如苹果 2024-09-28），
    两个来源按它对应同一期间。15 日及以后取本月末，之前取上月末。"""
    end = pd.to_datetime(period_end)
    this_month = end + pd.offsets.MonthEnd(0)
    prev_month = end - pd.offsets.MonthEnd(1)
    return this_month.where(end.dt.day >= 15, prev_month)


FACT_KEY = ["accession", "taxonomy", "tag", "period_key", "duration_quarters", "unit"]


def _combined(store: EdgarStore, ciks: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """两个来源的申报与事实。同一申报的同一事实两处都有时取 FSDS 的值与可用时间（有精确的接受时间），
    期末日取 API 的实际日期（FSDS 取整到月末）；exact_end 标明期末日是否为实际日期。"""
    marks = ", ".join("?" for _ in ciks)
    facts = store.query("facts", f"cik IN ({marks})", list(ciks))
    filings = store.query("filings", f"cik IN ({marks})", list(ciks))
    facts["period_key"] = period_key(facts["period_end"])
    api = facts[facts["source"] == "companyfacts"].drop_duplicates(FACT_KEY)
    actual = api.set_index(FACT_KEY)["period_end"]
    facts = facts.assign(_rank=(facts["source"] != "fsds").astype(int)).sort_values("_rank")
    facts = facts.drop_duplicates(FACT_KEY, keep="first").drop(columns="_rank")
    exact = facts.set_index(FACT_KEY).index.map(actual.to_dict())
    facts["exact_end"] = (facts["source"] == "companyfacts") | pd.notna(pd.Series(exact, index=facts.index))
    facts["period_end"] = pd.Series(exact, index=facts.index).where(pd.notna(pd.Series(exact, index=facts.index)),
                                                                     facts["period_end"])
    facts["period_end"] = pd.to_datetime(facts["period_end"])
    filings = filings.assign(_rank=(filings["source"] != "fsds").astype(int)).sort_values("_rank")
    filings = filings.drop_duplicates("accession", keep="first").drop(columns="_rank")
    return facts, filings


def annual_metric(root: Path, spec: FundamentalsSpec, metric: str, ciks: list[int] | None = None,
                  as_of: datetime | None = None) -> pd.DataFrame:
    """年度指标：每家公司每个财年取一个值。

    只用年度报告（10-K、10-K/A）中的数字：期间指标取 4 个季度长的期间，时点指标取财年末的余额。
    同一份申报中按别名顺序取第一个出现的科目；同一财年在多份申报中出现时，取（as_of 之前）最新的申报，
    并保留首次公布的值与申报次数，便于看出修订。首次公布的值只在同一科目内取：不同申报换了别名时，
    数值差异来自口径而不是重述，tags_used 大于 1 标出这种情况。
    """
    m = spec.metrics[metric]
    ciks = ciks or [c.cik for c in spec.companies]
    labels = {c.cik: c.label for c in spec.companies}
    facts, filings = _combined(EdgarStore(root), ciks)
    forms = filings.set_index("accession")["form"]
    facts = facts[facts["accession"].map(forms).isin(spec.forms_annual) & (facts["unit"] == m.unit)]
    if as_of is not None:
        facts = facts[facts["available_at"] <= pd.Timestamp(as_of).tz_convert("UTC")]
    # 财年末：年度报告中 4 个季度长的期间的期末
    fy_ends = facts[facts["duration_quarters"] == 4].groupby("cik")["period_key"].agg(set)
    wanted = facts["duration_quarters"] == (4 if m.period == "duration" else 0)
    if m.period == "instant":
        wanted &= pd.Series([pk in fy_ends.get(c, set()) for c, pk in zip(facts["cik"], facts["period_key"])],
                            index=facts.index, dtype=bool)
    order = {t: i for i, t in enumerate(m.tags)}
    cand = facts[wanted].assign(_alias=[order.get((tx, tg)) for tx, tg in zip(facts[wanted]["taxonomy"],
                                                                             facts[wanted]["tag"])])
    cand = cand[cand["_alias"].notna()]
    if cand.empty:
        return pd.DataFrame(columns=["cik", "label", "metric", "fiscal_year_end", "exact_end", "value", "unit",
                                     "tag", "accession", "form", "available_at", "first_value", "filings",
                                     "tags_used"])
    # 每份申报、每个期间取别名顺序最靠前的科目
    cand = cand.sort_values(["cik", "period_key", "accession", "_alias"])
    per_filing = cand.drop_duplicates(["cik", "period_key", "accession"], keep="first")
    per_filing = per_filing.sort_values(["cik", "period_key", "available_at", "accession"])
    grouped = per_filing.groupby(["cik", "period_key"])
    out = grouped.tail(1).copy()
    # 修订只在同一科目内比较：不同申报换了科目（别名）时数值不同，不是重述
    latest_tag = per_filing.groupby(["cik", "period_key"])["tag"].transform("last")
    same_tag = per_filing[per_filing["tag"] == latest_tag].groupby(["cik", "period_key"])
    out = out.merge(same_tag["value"].first().rename("first_value"), left_on=["cik", "period_key"],
                    right_index=True).merge(grouped.size().rename("filings"), left_on=["cik", "period_key"],
                                            right_index=True)
    out = out.merge(grouped["tag"].nunique().rename("tags_used"), left_on=["cik", "period_key"], right_index=True)
    # 期末日：同一财年任何一条记录有实际日期就用它，否则为 FSDS 取整后的月末
    exact = per_filing[per_filing["exact_end"]].groupby(["cik", "period_key"])["period_end"].first()
    out["exact_end"] = [(c, k) in exact.index for c, k in zip(out["cik"], out["period_key"])]
    out["period_end"] = [exact.get((c, k), pe) for c, k, pe in zip(out["cik"], out["period_key"], out["period_end"])]
    out["label"] = out["cik"].map(labels)
    out["metric"] = metric
    out["form"] = out["accession"].map(forms)
    out["tag"] = out["taxonomy"] + ":" + out["tag"]
    out = out.rename(columns={"period_end": "fiscal_year_end"})
    return out[["cik", "label", "metric", "fiscal_year_end", "exact_end", "value", "unit", "tag", "accession",
                "form", "available_at", "first_value", "filings", "tags_used"]].reset_index(drop=True)


def source_agreement(root: Path, spec: FundamentalsSpec) -> pd.DataFrame:
    """同一申报的同一事实，FSDS 与 Company Facts 的数值是否一致（只比较指标登记的科目）。"""
    store = EdgarStore(root)
    ciks = [c.cik for c in spec.companies]
    marks = ", ".join("?" for _ in ciks)
    facts = store.query("facts", f"cik IN ({marks})", ciks)
    tags = {f"{tx}:{tg}" for m in spec.metrics.values() for tx, tg in m.tags}
    facts = facts[(facts["taxonomy"] + ":" + facts["tag"]).isin(tags)]
    facts["period_key"] = period_key(facts["period_end"])
    a = facts[facts["source"] == "fsds"].drop_duplicates(FACT_KEY)
    b = facts[facts["source"] == "companyfacts"].drop_duplicates(FACT_KEY)
    both = a.merge(b, on=FACT_KEY, suffixes=("_fsds", "_api"))
    both["diff"] = (both["value_fsds"] - both["value_api"]).abs()
    both["period_end"] = both["period_end_api"]
    return both[FACT_KEY + ["period_end", "cik_fsds", "value_fsds", "value_api", "diff"]].rename(
        columns={"cik_fsds": "cik"})
