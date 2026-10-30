"""芯片经营分析（P3b）的固定证据包：分部事实、产业链登记状态与研究单元定义，导入后由研究按版本固定。

证据包是一个自包含的 JSON（industry-evidence.v1），经 evidence_bundle 接入器进入版本库：
- records：登记分部（按 XBRL 别名）在年度 10-K 中的分部事实；同一申报的其他分部（如 AllOtherSegments）
  营收与合并口径营收（E1 事实表，有则附上）只用于分部合计核对
- metadata：产业链登记的核对结果（必须零错误）、映射与证据的机器核对、技术复核（含结论边界）与可选人工复核状态、研究单元定义、
  所用分部事实分区版本与登记文件校验值

研究只读取证据包，不直接读取 segment_facts 或登记文件，因此登记或分部事实之后的变化不影响已有运行的复现。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..connectors.base import now_utc
from ..data.fundamentals import EdgarStore
from ..registry import load_fundamentals
from .catalog import FILES, Catalog, check, load_catalog
from .classification import ClassificationStore

BUNDLE_SCHEMA = "industry-evidence.v1"
DATASET_ID = "chip_segment_evidence"
ANNUAL_FORMS = ("10-K", "10-K/A")
# 只取经营分部口径：ConsolidationItems 为空或 OperatingSegments；CorporateNonSegment 等不是分部数字
_SEGMENT_CONSOLIDATION = (None, "OperatingSegments")


def _axes(segments: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in segments.split(";") if p)


def fact_fiscal_year(filing_fy: int, filing_month_end: pd.Timestamp, period_end: pd.Timestamp) -> int:
    """事实所属财年：申报财年减去两者月末相隔的整年数（比较列中的上一年、上上年）。"""
    months = (filing_month_end.year - period_end.year) * 12 + (filing_month_end.month - period_end.month)
    return int(filing_fy) - round(months / 12)


def _iso(value: Any) -> str | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value).isoformat()


def build_bundle(root: Path, cat: Catalog | None = None, facts: pd.DataFrame | None = None,
                 consolidated: pd.DataFrame | None = None, clock=now_utc) -> dict[str, Any]:
    """组装证据包；产业链登记核对有错误或有项目未核对时拒绝，不把未核对的证据固定下来。"""
    root = Path(root)
    cat = cat or load_catalog(root)
    store = EdgarStore(root)
    facts = store.query("segment_facts") if facts is None else facts
    rep = check(cat, ClassificationStore(root).load(), facts)
    if rep.errors or rep.warnings:
        raise ValueError("产业链登记核对未全部通过，不生成证据包："
                         + "；".join([*rep.errors, *rep.warnings][:5]))
    if consolidated is None:
        consolidated = _consolidated_revenue(root, store)

    aliases = {m["member"]: e for e in cat.entities.values() if e["type"] == "segment"
               for m in e.get("xbrl_members") or []}
    company_of = {e["id"]: e["parent"] for e in cat.entities.values() if e["type"] == "segment"}
    ciks = {int(cat.entities[c]["cik"]) for c in company_of.values() if cat.entities[c].get("cik")}
    f = facts[facts["form"].isin(ANNUAL_FORMS) & (facts["duration_quarters"] == 4) & facts["cik"].isin(ciks)]
    records = []
    for r in f.itertuples(index=False):
        axes = _axes(r.segments)
        member = axes.get("BusinessSegments")
        if member is None or set(axes) - {"BusinessSegments", "ConsolidationItems"} \
                or axes.get("ConsolidationItems") not in _SEGMENT_CONSOLIDATION:
            continue
        entity = aliases.get(member)
        if entity is not None and int(cat.entities[entity["parent"]]["cik"]) != int(r.cik):
            entity = None  # 别名属于另一家公司：不挂到登记分部
        kind = "segment" if entity is not None else "other_segment"
        fy = fact_fiscal_year(r.fiscal_year, pd.Timestamp(r.filing_period_month_end), pd.Timestamp(r.period_end))
        records.append({
            "id": f"{r.accession}|{r.tag}|{r.segments}|{pd.Timestamp(r.period_end).date()}",
            "date": pd.Timestamp(r.period_end).date().isoformat(), "value": r.value,
            "published_at": pd.Timestamp(r.accepted_at).tz_convert("America/New_York").date().isoformat(),
            "kind": kind, "entity": entity["id"] if entity else None, "member": member,
            "company": entity["parent"] if entity else None, "cik": int(r.cik), "accession": r.accession,
            "form": r.form, "filing_fiscal_year": int(r.fiscal_year), "fiscal_year": fy, "tag": r.tag,
            "segments": r.segments, "unit": r.unit, "period_end_month": pd.Timestamp(r.period_end).date().isoformat(),
            "filing_period_month_end": pd.Timestamp(r.filing_period_month_end).date().isoformat(),
            "available_at": _iso(r.available_at),
        })
    accessions = {x["accession"] for x in records}
    seen: dict[str, int] = {}
    for r in consolidated[consolidated["accession"].isin(accessions)].itertuples(index=False):
        key = f"{r.accession}|{r.tag}|consolidated|{pd.Timestamp(r.period_end).date()}"
        seen[key] = seen.get(key, 0) + 1
        records.append({
            "id": key if seen[key] == 1 else f"{key}|{seen[key]}",
            "date": pd.Timestamp(r.period_end).date().isoformat(), "value": r.value, "published_at": None,
            "kind": "consolidated", "entity": None, "member": None, "company": None, "cik": int(r.cik),
            "accession": r.accession, "tag": r.tag, "unit": r.unit,
            "period_end_month": pd.Timestamp(r.period_end).date().isoformat(), "available_at": _iso(r.available_at),
        })
    if not records:
        raise ValueError("没有登记分部的年度分部事实，不生成证据包")
    base = root / "config" / "supply_chain"
    partitions = {p["key"]: p["version_id"] for p in store.partitions() if p["table"] == "segment_facts"}
    return {
        "schema": BUNDLE_SCHEMA, "unit": "USD", "records": sorted(records, key=lambda x: x["id"]),
        "metadata": {
            "purpose": "chip P3b segment operating analysis",
            "built_at": clock().isoformat(),
            "catalog_version": cat.version,
            "catalog_files": {n: hashlib.sha256((base / f"{n}.yaml").read_bytes()).hexdigest() for n in FILES},
            "catalog_check": {"errors": rep.errors, "warnings": rep.warnings, "verified": rep.verified},
            "claims": {cid: {"review_status": c["review_status"], "machine_check": rep.claim_checks.get(cid),
                             "technical_review": _technical(cat, rep, cid)}
                       for cid, c in cat.claims.items()},
            "links": {lid: {"entity": lk["entity"], "activity": lk["activity"], "match": lk["match"],
                            "scope": lk.get("scope", ""), "valid_from": _iso_date(lk.get("valid_from")),
                            "valid_to": _iso_date(lk.get("valid_to")), "review_status": lk["review_status"],
                            "technical_review": _technical(cat, rep, lid), "status": rep.statuses[lid]}
                      for lid, lk in cat.links.items()},
            "reviews": {rid: {k: r.get(k) for k in ("kind", "reviewer", "reviewed_at", "method", "scope", "basis", "record")}
                        for rid, r in cat.reviews.items()},
            "entities": {e["id"]: {"name": e["name"], "parent": e.get("parent"), "type": e["type"],
                                   "superseded_in": e.get("superseded_in")}
                         for e in cat.entities.values() if e["type"] in ("company", "segment")},
            "units": cat.units,
            "segment_fact_partitions": dict(sorted(partitions.items())),
        },
    }


def _technical(cat: Catalog, rep: Any, item_id: str) -> dict[str, Any] | None:
    """对象的技术复核：所用记录、复核日期、结果（passed / failed / stale）与结论边界；没有记录为 None。"""
    t = cat.technical.get(item_id)
    if t is None:
        return None
    return {"review": t["review"], "reviewed_at": t["reviewed_at"], "result": rep.technical[item_id], "limits": t["limits"]}


def _iso_date(value: Any) -> str | None:
    return None if value is None else str(value)


def _consolidated_revenue(root: Path, store: EdgarStore) -> pd.DataFrame:
    """E1 合并口径年度营收（只有 E1 登记的公司才有），用于分部合计核对。"""
    spec = load_fundamentals(root / "config" / "fundamentals.yaml")
    tags = {t for _, t in spec.metrics["revenue"].tags}
    facts = store.query("facts")
    # 只用 FSDS（与分部事实同一来源）；同一申报、科目与期末的重复行去重，数值不同的保留，由研究判为冲突
    rows = facts[facts["tag"].isin(tags) & (facts["duration_quarters"] == 4) & (facts["source"] == "fsds")]
    return rows[["accession", "cik", "tag", "period_end", "unit", "value", "available_at"]].drop_duplicates(
        subset=["accession", "tag", "period_end", "unit", "value"])


def write_bundle(root: Path, doc: dict[str, Any], built_at: datetime | None = None) -> Path:
    out = Path(root) / "data" / "supply_chain" / "bundles"
    out.mkdir(parents=True, exist_ok=True)
    stamp = (built_at or now_utc()).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"chip-segments-{stamp}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path
