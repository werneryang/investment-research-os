"""季度财报登记与证据包（docs/study-earnings.md）。

登记在 config/earnings/<earnings_id>.yaml：SEC 原文（SHA256 固定，存于 data/earnings/filings/）、
逐期的合并利润表与分部数值、现金流量、资产负债表时点、收入积压订单、恒定汇率对账、资本开支展望、
可比性说明和覆盖分类。核对（check）确认：

- 原文文件存在、SHA256 与登记一致；
- 每个登记数值（取绝对值、按千分位格式）出现在所引原文中；这是宽松的存在性检查，不证明数值取自正确的行列；
- 会计恒等式成立：收入由各产品线合成，分部营业利润合计等于营业利润，营业利润加其他收支等于税前利润，
  税前利润减所得税等于净利润，净利润减优先股股息等于普通股可得净利润；
- 2025 年全年 = 前三季度 + 推导的第四季度；现金流量表的季度现金流与资本开支满足发行人的自由现金流定义；
- 文字摘录（展望、说明）逐字出现在所引原文中。

证据包（industry-evidence.v1）只在核对零错误时生成，经 evidence_bundle 接入器进入版本库；研究只读证据包。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from ..connectors.base import now_utc
from ..events import _norm, plain_text

BUNDLE_SCHEMA = "industry-evidence.v1"
DATASET_ID = "earnings_evidence"
UNIT = "USD million"
SCHEMA = "earnings.v1"
TZ = "America/New_York"

STATUSES = ("done", "data_gap", "judgment")
GUIDANCE_KINDS = ("qualitative", "point", "range")
INCOME_METRICS = ("revenue", "cost_of_revenues", "R_and_D", "sales_marketing", "G_and_A", "op_income", "other_income", "EBT",
                  "income_tax", "consolidated_NI", "preferred_dividends", "common_NI", "Search", "YouTube_ads", "Network",
                  "subscriptions_platforms_devices", "Services_revenue", "Cloud_revenue", "OtherBets_revenue", "hedging",
                  "Services_op", "Cloud_op", "OtherBets_op", "Alphabet_level_op", "equity_security_gain_loss")
BALANCE_METRICS = ("cash", "marketable_securities", "total_assets", "total_equity", "longterm_debt", "PPE_net")
QUARTERS = ("q3_2025", "q4_2025", "q1_2026", "q2_2026", "q3_2026")


def earnings_dir(root: Path) -> Path:
    return Path(root) / "config" / "earnings"


def filings_dir(root: Path) -> Path:
    return Path(root) / "data" / "earnings" / "filings"


def load_earnings(root: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(earnings_dir(root).glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if doc.get("schema_version") != SCHEMA:
            raise ValueError(f"财报登记 {path.name} 的 schema_version 不是 {SCHEMA}")
        if doc.get("earnings_id") != path.stem:
            raise ValueError(f"财报登记 {path.name} 的 earnings_id 应与文件名一致")
        out[doc["earnings_id"]] = doc
    return out


def sub(a: dict[str, Any], b: dict[str, Any]) -> dict[str, int]:
    """逐项相减：全年减前三季度得到第四季度。"""
    return {k: a[k] - b[k] for k in a}


def _number_in(text: str, value: float) -> bool:
    """数值的绝对值（千分位）作为独立数字出现在原文中。0 视为已出现（报表中常写作 —）。"""
    n = abs(value)
    if n == 0:
        return True
    shown = f"{int(n):,}" if float(n).is_integer() else f"{n:,}"
    return re.search(rf"(?<![\d,.]){re.escape(shown)}(?![\d,]|\.\d)", text) is not None


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=lambda: {"documents": 0, "values": 0, "identities": 0, "excerpts": 0})
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)


def _identities(label: str, v: dict[str, int], rep: Report) -> None:
    def eq(name: str, left: float, right: float) -> None:
        if left != right:
            rep.errors.append(f"{label}：{name}不成立（{left:,} ≠ {right:,}）")
        else:
            rep.checked["identities"] += 1

    eq("Search + YouTube + Network + 订阅/平台/设备 = Google Services 收入",
       v["Search"] + v["YouTube_ads"] + v["Network"] + v["subscriptions_platforms_devices"], v["Services_revenue"])
    eq("Services + Cloud + Other Bets + 套期 = 收入",
       v["Services_revenue"] + v["Cloud_revenue"] + v["OtherBets_revenue"] + v["hedging"], v["revenue"])
    eq("收入 − 营业成本与费用 = 营业利润",
       v["revenue"] - v["cost_of_revenues"] - v["R_and_D"] - v["sales_marketing"] - v["G_and_A"], v["op_income"])
    eq("分部营业利润合计 = 营业利润", v["Services_op"] + v["Cloud_op"] + v["OtherBets_op"] + v["Alphabet_level_op"], v["op_income"])
    eq("营业利润 + 其他收支 = 税前利润", v["op_income"] + v["other_income"], v["EBT"])
    eq("税前利润 − 所得税 = 净利润", v["EBT"] - v["income_tax"], v["consolidated_NI"])
    eq("净利润 − 优先股股息 = 普通股可得净利润", v["consolidated_NI"] - v["preferred_dividends"], v["common_NI"])


def check(root: Path, registry: dict[str, dict[str, Any]] | None = None) -> Report:
    """核对全部财报登记；有任何错误时证据包不生成。"""
    rep = Report()
    registry = load_earnings(root) if registry is None else registry
    for eid, reg in registry.items():
        for key in ("entity", "company", "as_of", "documents", "income", "cash_flow", "balance", "guidance", "notes", "coverage"):
            if not reg.get(key):
                rep.errors.append(f"{eid}：缺少 {key}")
        if rep.errors:
            continue
        texts: dict[str, str] = {}
        docs: dict[str, dict[str, Any]] = {}
        for d in reg["documents"]:
            missing = [k for k in ("id", "form", "accession", "url", "file", "sha256", "accepted_at") if not d.get(k)]
            if missing:
                rep.errors.append(f"{eid}：原文 {d.get('id')} 缺少 {'、'.join(missing)}")
                continue
            if d["id"] in docs:
                rep.errors.append(f"{eid}：原文 {d['id']} 重复登记")
                continue
            docs[d["id"]] = {**d, "accepted_at": str(d["accepted_at"])}
            path = filings_dir(root) / d["file"]
            if not path.exists():
                rep.errors.append(f"{eid}：原文 {d['id']} 不在本地（{d['file']}）；先运行 iros earnings fetch")
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != d["sha256"]:
                rep.errors.append(f"{eid}：原文 {d['id']} 的 SHA256 与登记不一致")
                continue
            texts[d["id"]] = plain_text(raw)
            rep.checked["documents"] += 1
            rep.documents[d["id"]] = docs[d["id"]]

        def has(doc_id: str, value: float, where: str) -> None:
            if doc_id not in docs:
                rep.errors.append(f"{eid}：{where} 引用的原文 {doc_id} 未登记")
            elif doc_id in texts:
                if _number_in(texts[doc_id], value):
                    rep.checked["values"] += 1
                else:
                    rep.errors.append(f"{eid}：{where} 的数值 {value:,} 没有出现在原文 {doc_id} 中")

        for pid, p in reg["income"].items():
            miss = [m for m in INCOME_METRICS if m not in p.get("values", {})]
            if miss:
                rep.errors.append(f"{eid}：{pid} 缺少 {'、'.join(miss)}")
                continue
            for m in INCOME_METRICS:
                has(p["document"], p["values"][m], f"{pid}.{m}")
            _identities(f"{eid}：{pid}", p["values"], rep)
        if not rep.errors:
            q4 = sub(reg["income"]["fy_2025"]["values"], reg["income"]["nine_months_2025"]["values"])
            _identities(f"{eid}：2025 年第四季度（全年减前三季度）", q4, rep)
        for pid, p in reg["cash_flow"].items():
            for m in ("cfo", "cash_ppe"):
                has(p["document"], p[m], f"现金流 {pid}.{m}")
        fcf = reg.get("issuer_fcf") or {}
        for pid in ("q3_2026", "ttm_2026q3"):
            if pid in fcf:
                cf = reg["cash_flow"][pid]
                if cf["cfo"] - cf["cash_ppe"] != fcf[pid]:
                    rep.errors.append(f"{eid}：{pid} 的经营现金流减资本开支不等于发行人披露的自由现金流")
                else:
                    rep.checked["identities"] += 1
                has(fcf["document"], fcf[pid], f"发行人自由现金流 {pid}")
        for date_, b in reg["balance"].items():
            for m in BALANCE_METRICS:
                if m not in b["values"]:
                    rep.errors.append(f"{eid}：资产负债表 {date_} 缺少 {m}")
                else:
                    has(b["document"], b["values"][m], f"资产负债表 {date_}.{m}")
        for pt in reg["rpo"]["points"]:
            for m in ("total", "cloud"):
                has(pt["document"], pt[m], f"积压订单 {pt['date']}.{m}")
        fx = reg["fx"]
        for m in ("reported_revenue", "yoy_constant_currency_revenue", "qoq_constant_currency_revenue"):
            has(fx["document"], fx[m], f"恒定汇率 {m}")
        ps = reg["per_share"]
        for m in ("diluted_eps_q3_2026", "diluted_eps_q3_2025"):
            if ps["document"] in texts and not re.search(rf"(?<![\d.]){re.escape(format(ps[m], '.2f'))}(?!\d)", texts[ps['document']]):
                rep.errors.append(f"{eid}：每股收益 {ps[m]} 没有出现在原文 {ps['document']} 中")
            else:
                rep.checked["values"] += 1
        has(reg["annual_cash_ppe"]["document"], reg["annual_cash_ppe"]["value"], "2025 年现金资本开支")

        def excerpt(doc_id: str, text: str, where: str) -> None:
            if doc_id not in docs:
                rep.errors.append(f"{eid}：{where} 引用的原文 {doc_id} 未登记")
            elif doc_id in texts:
                if _norm(text) in texts[doc_id]:
                    rep.checked["excerpts"] += 1
                else:
                    rep.errors.append(f"{eid}：{where} 的摘录没有逐字出现在原文 {doc_id} 中")

        ids = set()
        for g in reg["guidance"]:
            where = f"展望 {g.get('id')}"
            if g.get("id") in ids:
                rep.errors.append(f"{where} 重复")
            ids.add(g.get("id"))
            if g.get("kind") not in GUIDANCE_KINDS:
                rep.errors.append(f"{where} 的 kind 应为 {'、'.join(GUIDANCE_KINDS)} 之一")
            st = g.get("statement") or {}
            if not st.get("zh") or not st.get("en"):
                rep.errors.append(f"{where} 缺少中英文陈述")
            if g.get("kind") == "range" and not (g.get("low_usd_bn") and g.get("high_usd_bn")):
                rep.errors.append(f"{where} 缺少区间上下限")
            if g.get("kind") == "point" and not g.get("point_usd_bn"):
                rep.errors.append(f"{where} 缺少点值")
            excerpt(g["document"], g["excerpt"], where)
        ids = set()
        for n in reg["notes"]:
            where = f"说明 {n.get('id')}"
            if n.get("id") in ids:
                rep.errors.append(f"{where} 重复")
            ids.add(n.get("id"))
            for key in ("title", "fact", "limit"):
                if not (n.get(key) or {}).get("zh") or not (n.get(key) or {}).get("en"):
                    rep.errors.append(f"{where} 的 {key} 缺少中英文")
            for text in n.get("excerpts") or []:
                excerpt(n["document"], text, where)
            if n.get("check"):
                has(n["check"]["document"], n["check"]["original_direct_q4_2025_revenue"], where)
        excerpt(reg["rpo"]["recognition"]["document"], reg["rpo"]["recognition"]["excerpt"], "积压订单确认期限")
        for c in reg["coverage"]:
            if c.get("status") not in STATUSES:
                rep.errors.append(f"覆盖项 {c.get('id')} 的 status 应为 {'、'.join(STATUSES)} 之一")
            if not (c.get("item") or {}).get("zh") or not (c.get("item") or {}).get("en"):
                rep.errors.append(f"覆盖项 {c.get('id')} 缺少中英文")
    return rep


def _et_day(accepted_at: str) -> str:
    s = str(accepted_at)
    if "T" not in s:
        return s[:10]
    return pd.Timestamp(s).tz_convert(TZ).date().isoformat()


def build_bundle(root: Path, clock: Callable[[], datetime] = now_utc) -> dict[str, Any]:
    """全部财报登记的证据包；核对有错误时拒绝。"""
    root = Path(root)
    registry = load_earnings(root)
    rep = check(root, registry)
    if rep.errors:
        raise ValueError("财报登记核对未通过，不生成证据包：" + "；".join(rep.errors[:5]))
    records, snapshot = [], {}
    for eid, reg in registry.items():
        docs = {d["id"]: rep.documents[d["id"]] for d in reg["documents"]}

        def add(kind: str, period: str, metric: str, value: float, date_: str, doc_id: str) -> None:
            d = docs[doc_id]
            records.append({"id": f"{eid}|{kind}|{period}|{metric}", "date": str(date_), "value": value,
                            "published_at": _et_day(d["accepted_at"]), "earnings": eid, "record": kind, "period": period,
                            "metric": metric, "document": doc_id, "accession": d["accession"], "form": d["form"], "url": d["url"]})

        for pid, p in reg["income"].items():
            for m in INCOME_METRICS:
                add("income", pid, m, p["values"][m], p["end"], p["document"])
        for pid, p in reg["cash_flow"].items():
            for m in ("cfo", "cash_ppe"):
                add("cash_flow", pid, m, p[m], p["end"], p["document"])
        for date_, b in reg["balance"].items():
            for m in BALANCE_METRICS:
                add("balance", date_, m, b["values"][m], date_, b["document"])
        snapshot[eid] = {
            "entity": reg["entity"], "company": reg["company"], "cik": reg["cik"], "tickers": reg["tickers"],
            "latest_period": reg["latest_period"], "as_of": str(reg["as_of"]), "release": reg["release"],
            "periods": {pid: {k: p[k] for k in ("label", "start", "end", "document")} for pid, p in reg["income"].items()},
            "documents": [{k: d.get(k) for k in ("id", "form", "period_end", "accession", "accepted_at", "url", "sha256")}
                          for d in reg["documents"]],
            "related_studies": reg.get("related_studies", []), "issuer_fcf": reg["issuer_fcf"], "rpo": reg["rpo"], "fx": reg["fx"], "per_share": reg["per_share"],
            "annual_cash_ppe": reg["annual_cash_ppe"], "guidance": reg["guidance"], "notes": reg["notes"],
            "coverage": reg["coverage"]}
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(earnings_dir(root).glob("*.yaml"))}
    return {"schema": BUNDLE_SCHEMA, "unit": UNIT, "records": sorted(records, key=lambda x: x["id"]),
            "metadata": {"purpose": "quarterly earnings studies", "built_at": clock().isoformat(), "earnings_files": files,
                         "check": {"errors": rep.errors, "checked": rep.checked}, "earnings": snapshot}}


def write_bundle(root: Path, doc: dict[str, Any], built_at: datetime | None = None) -> Path:
    out = Path(root) / "data" / "earnings" / "bundles"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"earnings-{(built_at or now_utc()).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


def fetch(root: Path, user_agent: str, http_get: Callable[[str, dict[str, str]], bytes] | None = None) -> list[str]:
    """下载登记中本地还没有的原文，返回新下载的文件名。SHA256 由 check 核对。"""
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
    for reg in load_earnings(root).values():
        for d in reg.get("documents", []):
            if (out / d["file"]).exists():
                continue
            (out / d["file"]).write_bytes(http_get(d["url"], {"User-Agent": user_agent}))
            got.append(d["file"])
    return got
