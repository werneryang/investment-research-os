"""关系链研究的固定证据包（docs/relation-chain-design.md §4、§5）。

证据包（industry-evidence.v1）经 evidence_bundle 接入器进入版本库，研究只读取证据包：
- records：链上公司的年度营收。直接从登记原文（claims.yaml 中 SHA256 固定的年报）的内联 XBRL 解析，
  每家公司只用一份年报中的三个财年，与原文同一口径；合并口径之外只取业务分部维度（StatementBusinessSegmentsAxis）
- metadata.snapshot：产业链登记的快照：主体、活动、关系（含核对状态、证据级别、技术复核的结论边界、披露方与最早公开时间）、
  证据摘录与出处、查阅记录；登记核对必须零错误、零未核对

营收的币种以原文单位为准（台积电为新台币），证据包的 unit 为 mixed，研究只比较同一公司自己币种的增长率。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..connectors.base import now_utc
from ..data.fundamentals import EdgarStore
from .catalog import FILES, OPTIONAL_FILES, Catalog, Report, check, load_catalog
from .classification import ClassificationStore

BUNDLE_SCHEMA = "industry-evidence.v1"
DATASET_ID = "relation_chain_evidence"
UNIT = "mixed"
# 首例（NVIDIA）链上有年报原文的公司：营收取自这份年报（三星、SK 海力士、鸿海、纬创不在 SEC 申报，尚未取得）
REVENUE_DOCUMENTS = {"co_nvidia": "doc_nvda_10k_fy2026", "co_tsmc": "doc_tsmc_20f_fy2025",
                     "co_micron": "doc_mu_10k_fy2025", "co_fabrinet": "doc_fn_10k_fy2026"}
# 营收科目：按原文实际使用的科目，逐份年报列出
REVENUE_TAGS = ("us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "ifrs-full:RevenueFromContractsWithCustomers", "ifrs-full:Revenue")
SEGMENT_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
# 分部数字可另带「经营分部」合并项维度；其他维度（地区、产品、抵销项等）不取
CONSOLIDATION_AXIS, OPERATING = "srt:ConsolidationItemsAxis", "us-gaap:OperatingSegmentsMember"

_CONTEXT = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.S)
_MEMBER = re.compile(r'<xbrldi:explicitMember dimension="([^"]+)">([^<]+)</xbrldi:explicitMember>')
_FACT = re.compile(r'<ix:nonFraction([^>]*)>(.*?)</ix:nonFraction>', re.S)
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def inline_revenue(text: str) -> list[dict[str, Any]]:
    """年报内联 XBRL 中的年度营收：合并口径（无维度）与业务分部（业务分部维度，可另带经营分部合并项）。同一事实重复出现时只保留一次。"""
    contexts = {}
    for cid, body in _CONTEXT.findall(text):
        start, end = re.search(r"<xbrli:startDate>([^<]+)", body), re.search(r"<xbrli:endDate>([^<]+)", body)
        if start and end:
            contexts[cid] = (start.group(1), end.group(1), dict(_MEMBER.findall(body)))
    out, seen = [], set()
    for attrs, body in _FACT.findall(text):
        a = dict(_ATTR.findall(attrs))
        if a.get("name") not in REVENUE_TAGS or a.get("contextRef") not in contexts:
            continue
        start, end, dims = contexts[a["contextRef"]]
        days = (pd.Timestamp(end) - pd.Timestamp(start)).days
        extra = {k: v for k, v in dims.items() if k != SEGMENT_AXIS}
        if not 350 <= days <= 380 or (dims and SEGMENT_AXIS not in dims) or any(
                (k, v) != (CONSOLIDATION_AXIS, OPERATING) for k, v in extra.items()):
            continue
        raw = re.sub(r"<[^>]+>", "", html.unescape(body)).strip().replace(",", "")
        if not raw or raw == "-":
            continue
        value = float(raw) * 10 ** int(a.get("scale", "0")) * (-1 if a.get("sign") == "-" else 1)
        key = (a["name"], start, end, dims.get(SEGMENT_AXIS), a.get("unitRef"), value)
        if key in seen:
            continue
        seen.add(key)
        out.append({"tag": a["name"], "start": start, "end": end, "segment": dims.get(SEGMENT_AXIS),
                    "unit": (a.get("unitRef") or "").upper(), "value": value})
    return out


def _claim_owner(cat: Catalog, c: dict[str, Any]) -> str | None:
    if c["type"] == "filing_text":
        return cat.documents[c["document"]].get("entity")
    return None


def snapshot(cat: Catalog, rep: Report) -> dict[str, Any]:
    """研究所需的登记快照；只用已核对的状态与结论边界，不含人工复核以外的推断。"""
    def limits(item_id: str) -> str:
        t = cat.technical.get(item_id)
        return t["limits"] if t and rep.technical.get(item_id) == "passed" else ""

    def doc_available(doc_id: str) -> str:
        from .catalog import _available_at
        return _available_at(cat.documents[doc_id]["accepted_at"])

    claims = {}
    for cid, c in cat.claims.items():
        doc = cat.documents.get(c.get("document") or "")
        claims[cid] = {k: c.get(k) for k in ("type", "document", "locator", "excerpt", "publisher", "title", "published_at",
                                             "channel", "summary", "display", "estimate", "note")}
        claims[cid].update({"available_at": rep.claim_available_at.get(cid), "url": doc and doc["url"],
                            "form": doc and doc.get("form"), "entity": doc and doc.get("entity"),
                            "machine_check": rep.claim_checks.get(cid), "limits": limits(cid)})
    relations = {}
    for rid, r in cat.relations.items():
        dates = [rep.claim_available_at[c] for c in r["claims"] if rep.claim_available_at.get(c)]
        relations[rid] = {**{k: v for k, v in r.items() if k not in ("reviewer", "reviewed_at")},
                          "status": rep.statuses.get(rid), "evidence_class": rep.evidence_class.get(rid),
                          "limits": limits(rid), "available_at": min(dates) if dates else None,
                          "disclosed_by": sorted({o for c in r["claims"] if (o := _claim_owner(cat, cat.claims[c]))})}
    searches = {qid: {**q, "searched_at": str(q["searched_at"]), "available_at": doc_available(q["document"])}
                for qid, q in cat.searches.items()}
    used = {c["document"] for c in claims.values() if c.get("document")} | {q["document"] for q in cat.searches.values()}
    documents = {d: {k: cat.documents[d].get(k) for k in ("accession", "form", "entity", "url", "document_period_end")}
                 | {"available_at": doc_available(d)} for d in sorted(used)}
    for d in documents.values():
        d["document_period_end"] = d["document_period_end"] and str(d["document_period_end"])
    return {
        "catalog_version": cat.version,
        "entities": {e["id"]: {k: e.get(k) for k in ("name", "type", "parent", "cik", "country")}
                     for e in cat.entities.values()},
        "activities": {a["id"]: {"name": a["name"], "definition": a["definition"]} for a in cat.activities.values()},
        "relations": relations, "claims": claims, "documents": documents, "searches": searches,
    }


def build_bundle(root: Path, companies: dict[str, str] = REVENUE_DOCUMENTS, cat: Catalog | None = None,
                 clock=now_utc) -> dict[str, Any]:
    """companies：{主体 ID: 原文 ID}，营收取自这份年报。登记核对有错误或未核对项时拒绝。"""
    root = Path(root)
    cat = cat or load_catalog(root)
    facts = EdgarStore(root).query("segment_facts")
    rep = check(cat, ClassificationStore(root).load(), facts if len(facts) else None)
    if rep.errors or rep.warnings:
        raise ValueError("产业链登记核对未全部通过，不生成关系链证据包：" + "；".join([*rep.errors, *rep.warnings][:5]))
    snap = snapshot(cat, rep)
    records = []
    docs_dir = root / "data" / "supply_chain" / "filings"
    for entity, doc_id in companies.items():
        doc = cat.documents[doc_id]
        if doc.get("entity") != entity:
            raise ValueError(f"原文 {doc_id} 不属于 {entity}")
        data = (docs_dir / doc["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != doc["sha256"]:
            raise ValueError(f"原文 {doc_id} 的 SHA256 与登记不一致")
        rows = inline_revenue(data.decode("utf-8", errors="replace"))
        if not rows:
            raise ValueError(f"原文 {doc_id} 中没有年度营收")
        for r in rows:
            key = f"{doc_id}|{r['tag']}|{r['segment'] or 'consolidated'}|{r['unit']}|{r['end']}"
            records.append({"id": key, "date": r["end"], "value": r["value"],
                            "published_at": snap["documents"][doc_id]["available_at"][:10],
                            "kind": "segment_revenue" if r["segment"] else "revenue", "entity": entity,
                            "document": doc_id, "accession": doc["accession"], "form": doc.get("form"),
                            "document_period_end": str(doc.get("document_period_end")), **r})
    base = root / "config" / "supply_chain"
    files = {n: hashlib.sha256((base / f"{n}.yaml").read_bytes()).hexdigest()
             for n in FILES + OPTIONAL_FILES if (base / f"{n}.yaml").exists()}
    return {"schema": BUNDLE_SCHEMA, "unit": UNIT, "records": sorted(records, key=lambda x: x["id"]),
            "metadata": {"purpose": "relationship chain study", "built_at": clock().isoformat(),
                         "catalog_files": files, "revenue_documents": companies,
                         "catalog_check": {"errors": rep.errors, "warnings": rep.warnings, "verified": rep.verified},
                         "snapshot": snap}}


def write_bundle(root: Path, doc: dict[str, Any], built_at: datetime | None = None) -> Path:
    out = Path(root) / "data" / "supply_chain" / "bundles"
    out.mkdir(parents=True, exist_ok=True)
    stamp = (built_at or now_utc()).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"relation-chain-{stamp}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path
