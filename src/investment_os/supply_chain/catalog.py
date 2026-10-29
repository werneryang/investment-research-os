"""产业链登记（config/supply_chain/）：L2 活动、L3 主体与映射、L4 关系、证据与研究单元的读取和核对。

结构错误（缺字段、重复 ID、未知取值）在读取时报错。核对（check）再逐项检查引用、方向约定与证据：
- NAICS 代码必须在已导入的分类表中（未导入时记为未核对）
- filing_text 的摘录必须逐字出现在本地原文中，原文 SHA256 必须与登记一致
- xbrl_segment 必须在 segment_facts 表中找到同一申报、科目、维度、期末与期间长度，数值一致
- 证据须来自相关公司的申报；XBRL 证据须写明数值与单位，单位参与匹配；分部别名须属于上级公司的申报与业务分部维度
- 原文登记的精确期末须在原文中出现，且与 FSDS 的月末相差不超过半个月
- 被否定或撤回的证据不能支撑任何映射或关系

机器核对（claim_checks）与人工复核（review_status）分开记录：模型提取的证据为 candidate，
confirmed 只能由人工复核给出并写明复核人与日期。映射与关系自身有错误时为 invalid；否则有至少一条人工确认、
机器核对通过且适用（来自相关公司、分部别名相符）的证据时为 confirmed，其余为 candidate。
本地缺少原文或分部事实、证据缺数值或单位时，相应项目记为未核对（warning），不冒充通过。
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
    "原文": {"id", "accession", "form", "entity", "url", "file", "sha256", "accepted_at", "retrieved_at",
             "document_period_end"},
    "证据": {"id", "type", "document", "locator", "excerpt", "accession", "tag", "segments", "period_end",
             "duration_quarters", "value", "unit", "origin_type", "review_status", "reviewer", "reviewed_at", "note"},
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
        # 人工复核状态与机器核对分开：confirmed 只能由人工复核给出，须写明复核人与日期
        if c["review_status"] in ("confirmed", "rejected", "retracted"):
            _need(c, ("reviewer", "reviewed_at"), f"证据 {c['id']}（{c['review_status']} 须有人工复核记录）")
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
    # 机器核对结果：verified / unverified（本地缺少原文或数据、证据缺数值或单位）/ failed
    claim_checks: dict[str, str] = field(default_factory=dict)
    # 映射与关系的状态：invalid（自身有错误）/ confirmed（至少一条人工确认、机器核对通过且适用的证据）/ candidate
    statuses: dict[str, str] = field(default_factory=dict)
    inventory: dict[str, Any] = field(default_factory=dict)

    def ok(self, kind: str) -> None:
        self.verified[kind] = self.verified.get(kind, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _members(segments: str) -> set[str]:
    return {p.partition("=")[2] for p in segments.split(";") if p}


def _business_segment(segments: str) -> str | None:
    """segments 中 BusinessSegments 维度的成员；没有该维度返回 None。"""
    for part in segments.split(";"):
        axis, _, member = part.partition("=")
        if axis == "BusinessSegments":
            return member
    return None


def _company_cik(cat: Catalog, entity_id: str | None) -> int | None:
    """主体所属公司的 CIK：分部与匿名对手方取上级公司。"""
    e = cat.entities.get(entity_id or "")
    if e is None:
        return None
    if e["type"] != "company":
        e = cat.entities.get(e.get("parent") or "")
    return int(e["cik"]) if e and e.get("cik") else None


def _filing_cik(facts: pd.DataFrame | None, accession: str) -> int | None:
    if facts is None:
        return None
    rows = facts.loc[facts["accession"] == accession, "cik"]
    return int(rows.iloc[0]) if len(rows) else None


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
            parent_cik = _company_cik(cat, e["id"])
            filer = _filing_cik(segment_facts, m.get("seen_in"))
            if filer is not None and filer != parent_cik:
                rep.errors.append(f"{e['id']} 的 XBRL 成员 {m['member']} 所在申报 {m.get('seen_in')} 属于 CIK {filer}，"
                                  f"不是上级公司（CIK {parent_cik}）")
            elif not any(_business_segment(s) == m["member"] for s in rows["segments"]):
                rep.errors.append(f"{e['id']} 的 XBRL 成员 {m['member']} 不在申报 {m.get('seen_in')} 的业务分部维度中")
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
    for d in cat.documents.values():
        filer = _filing_cik(segment_facts, d["accession"])
        owner = _company_cik(cat, d.get("entity"))
        if filer is not None and filer != owner:
            rep.errors.append(f"原文 {d['id']} 的申报 {d['accession']} 属于 CIK {filer}，不是登记的 {d.get('entity')}")
        end = d.get("document_period_end")
        if not end:
            rep.warnings.append(f"原文 {d['id']} 未登记精确期末")
            continue
        end = pd.Timestamp(str(end))
        text = texts.get(d["id"])
        if text is not None:
            phrase = f"fiscal year ended {end.strftime('%B')} {end.day}, {end.year}"
            if phrase.lower() not in text.lower():
                rep.errors.append(f"原文 {d['id']} 中找不到「{phrase}」，精确期末未得到原文支持")
            else:
                rep.ok("document_period_end")
        if segment_facts is not None:
            months = segment_facts.loc[segment_facts["accession"] == d["accession"], "filing_period_month_end"]
            # FSDS 把期末取整到最近的月末；相差超过半个月说明登记的期末或申报编号有误
            if len(months) and abs((pd.Timestamp(months.iloc[0]) - end).days) > 15:
                rep.errors.append(f"原文 {d['id']} 的精确期末 {end.date()} 与 FSDS 月末 {pd.Timestamp(months.iloc[0]).date()} "
                                  "相差超过半个月")
    for c in cat.claims.values():
        if c["type"] == "filing_text":
            doc = cat.documents.get(c["document"])
            if doc is None:
                rep.errors.append(f"证据 {c['id']} 引用了未登记的原文 {c['document']}")
                continue
            rep.claim_available_at[c["id"]] = _available_at(doc["accepted_at"])
            text = texts.get(doc["id"])
            if text is None:
                rep.claim_checks[c["id"]] = "unverified"
                continue
            if normalize_text(str(c["excerpt"])) not in text:
                rep.errors.append(f"证据 {c['id']} 的摘录没有逐字出现在 {doc['file']} 中")
                rep.claim_checks[c["id"]] = "failed"
            else:
                rep.ok("excerpt")
                rep.claim_checks[c["id"]] = "verified"
            continue
        if c.get("value") is None or not c.get("unit"):
            rep.warnings.append(f"证据 {c['id']} 缺少数值或单位，未核对")
            rep.claim_checks[c["id"]] = "unverified"
            continue
        if segment_facts is None:
            rep.warnings.append(f"分部事实未提取，未核对证据 {c['id']}")
            rep.claim_checks[c["id"]] = "unverified"
            continue
        f = segment_facts
        rows = f[(f["accession"] == c["accession"]) & (f["tag"] == c["tag"]) & (f["segments"] == c["segments"])
                 & (f["period_end"] == pd.Timestamp(str(c["period_end"])))
                 & (f["duration_quarters"] == int(c["duration_quarters"]))]
        rep.claim_checks[c["id"]] = "failed"
        if rows.empty:
            rep.errors.append(f"证据 {c['id']} 在分部事实中找不到对应的行")
            continue
        same_unit = rows[rows["unit"] == c["unit"]]
        if same_unit.empty:
            rep.errors.append(f"证据 {c['id']} 的单位 {c['unit']} 与分部事实 {sorted(set(rows['unit']))} 不一致")
            continue
        if not (same_unit["value"] == float(c["value"])).any():
            rep.errors.append(f"证据 {c['id']} 的数值 {c['value']} 与分部事实 {sorted(same_unit['value'])} 不一致")
            continue
        rep.claim_available_at[c["id"]] = pd.Timestamp(same_unit["available_at"].iloc[0]).isoformat()
        rep.claim_checks[c["id"]] = "verified"
        rep.ok("xbrl_fact")

    def claim_owner(c: dict[str, Any]) -> int | None:
        """证据来自哪家公司的申报：原文看登记的主体，XBRL 看分部事实中的申报主体。"""
        if c["type"] == "filing_text":
            doc = cat.documents.get(c["document"])
            return _company_cik(cat, doc.get("entity")) if doc else None
        return _filing_cik(segment_facts, c["accession"])

    def supported(kind: str, item: dict[str, Any], owners: set[int | None], errors_before: int,
                  excluded: set[str] = frozenset()) -> None:
        """证据须存在、未被否定或撤回、来自相关公司的申报、机器核对未失败；不满足的证据不计入。

        状态：该对象自身有任何错误为 invalid；否则有人工确认且机器核对通过的证据为 confirmed，其余为 candidate。
        excluded 为调用方已判定不适用的证据（如分部别名不符）。
        """
        usable, confirmed = 0, False
        for cid in item.get("claims") or []:
            c = cat.claims.get(cid)
            if c is None:
                rep.errors.append(f"{kind} {item['id']} 引用了未登记的证据 {cid}")
                continue
            if c["review_status"] in ("rejected", "retracted"):
                rep.errors.append(f"{kind} {item['id']} 引用了被{'否定' if c['review_status'] == 'rejected' else '撤回'}"
                                  f"的证据 {cid}")
                continue
            owner = claim_owner(c)
            if owner is not None and owner not in owners:
                rep.errors.append(f"{kind} {item['id']} 的证据 {cid} 来自 CIK {owner} 的申报，不属于相关公司")
                continue
            if rep.claim_checks.get(cid) == "failed" or cid in excluded:
                continue  # 机器核对失败或调用方判定不适用：错误已另行报告，不计入
            usable += 1
            confirmed |= c["review_status"] == "confirmed" and rep.claim_checks.get(cid) == "verified"
        if not usable:
            rep.errors.append(f"{kind} {item['id']} 没有可用的证据")
        rep.statuses[item["id"]] = ("invalid" if len(rep.errors) > errors_before
                                    else "confirmed" if confirmed else "candidate")

    # ---- L3 映射 ----
    for lk in cat.links.values():
        before = len(rep.errors)
        e = cat.entities.get(lk["entity"])
        if e is None or e["type"] == "anonymous":
            rep.errors.append(f"映射 {lk['id']} 的主体 {lk['entity']} 未登记或为匿名对手方")
        if lk["activity"] not in cat.activities:
            rep.errors.append(f"映射 {lk['id']} 的活动 {lk['activity']} 未登记")
        # XBRL 证据的业务分部成员须是该分部登记的别名，防止把另一分部或另一公司的数字挂到这里
        aliases = {m["member"] for m in (e or {}).get("xbrl_members") or []}
        mismatched = set()
        for cid in lk.get("claims") or []:
            c = cat.claims.get(cid)
            if c and c["type"] == "xbrl_segment" and e and e["type"] == "segment" \
                    and _business_segment(c["segments"]) not in aliases:
                rep.errors.append(f"映射 {lk['id']} 的证据 {cid} 的业务分部 {_business_segment(c['segments'])} "
                                  f"不是 {e['id']} 的登记别名")
                mismatched.add(cid)
        supported("映射", lk, {_company_cik(cat, lk["entity"])}, before, mismatched)

    # ---- L4 关系 ----
    keys: dict[tuple[Any, ...], str] = {}
    for r in cat.relations.values():
        before = len(rep.errors)
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
        supported("关系", r, {_company_cik(cat, x) for x in ends if x}, before)

    # ---- 研究单元 ----
    for u in cat.units.values():
        if u["activity"] not in cat.activities:
            rep.errors.append(f"研究单元 {u['id']} 的活动 {u['activity']} 未登记")
        for e in u["entities"]:
            if e not in cat.entities:
                rep.errors.append(f"研究单元 {u['id']} 引用了未登记的主体 {e}")

    rep.inventory = inventory(cat)
    rep.inventory["claim_checks"] = {s: sum(v == s for v in rep.claim_checks.values())
                                     for s in ("verified", "unverified", "failed")}
    rep.inventory["link_relation_status"] = {s: sum(v == s for v in rep.statuses.values())
                                             for s in ("confirmed", "candidate", "invalid")}
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
    review: dict[str, int] = {}
    for c in cat.claims.values():
        review[c["review_status"]] = review.get(c["review_status"], 0) + 1
    for r in cat.relations.values():
        types[r["type"]] = types.get(r["type"], 0) + 1
    return {
        "catalog_version": cat.version,
        "counts": {"activities": len(cat.activities), "entities": len(cat.entities), "links": len(cat.links),
                   "relations": len(cat.relations), "claims": len(cat.claims), "units": len(cat.units)},
        "relation_types": types,
        "claim_review_status": review,
        "anonymous_counterparties": sorted(e["id"] for e in cat.entities.values() if e["type"] == "anonymous"),
        "by_company": by_company,
        "gaps": gaps,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
