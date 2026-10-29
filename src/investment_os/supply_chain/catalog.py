"""产业链登记（config/supply_chain/）：L2 活动、L3 主体与映射、L4 关系、证据与研究单元的读取和核对。

结构错误（缺字段、重复 ID、未知取值）在读取时报错。核对（check）再逐项检查引用、方向约定与证据：
- NAICS 代码必须在已导入的分类表中（未导入时记为未核对）
- filing_text 的摘录必须逐字出现在本地原文中，原文 SHA256 必须与登记一致
- xbrl_segment 必须在 segment_facts 表中找到同一申报、科目、维度、期末与期间长度，数值一致
- 映射与关系至少有一条 confirmed 证据；被否定或撤回的证据不能支撑任何映射或关系
本地缺少原文或分部事实时，相应项目记为未核对（warning），不冒充通过。
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

SCHEMA_VERSION = "supply_chain.v1"
FILES = ("activities", "entities", "links", "relations", "claims", "units")
DIRECTED = ("supply", "foundry", "contract_manufacturing")
UNDIRECTED = ("partnership", "competition", "substitution")
MATCH_TYPES = ("exact", "partial", "ambiguous")
REVIEW = ("candidate", "confirmed", "rejected", "retracted")
ORIGIN = ("observed", "derived", "assumed", "inferred", "unknown")
ENTITY_TYPES = ("company", "segment", "anonymous")
UNIT_STATUS = ("unassessed", "A", "B", "C")
TZ = "America/New_York"
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})


class CatalogError(ValueError):
    pass


_BLOCK_TAG = re.compile(r"<(?:/?(?:p|div|br|td|th|tr|li|ul|ol|table|h[1-6])\b)[^>]*>", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """去标签、反转义、弯引号换直引号、空白折叠；原文与摘录用同一规则比较。

    块级标签视为空白，行内标签（b、span 等）直接去掉，避免在标点前插入空格。
    """
    text = re.sub(r"<[^>]+>", "", _BLOCK_TAG.sub(" ", text))
    return re.sub(r"\s+", " ", html.unescape(text).translate(_QUOTES)).strip()


@dataclass
class Catalog:
    root: Path
    activities: dict[str, dict[str, Any]]
    entities: dict[str, dict[str, Any]]
    links: dict[str, dict[str, Any]]
    relations: dict[str, dict[str, Any]]
    claims: dict[str, dict[str, Any]]
    documents: dict[str, dict[str, Any]]
    units: dict[str, dict[str, Any]]
    version: str = ""

    def ciks(self) -> set[int]:
        return {int(e["cik"]) for e in self.entities.values() if e.get("cik")}


def _need(item: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if item.get(k) in (None, "", [])]
    if missing:
        raise CatalogError(f"{where} 缺少字段：{', '.join(missing)}")


# 每类对象允许的字段：YAML 流式写法中未加引号的英文逗号会把一个值拆成多个键，未知字段一律报错
FIELDS = {
    "活动": {"id", "name", "definition", "includes", "excludes", "naics"},
    "主体": {"id", "type", "name", "cik", "country", "parent", "xbrl_members", "superseded_in"},
    "原文": {"id", "accession", "form", "entity", "url", "file", "sha256", "accepted_at", "retrieved_at"},
    "证据": {"id", "type", "document", "locator", "excerpt", "accession", "tag", "segments", "period_end",
             "duration_quarters", "value", "origin_type", "review_status", "note"},
    "映射": {"id", "entity", "activity", "match", "scope", "valid_from", "valid_to", "claims"},
    "关系": {"id", "type", "provider", "recipient", "parties", "market", "activity", "activity_gap", "product",
             "share", "valid_from", "valid_to", "claims", "note"},
    "研究单元": {"id", "question", "activity", "entities", "observation", "metrics", "period", "required_inputs",
                 "known_gaps", "expected", "status"},
}


def _choice(value: Any, choices: tuple[str, ...], where: str) -> None:
    if value not in choices:
        raise CatalogError(f"{where} 的取值 {value!r} 无效；可用：{', '.join(choices)}")


def load_catalog(root: Path) -> Catalog:
    base = Path(root) / "config" / "supply_chain"
    docs: dict[str, Any] = {}
    for name in FILES:
        path = base / f"{name}.yaml"
        if not path.exists():
            raise CatalogError(f"缺少产业链登记文件：{path}")
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if doc.get("schema_version") != SCHEMA_VERSION:
            raise CatalogError(f"{path.name} 的 schema_version 应为 {SCHEMA_VERSION}，实际为 {doc.get('schema_version')!r}")
        docs[name] = doc
    seen: dict[str, str] = {}

    def index(items: list[dict[str, Any]], kind: str, required: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        out = {}
        for item in items or []:
            _need(item, ("id", *required), f"{kind} {item.get('id', '?')}")
            unknown = sorted(str(k) for k in set(item) - FIELDS[kind])
            if unknown:
                raise CatalogError(f"{kind} {item['id']} 有未知字段：{', '.join(unknown)}（检查未加引号的英文逗号）")
            if item["id"] in seen:
                raise CatalogError(f"ID 重复：{item['id']}（{seen[item['id']]} 与 {kind}）")
            seen[item["id"]] = kind
            out[item["id"]] = item
        return out

    activities = index(docs["activities"].get("activities"), "活动", ("name", "definition"))
    for a in activities.values():
        for m in a.get("naics") or []:
            _need(m, ("code", "match_type", "review_status"), f"活动 {a['id']} 的 NAICS 对应")
            _choice(m["match_type"], MATCH_TYPES, f"活动 {a['id']} 的 match_type")
            _choice(m["review_status"], REVIEW, f"活动 {a['id']} 的 review_status")
    entities = index(docs["entities"].get("entities"), "主体", ("type", "name"))
    for e in entities.values():
        _choice(e["type"], ENTITY_TYPES, f"主体 {e['id']} 的 type")
    documents = index(docs["claims"].get("documents"), "原文", ("accession", "url", "file", "sha256", "accepted_at"))
    claims = index(docs["claims"].get("claims"), "证据", ("type", "origin_type", "review_status"))
    for c in claims.values():
        _choice(c["type"], ("filing_text", "xbrl_segment"), f"证据 {c['id']} 的 type")
        _choice(c["origin_type"], ORIGIN, f"证据 {c['id']} 的 origin_type")
        _choice(c["review_status"], REVIEW, f"证据 {c['id']} 的 review_status")
        _need(c, ("document", "locator", "excerpt") if c["type"] == "filing_text" else
              ("accession", "tag", "segments", "period_end", "duration_quarters"), f"证据 {c['id']}")
    links = index(docs["links"].get("links"), "映射", ("entity", "activity", "match", "claims"))
    for lk in links.values():
        _choice(lk["match"], MATCH_TYPES, f"映射 {lk['id']} 的 match")
    relations = index(docs["relations"].get("relations"), "关系", ("type", "claims"))
    for r in relations.values():
        _choice(r["type"], DIRECTED + UNDIRECTED, f"关系 {r['id']} 的 type")
    units = index(docs["units"].get("units"), "研究单元", ("question", "activity", "entities", "status"))
    for u in units.values():
        _choice(u["status"], UNIT_STATUS, f"研究单元 {u['id']} 的 status")
    return Catalog(Path(root), activities, entities, links, relations, claims, documents, units,
                   docs["activities"].get("version", ""))


def _available_at(accepted: str) -> str:
    """接受时间的次日 0 点（美东），与财报事实相同的保守规则。"""
    t = pd.Timestamp(accepted).tz_convert(TZ)
    return (t.normalize() + timedelta(days=1)).isoformat()


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verified: dict[str, int] = field(default_factory=dict)
    claim_available_at: dict[str, str] = field(default_factory=dict)
    inventory: dict[str, Any] = field(default_factory=dict)

    def ok(self, kind: str) -> None:
        self.verified[kind] = self.verified.get(kind, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _members(segments: str) -> set[str]:
    return {p.partition("=")[2] for p in segments.split(";") if p}


def check(cat: Catalog, naics: pd.DataFrame | None = None, segment_facts: pd.DataFrame | None = None,
          documents_dir: Path | None = None) -> Report:
    rep = Report()
    docs_dir = documents_dir or cat.root / "data" / "supply_chain" / "filings"

    # ---- L2：NAICS 候选对应 ----
    codes = set(naics["code"]) if naics is not None else None
    for a in cat.activities.values():
        for m in a.get("naics") or []:
            if codes is None:
                rep.warnings.append(f"NAICS 分类表未导入，未核对活动 {a['id']} 的代码 {m['code']}")
            elif str(m["code"]) not in codes:
                rep.errors.append(f"活动 {a['id']} 的 NAICS 代码 {m['code']} 不在 NAICS 2022 表中")
            else:
                rep.ok("naics_code")

    # ---- 主体 ----
    for e in cat.entities.values():
        if e["type"] == "segment":
            parent = cat.entities.get(e.get("parent"))
            if parent is None or parent["type"] != "company":
                rep.errors.append(f"分部 {e['id']} 的上级 {e.get('parent')} 不是登记的公司")
        if e["type"] == "anonymous" and e.get("cik"):
            rep.errors.append(f"匿名对手方 {e['id']} 不能有 CIK")
        for m in e.get("xbrl_members") or []:
            if segment_facts is None:
                rep.warnings.append(f"分部事实未提取，未核对 {e['id']} 的 XBRL 成员 {m['member']}")
                continue
            rows = segment_facts[segment_facts["accession"] == m.get("seen_in")]
            if not any(m["member"] in _members(s) for s in rows["segments"]):
                rep.errors.append(f"{e['id']} 的 XBRL 成员 {m['member']} 不在申报 {m.get('seen_in')} 的分部事实中")
            else:
                rep.ok("xbrl_member")

    # ---- 证据 ----
    texts: dict[str, str | None] = {}
    for d in cat.documents.values():
        path = docs_dir / d["file"]
        if not path.exists():
            rep.warnings.append(f"原文 {d['id']}（{d['file']}）不在本地，相关摘录未核对")
            texts[d["id"]] = None
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != d["sha256"]:
            rep.errors.append(f"原文 {d['id']} 的 SHA256 与登记不一致")
            texts[d["id"]] = None
            continue
        texts[d["id"]] = normalize_text(data.decode("utf-8", errors="replace"))
        rep.ok("document")
    for c in cat.claims.values():
        if c["type"] == "filing_text":
            doc = cat.documents.get(c["document"])
            if doc is None:
                rep.errors.append(f"证据 {c['id']} 引用了未登记的原文 {c['document']}")
                continue
            rep.claim_available_at[c["id"]] = _available_at(doc["accepted_at"])
            text = texts.get(doc["id"])
            if text is None:
                continue
            if normalize_text(str(c["excerpt"])) not in text:
                rep.errors.append(f"证据 {c['id']} 的摘录没有逐字出现在 {doc['file']} 中")
            else:
                rep.ok("excerpt")
            continue
        if segment_facts is None:
            rep.warnings.append(f"分部事实未提取，未核对证据 {c['id']}")
            continue
        f = segment_facts
        rows = f[(f["accession"] == c["accession"]) & (f["tag"] == c["tag"]) & (f["segments"] == c["segments"])
                 & (f["period_end"] == pd.Timestamp(str(c["period_end"])))
                 & (f["duration_quarters"] == int(c["duration_quarters"]))]
        if rows.empty:
            rep.errors.append(f"证据 {c['id']} 在分部事实中找不到对应的行")
            continue
        if c.get("value") is not None and not (rows["value"] == float(c["value"])).any():
            rep.errors.append(f"证据 {c['id']} 的数值 {c['value']} 与分部事实 {sorted(rows['value'])} 不一致")
            continue
        rep.claim_available_at[c["id"]] = pd.Timestamp(rows["available_at"].iloc[0]).isoformat()
        rep.ok("xbrl_fact")

    def supported(kind: str, item: dict[str, Any]) -> None:
        statuses = []
        for cid in item.get("claims") or []:
            c = cat.claims.get(cid)
            if c is None:
                rep.errors.append(f"{kind} {item['id']} 引用了未登记的证据 {cid}")
                continue
            statuses.append(c["review_status"])
            if c["review_status"] in ("rejected", "retracted"):
                rep.errors.append(f"{kind} {item['id']} 引用了被{'否定' if c['review_status'] == 'rejected' else '撤回'}"
                                  f"的证据 {cid}")
        if "confirmed" not in statuses:
            rep.errors.append(f"{kind} {item['id']} 没有任何 confirmed 证据")

    # ---- L3 映射 ----
    for lk in cat.links.values():
        e = cat.entities.get(lk["entity"])
        if e is None or e["type"] == "anonymous":
            rep.errors.append(f"映射 {lk['id']} 的主体 {lk['entity']} 未登记或为匿名对手方")
        if lk["activity"] not in cat.activities:
            rep.errors.append(f"映射 {lk['id']} 的活动 {lk['activity']} 未登记")
        supported("映射", lk)

    # ---- L4 关系 ----
    keys: dict[tuple[Any, ...], str] = {}
    for r in cat.relations.values():
        where = f"关系 {r['id']}"
        if r["type"] in DIRECTED:
            ends = [r.get("provider"), r.get("recipient")]
            if r.get("parties") or None in ends or ends[0] == ends[1]:
                rep.errors.append(f"{where} 是有向关系，须有不同的 provider 与 recipient，不用 parties")
            key = (r["type"], *ends, r.get("activity"), r.get("product"))
        else:
            ends = list(r.get("parties") or [])
            if r.get("provider") or r.get("recipient") or len(ends) != 2 or ends[0] == ends[1]:
                rep.errors.append(f"{where} 是无向关系，须用两个不同的 parties，不用 provider / recipient")
            elif ends != sorted(ends):
                rep.errors.append(f"{where} 的 parties 须按 ID 排序后只存一次")
            if r["type"] == "competition" and not r.get("market"):
                rep.errors.append(f"{where} 是竞争关系，必须写明 market")
            key = (r["type"], *sorted(ends), r.get("market"))
        for end in ends:
            if end is not None and end not in cat.entities:
                rep.errors.append(f"{where} 引用了未登记的主体 {end}")
        if r.get("activity") is None:
            if not r.get("activity_gap"):
                rep.errors.append(f"{where} 没有活动，须在 activity_gap 写明原因")
        elif r["activity"] not in cat.activities:
            rep.errors.append(f"{where} 的活动 {r['activity']} 未登记")
        share = r.get("share")
        if share is not None:
            v = share.get("value")
            if v is not None and not 0 <= float(v) <= 1:
                rep.errors.append(f"{where} 的占比 {v} 不在 0–1 之间")
            if v is None and not share.get("bound"):
                rep.errors.append(f"{where} 的占比既无数值也无范围")
            if not (share.get("denominator") and share.get("period")):
                rep.errors.append(f"{where} 的占比须写明分母与期间")
        if key in keys:
            rep.errors.append(f"{where} 与 {keys[key]} 重复记录同一关系")
        keys[key] = r["id"]
        supported("关系", r)

    # ---- 研究单元 ----
    for u in cat.units.values():
        if u["activity"] not in cat.activities:
            rep.errors.append(f"研究单元 {u['id']} 的活动 {u['activity']} 未登记")
        for e in u["entities"]:
            if e not in cat.entities:
                rep.errors.append(f"研究单元 {u['id']} 引用了未登记的主体 {e}")

    rep.inventory = inventory(cat)
    return rep


def inventory(cat: Catalog) -> dict[str, Any]:
    """P0 盘点：各层数量、每家公司的映射与关系、已知缺口。"""
    by_company: dict[str, dict[str, int]] = {}
    for lk in cat.links.values():
        parent = cat.entities[lk["entity"]].get("parent") or lk["entity"]
        by_company.setdefault(parent, {"links": 0, "relations": 0})["links"] += 1
    for r in cat.relations.values():
        for end in [r.get("provider"), r.get("recipient"), *(r.get("parties") or [])]:
            if end in cat.entities and cat.entities[end].get("cik"):
                by_company.setdefault(end, {"links": 0, "relations": 0})["relations"] += 1
    gaps = [f"{r['id']}：{r['activity_gap']}" for r in cat.relations.values() if r.get("activity_gap")]
    gaps += [f"{e['id']}：{e['superseded_in']} 起不再使用" for e in cat.entities.values() if e.get("superseded_in")]
    gaps += [f"{u['id']}：{g}" for u in cat.units.values() for g in u.get("known_gaps") or []]
    types: dict[str, int] = {}
    for r in cat.relations.values():
        types[r["type"]] = types.get(r["type"], 0) + 1
    return {
        "catalog_version": cat.version,
        "counts": {"activities": len(cat.activities), "entities": len(cat.entities), "links": len(cat.links),
                   "relations": len(cat.relations), "claims": len(cat.claims), "units": len(cat.units)},
        "relation_types": types,
        "anonymous_counterparties": sorted(e["id"] for e in cat.entities.values() if e["type"] == "anonymous"),
        "by_company": by_company,
        "gaps": gaps,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
