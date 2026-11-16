"""事件登记与证据包（docs/study-events.md）。

登记在 config/events/<event_id>.yaml：原文（SHA256 固定，存于 data/events/filings/，或引用产业链登记的原文）、
带逐字摘录的事实、以及「原文没有提及」的检查项。核对（check）确认：
- 原文文件存在、SHA256 与登记一致；
- 每条事实的摘录逐字出现在原文中（去掉标签、合并空白后比较）；
- 每个「未提及」检查项的检索词确实不在所列原文中。

证据包（industry-evidence.v1）只在核对零错误时生成，经 evidence_bundle 接入器进入版本库；研究只读证据包。
每条记录的 value 是相对事件日的日历天数（事件时间 t），date 是事实日期或原文接受日（美东）。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from ..connectors.base import now_utc

BUNDLE_SCHEMA = "industry-evidence.v1"
DATASET_ID = "event_evidence"
UNIT = "days"
SCHEMA = "event.v1"
KINDS = ("context", "related", "event", "scheduled")
TZ = "America/New_York"


def events_dir(root: Path) -> Path:
    return Path(root) / "config" / "events"


def filings_dir(root: Path) -> Path:
    return Path(root) / "data" / "events" / "filings"


def plain_text(raw: bytes) -> str:
    """原文的可比较文字：去掉 HTML 标签，还原实体，合并空白。摘录和检索词都与它比较。"""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_events(root: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(events_dir(root).glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if doc.get("schema_version") != SCHEMA:
            raise ValueError(f"事件登记 {path.name} 的 schema_version 不是 {SCHEMA}")
        if doc.get("event_id") != path.stem:
            raise ValueError(f"事件登记 {path.name} 的 event_id 应与文件名一致")
        out[doc["event_id"]] = doc
    return out


def event_documents(root: Path) -> dict[str, dict[str, Any]]:
    """全部事件登记中的原文 ID → 登记（供主体索引等核对引用）。"""
    return {d["id"]: d for ev in load_events(root).values() for d in ev.get("documents", [])}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=lambda: {"documents": 0, "excerpts": 0, "absent_terms": 0})
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)


def _resolve_documents(root: Path, ev: dict[str, Any], rep: Report) -> dict[str, tuple[dict[str, Any], Path]]:
    """原文 ID → (登记, 本地文件)。引用产业链登记的原文时，出处、接受时间与 SHA256 取自那里。"""
    docs: dict[str, tuple[dict[str, Any], Path]] = {}
    supply = None
    for d in ev.get("documents", []):
        if d["id"] in docs:
            rep.errors.append(f"{ev['event_id']}：原文 {d['id']} 重复登记")
            continue
        if d.get("catalog") == "supply_chain":
            if supply is None:
                from ..supply_chain.catalog import load_catalog
                supply = load_catalog(root)
            ref = supply.documents.get(d["id"])
            if not ref:
                rep.errors.append(f"{ev['event_id']}：引用的产业链原文 {d['id']} 未登记")
                continue
            entry = {"id": d["id"], **{k: ref.get(k) for k in ("accession", "form", "url", "file", "sha256")},
                     "accepted_at": str(ref["accepted_at"]), "items": [], "catalog": "supply_chain"}
            docs[d["id"]] = (entry, Path(root) / "data" / "supply_chain" / "filings" / ref["file"])
        else:
            missing = [k for k in ("accession", "form", "url", "file", "sha256", "accepted_at") if not d.get(k)]
            if missing:
                rep.errors.append(f"{ev['event_id']}：原文 {d['id']} 缺少 {'、'.join(missing)}")
                continue
            docs[d["id"]] = ({**d, "accepted_at": str(d["accepted_at"])}, filings_dir(root) / d["file"])
    return docs


def check(root: Path, events: dict[str, dict[str, Any]] | None = None) -> Report:
    """核对全部事件登记；有任何错误时证据包不生成。"""
    rep = Report()
    events = load_events(root) if events is None else events
    for eid, ev in events.items():
        for key in ("entity", "title", "event_date", "as_of", "facts"):
            if not ev.get(key):
                rep.errors.append(f"{eid}：缺少 {key}")
        if rep.errors:
            continue
        event_day, as_of = date.fromisoformat(str(ev["event_date"])), date.fromisoformat(str(ev["as_of"]))
        if event_day > as_of:
            rep.errors.append(f"{eid}：事件日晚于查阅日")
        docs = _resolve_documents(root, ev, rep)
        texts: dict[str, str] = {}
        for did, (d, path) in docs.items():
            if not path.exists():
                rep.errors.append(f"{eid}：原文 {did} 不在本地（{path.name}）；先运行 iros event fetch")
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != d["sha256"]:
                rep.errors.append(f"{eid}：原文 {did} 的 SHA256 与登记不一致")
                continue
            texts[did] = plain_text(raw)
            rep.checked["documents"] += 1
            rep.documents[did] = d
        ids = set()
        for f in ev["facts"]:
            where = f"{eid}：事实 {f.get('id')}"
            if f.get("id") in ids:
                rep.errors.append(f"{where} 重复")
            ids.add(f.get("id"))
            if f.get("kind") not in KINDS:
                rep.errors.append(f"{where} 的 kind 应为 {'、'.join(KINDS)} 之一")
            statement = f.get("statement") or {}
            if not statement.get("zh") or not statement.get("en"):
                rep.errors.append(f"{where} 缺少中英文陈述")
            try:
                day = date.fromisoformat(str(f.get("date")))
            except ValueError:
                rep.errors.append(f"{where} 的日期无效")
                continue
            if f.get("kind") == "scheduled" and day <= as_of:
                rep.errors.append(f"{where} 是日程，但日期不晚于查阅日；已发生的事项应按实际结果登记")
            if f.get("kind") != "scheduled" and day > as_of:
                rep.errors.append(f"{where} 的日期晚于查阅日")
            if f.get("document") not in docs:
                rep.errors.append(f"{where} 引用的原文未登记")
                continue
            if f["document"] not in texts:
                continue  # 原文缺失或校验值不符，已报错
            if _norm(f.get("excerpt") or "") == "" or _norm(f["excerpt"]) not in texts[f["document"]]:
                rep.errors.append(f"{where} 的摘录没有逐字出现在原文 {f['document']} 中")
                continue
            rep.checked["excerpts"] += 1
        for n in ev.get("not_mentioned", []):
            where = f"{eid}：未提及项 {n.get('id')}"
            if not n.get("terms") or not n.get("documents"):
                rep.errors.append(f"{where} 需要检索词和原文")
                continue
            for did in n["documents"]:
                if did not in docs:
                    rep.errors.append(f"{where} 引用的原文 {did} 未登记")
                    continue
                if did not in texts:
                    continue
                for term in n["terms"]:
                    if re.search(re.escape(term), texts[did], re.I):
                        rep.errors.append(f"{where}：检索词「{term}」出现在原文 {did} 中，不能登记为未提及")
                    else:
                        rep.checked["absent_terms"] += 1
    return rep


def _et_day(accepted_at: str) -> str:
    return pd.Timestamp(accepted_at).tz_convert(TZ).date().isoformat()


def build_bundle(root: Path, clock: Callable[[], datetime] = now_utc) -> dict[str, Any]:
    """全部事件登记的证据包；核对有错误时拒绝。"""
    root = Path(root)
    events = load_events(root)
    rep = check(root, events)
    if rep.errors:
        raise ValueError("事件登记核对未通过，不生成证据包：" + "；".join(rep.errors[:5]))
    records, snapshot = [], {}
    for eid, ev in events.items():
        event_day = date.fromisoformat(str(ev["event_date"]))
        docs = {d["id"]: rep.documents[d["id"]] for d in ev["documents"]}

        def offset(day: str) -> int:
            return (date.fromisoformat(day) - event_day).days

        for order, f in enumerate(ev["facts"]):
            d = docs[f["document"]]
            records.append({"id": f"{eid}|fact|{f['id']}", "date": str(f["date"]), "value": offset(str(f["date"])),
                            "published_at": _et_day(d["accepted_at"]), "event": eid, "record": "fact", "fact": f["id"],
                            "kind": f["kind"], "order": order, "document": f["document"], "accession": d["accession"], "form": d["form"],
                            "url": d["url"], "locator": f.get("locator"), "excerpt": _norm(f["excerpt"]),
                            "statement": f["statement"]})
        for did, d in docs.items():
            day = _et_day(d["accepted_at"])
            records.append({"id": f"{eid}|filing|{did}", "date": day, "value": offset(day), "published_at": day,
                            "event": eid, "record": "filing", "document": did, "accession": d["accession"],
                            "form": d["form"], "items": d.get("items") or [], "url": d["url"],
                            "accepted_at": d["accepted_at"]})
        snapshot[eid] = {"entity": ev["entity"], "title": ev["title"], "event_date": str(ev["event_date"]),
                         "as_of": str(ev["as_of"]), "filings_checked": ev.get("filings_checked"),
                         "not_mentioned": [{**n, "documents": list(n["documents"])} for n in ev.get("not_mentioned", [])]}
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(events_dir(root).glob("*.yaml"))}
    return {"schema": BUNDLE_SCHEMA, "unit": UNIT, "records": sorted(records, key=lambda x: x["id"]),
            "metadata": {"purpose": "event studies", "built_at": clock().isoformat(), "event_files": files,
                         "check": {"errors": rep.errors, "checked": rep.checked}, "events": snapshot}}


def write_bundle(root: Path, doc: dict[str, Any], built_at: datetime | None = None) -> Path:
    out = Path(root) / "data" / "events" / "bundles"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"events-{(built_at or now_utc()).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


def fetch(root: Path, user_agent: str, http_get: Callable[[str, dict[str, str]], bytes] | None = None) -> list[str]:
    """下载登记中本地还没有的事件原文（不含引用的产业链原文），返回新下载的文件名。SHA256 由 check 核对。"""
    if not user_agent:
        raise ValueError("下载 SEC 原文需要 .env 中的 SEC_USER_AGENT")
    if http_get is None:
        import urllib.request

        def http_get(url: str, headers: dict[str, str]) -> bytes:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - 登记的 SEC 原文地址
                return resp.read()
    out, got = filings_dir(root), []
    out.mkdir(parents=True, exist_ok=True)
    for ev in load_events(root).values():
        for d in ev.get("documents", []):
            if d.get("catalog") or (out / d["file"]).exists():
                continue
            (out / d["file"]).write_bytes(http_get(d["url"], {"User-Agent": user_agent}))
            got.append(d["file"])
    return got
