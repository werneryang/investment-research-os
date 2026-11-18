"""季度财报登记与证据包（docs/study-earnings.md）。

登记在 config/earnings/<earnings_id>.yaml：SEC 原文（SHA256 固定，存于 data/earnings/filings/）、
逐期的合并利润表与分部数值、现金流量、资产负债表时点、可选的收入积压订单、恒定汇率对账、资本开支展望、
可比性说明和覆盖分类，以及 `profile`：这家公司的季度列、利润表科目、会计恒等式、分部、比率、页面行与图表、
关键发现措辞。研究分支、关键发现和页面只读 profile，不写死任何公司（新增公司见 docs/study-earnings.md）。核对（check）确认：

- 原文文件存在、SHA256 与登记一致；
- 每个登记数值（取绝对值、按千分位格式）出现在所引原文中；这是宽松的存在性检查，不证明数值取自正确的行列；
- profile 的结构完整且引用的科目都存在；
- 会计恒等式成立（由 profile.identities 列出，例如收入由各产品线合成、分部营业利润合计等于营业利润、
  税前利润减所得税等于净利润）；推导的季度（全年减前几季度）同样满足；
- 现金流量表的季度现金流与资本开支满足发行人的自由现金流定义；
- 文字摘录（展望、说明）逐字出现在所引原文中。

证据包（industry-evidence.v1）只在核对零错误时生成，经 evidence_bundle 接入器进入版本库；研究只读证据包。
"""

from __future__ import annotations

import hashlib
import json
import math
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
# 每家公司必备的合并利润表科目（研究分支据此算毛利率、营业利润率、现金转换）；其余科目由 profile.income_metrics 列出
CORE_INCOME = ("revenue", "cost_of_revenues", "op_income", "EBT", "consolidated_NI")
# 资产负债表时点的科目对所有公司相同
BALANCE_METRICS = ("cash", "marketable_securities", "total_assets", "total_equity", "longterm_debt", "PPE_net")
CASH_METRICS = ("cfo", "cash_ppe")
COMPUTED_KEYS = ("free_cash_flow", "gross_profit", "gross_margin", "op_margin", "capex_to_sales", "cfo_to_consolidated_ni")
CHART_UNITS = ("usd_bn", "pct")


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


def _identities(label: str, v: dict[str, int], rep: Report, identities: list[dict[str, Any]]) -> None:
    """profile.identities：terms（科目 → ±1）的加权和等于 equals 科目。"""
    for ident in identities:
        left = sum(int(coef) * v[m] for m, coef in ident["terms"].items())
        right = v[ident["equals"]]
        if left != right:
            rep.errors.append(f"{label}：{ident['name']}不成立（{left:,} ≠ {right:,}）")
        else:
            rep.checked["identities"] += 1


def _bi(x: Any) -> bool:
    """中英文文字：恰好 zh、en 两个键且非空（YAML 流式写法里的逗号会把英文截断成多余的键）。"""
    return isinstance(x, dict) and set(x) == {"zh", "en"} and bool(x["zh"]) and bool(x["en"])


def cash_metrics(p: dict[str, Any]) -> tuple[str, ...]:
    """本金只在显式启用后进入核对、证据包与计算，不混入 cash_ppe。"""
    return CASH_METRICS + (("cash_ppe_principal",) if p.get("fcf_deduct_principal") is True else ())


def free_cash_flow(cash: dict[str, Any], p: dict[str, Any]) -> float:
    """发行人 FCF：购置支出与相关本金分别扣除；启用时本金不能缺省为零。"""
    return cash["cfo"] - cash["cash_ppe"] - (cash["cash_ppe_principal"] if p.get("fcf_deduct_principal") is True else 0)


def display_keys(p: dict[str, Any]) -> set[str]:
    """页面、图表与比率可以引用的行键：利润表科目、现金流、研究分支算出的指标。"""
    keys = set(p.get("income_metrics") or []) | set(cash_metrics(p)) | set(COMPUTED_KEYS) | {r.get("key") for r in p.get("ratios") or []}
    if p.get("non_operating"):
        keys.add("ebt_ex_equity_securities")
    return keys


def profile_errors(reg: dict[str, Any]) -> list[str]:
    """profile 的结构与引用：研究分支只读 profile，缺什么就在这里报，不等到页面出错。"""
    p = reg.get("profile")
    if not isinstance(p, dict):
        return ["缺少 profile（见 docs/study-earnings.md）"]
    errs: list[str] = []
    mets = list(p.get("income_metrics") or [])
    miss = [m for m in CORE_INCOME if m not in mets]
    if miss:
        errs.append(f"profile.income_metrics 缺少必备科目 {'、'.join(miss)}")
    if not isinstance(p.get("short_name"), str) or not p.get("short_name"):
        errs.append("profile 缺少 short_name")
    qs = p.get("quarters") or []
    ids = [q.get("id") for q in qs]
    if len(qs) < 3 or len(set(ids)) != len(ids):
        errs.append("profile.quarters 至少 3 个且 id 不重复（从旧到新）")
    income, cash = reg.get("income") or {}, reg.get("cash_flow") or {}
    if "fcf_deduct_principal" in p and not isinstance(p["fcf_deduct_principal"], bool):
        errs.append("profile.fcf_deduct_principal 必须是布尔值")
    if p.get("fcf_deduct_principal") is True:
        for m in ("cash_ppe", "cash_ppe_principal"):
            if not _bi((p.get("metrics") or {}).get(m)):
                errs.append(f"profile.metrics.{m} 需要中英文标签（本金与购置支出分列）")
    for pid, cf in cash.items():
        if "cash_ppe_principal" in cf and p.get("fcf_deduct_principal") is not True:
            errs.append(f"cash_flow.{pid}.cash_ppe_principal 需要显式启用 profile.fcf_deduct_principal")
        for m in cash_metrics(p):
            v = cf.get(m)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                errs.append(f"cash_flow.{pid}.{m} 需要有限数值（不能缺失）")
            elif m != "cfo" and v < 0:
                errs.append(f"cash_flow.{pid}.{m} 应为非负现金支出")
    for q in qs:
        where = f"profile.quarters {q.get('id')}"
        if not q.get("id") or not q.get("label") or not q.get("end") or not _bi(q.get("name")):
            errs.append(f"{where} 需要 id、label、end 与中英文 name")
        d = q.get("derive")
        if d:
            if not d.get("total") or not d.get("less") or not _bi(d.get("method")) or not _bi(d.get("note")):
                errs.append(f"{where} 的 derive 需要 total、less、中英文 method 与 note")
            for k in ("total", "less"):
                if d.get(k) not in income:
                    errs.append(f"{where} 的 derive.{k} 不在 income 中")
        elif q.get("id") not in income:
            errs.append(f"{where} 不在 income 中；没有直接披露的季度要写 derive")
        if q.get("id") not in cash:
            errs.append(f"{where} 不在 cash_flow 中")
    for k in ("current", "yoy_base", "qoq_base"):
        if p.get(k) not in ids:
            errs.append(f"profile.{k} 应是 quarters 中的 id")
    ytd = p.get("year_to_date")
    if ytd and not (ytd.get("id") in cash and set(ytd.get("quarters") or []) <= set(ids) and ytd.get("quarters") and _bi(ytd.get("label")) and _bi(ytd.get("short"))):
        errs.append("profile.year_to_date 需要现金流期间 id、所含季度与中英文 label、short")
    if p.get("trailing") and p["trailing"] not in cash:
        errs.append("profile.trailing 不在 cash_flow 中")
    for ident in p.get("identities") or []:
        if not ident.get("name") or not ident.get("terms") or ident.get("equals") not in mets or not set(ident["terms"]) <= set(mets):
            errs.append(f"profile.identities 的 {ident.get('name')} 需要 name、terms 与 equals，科目都要在 income_metrics 中")
    if not p.get("identities"):
        errs.append("profile.identities 不能为空：会计恒等式是防止取错值的主要检查")
    for r in p.get("ratios") or []:
        if not r.get("key") or r.get("num") not in mets or r.get("den") not in mets:
            errs.append(f"profile.ratios {r.get('key')} 需要 key、num、den（科目在 income_metrics 中）")
    keys = display_keys(p)
    rk = {r.get("key") for r in p.get("ratios") or []} | {"gross_margin", "op_margin"}
    for name, allowed in (("growth", set(mets) | set(cash_metrics(p))), ("margins", rk), ("segment_ops", set(mets))):
        bad = [m for m in p.get(name) or [] if m not in allowed]
        if bad:
            errs.append(f"profile.{name} 引用了不存在的科目 {'、'.join(map(str, bad))}")
    if p.get("segment_ops") and not any(i.get("equals") == "op_income" and set(i["terms"]) == set(p["segment_ops"]) for i in p.get("identities") or []):
        errs.append("profile.segment_ops 应对应一条恒等式：分部营业利润合计 = op_income")
    no = p.get("non_operating")
    if no and (no.get("key") not in mets or not _bi(no.get("label"))):
        errs.append("profile.non_operating 需要 income_metrics 中的 key 与中英文 label")
    labels = p.get("metrics") or {}
    table = [t if isinstance(t, str) else t.get("key") for t in p.get("table") or []]
    if not table:
        errs.append("profile.table 不能为空")
    for k in table:
        if k not in keys:
            errs.append(f"profile.table 的 {k} 不是可显示的行键")
        elif not _bi(labels.get(k)):
            errs.append(f"profile.metrics 缺少 {k} 的中英文标签")
    for k in p.get("report") or []:
        if k not in keys or not _bi(labels.get(k)):
            errs.append(f"profile.report 的 {k} 需要可显示的行键与 metrics 中的中英文标签")
    for c in p.get("charts") or []:
        if not _bi(c.get("title")) or c.get("unit") not in CHART_UNITS or not c.get("series"):
            errs.append("profile.charts 每项需要中英文 title、unit（usd_bn 或 pct）与 series")
        for sr in c.get("series") or []:
            if sr.get("key") not in keys or not _bi(sr.get("label")):
                errs.append(f"profile.charts 的序列 {sr.get('key')} 需要可显示的 key 与中英文 label")
    if not p.get("segments"):
        errs.append("profile.segments 不能为空（单一分部的公司也列出它）")
    for sg in p.get("segments") or []:
        if not sg.get("name") or any(sg.get(k) not in keys for k in ("revenue", "op", "margin")):
            errs.append(f"profile.segments {sg.get('name')} 需要 name、revenue、op、margin（行键）")
    for k in ("unallocated", "share"):
        if p.get(k) and (p[k].get("key") not in keys or not _bi(p[k].get("label"))):
            errs.append(f"profile.{k} 需要可显示的 key 与中英文 label")
    f = p.get("findings") or {}
    if not _bi(f.get("revenue_caveat")):
        errs.append("profile.findings.revenue_caveat 需要中英文（收入口径限制，例如不能称为有机增长的原因）")
    seg = f.get("segment")
    if seg and (not seg.get("name") or seg.get("revenue") not in keys or seg.get("margin") not in keys or not _bi(seg.get("caveat"))):
        errs.append("profile.findings.segment 需要 name、revenue、margin 与中英文 caveat")
    cal = p.get("calibers") or {}
    ch = p.get("prior_year_charge")
    if ch:
        note = next((n for n in reg.get("notes") or [] if n.get("id") == ch.get("note")), None)
        if not note or (note.get("approx") or {}).get(ch.get("field")) is None or not _bi(ch.get("label")):
            errs.append("profile.prior_year_charge 需要登记的说明 id、approx 中的字段与中英文 label")
    if (no or ch) and not _bi(cal.get("ex_items")):
        errs.append("profile.calibers.ex_items 需要中英文（示意算术的口径）")
    gr = p.get("guidance_remaining")
    if gr and (gr.get("guidance") not in [g.get("id") for g in reg.get("guidance") or []] or not _bi(gr.get("caliber")) or not _bi(gr.get("label")) or not ytd):
        errs.append("profile.guidance_remaining 需要登记的展望 id、中英文 label 与 caliber，以及 year_to_date")
    if reg.get("rpo"):
        series = (p.get("rpo") or {}).get("series") or []
        pts = reg["rpo"].get("points") or []
        if not series or any(not _bi(sr.get("label")) or any(sr.get("key") not in pt for pt in pts) for sr in series):
            errs.append("profile.rpo.series 需要中英文 label，且 key 在每个积压订单时点中")
    if reg.get("per_share"):
        ref = p.get("per_share") or {}
        if set(ref) != {"current", "prior"} or any(v not in reg["per_share"] for v in ref.values()):
            errs.append("profile.per_share 需要 current 与 prior，指向 per_share 中的字段")
    return errs


def check(root: Path, registry: dict[str, dict[str, Any]] | None = None) -> Report:
    """核对全部财报登记；有任何错误时证据包不生成。"""
    rep = Report()
    registry = load_earnings(root) if registry is None else registry
    for eid, reg in registry.items():
        for key in ("entity", "company", "as_of", "documents", "income", "cash_flow", "balance", "notes", "coverage"):
            if not reg.get(key):
                rep.errors.append(f"{eid}：缺少 {key}")
        rep.errors += [f"{eid}：{x}" for x in profile_errors(reg)]
        if rep.errors:
            continue
        p = reg["profile"]
        mets = list(p["income_metrics"])
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

        for pid, per in reg["income"].items():
            miss = [m for m in mets if m not in per.get("values", {})]
            if miss:
                rep.errors.append(f"{eid}：{pid} 缺少 {'、'.join(miss)}")
                continue
            for m in mets:
                has(per["document"], per["values"][m], f"{pid}.{m}")
            _identities(f"{eid}：{pid}", per["values"], rep, p["identities"])
        for q in p["quarters"]:
            d = q.get("derive")
            if d and not rep.errors:
                derived = sub(reg["income"][d["total"]]["values"], reg["income"][d["less"]]["values"])
                _identities(f"{eid}：{q['name']['zh']}（{d['method']['zh']}）", derived, rep, p["identities"])
        for pid, per in reg["cash_flow"].items():
            for m in cash_metrics(p):
                has(per["document"], per[m], f"现金流 {pid}.{m}")
        fcf = reg.get("issuer_fcf") or {}
        for pid in (k for k in fcf if k != "document"):
            if pid not in reg["cash_flow"]:
                rep.errors.append(f"{eid}：发行人自由现金流的期间 {pid} 不在 cash_flow 中")
                continue
            cf = reg["cash_flow"][pid]
            if free_cash_flow(cf, p) != fcf[pid]:
                rep.errors.append(f"{eid}：{pid} 的登记 FCF 公式不等于发行人披露的自由现金流")
            else:
                rep.checked["identities"] += 1
            has(fcf["document"], fcf[pid], f"发行人自由现金流 {pid}")
        for date_, b in reg["balance"].items():
            for m in BALANCE_METRICS:
                if m not in b["values"]:
                    rep.errors.append(f"{eid}：资产负债表 {date_} 缺少 {m}")
                else:
                    has(b["document"], b["values"][m], f"资产负债表 {date_}.{m}")
        rpo = reg.get("rpo")
        for pt in (rpo or {}).get("points", []):
            for sr in p["rpo"]["series"]:
                has(pt["document"], pt[sr["key"]], f"积压订单 {pt['date']}.{sr['key']}")
        fx = reg.get("fx")
        for m in ("reported_revenue", "yoy_constant_currency_revenue", "qoq_constant_currency_revenue"):
            if fx:
                has(fx["document"], fx[m], f"恒定汇率 {m}")
        ps = reg.get("per_share")
        for m in (p.get("per_share") or {}).values() if ps else ():
            if ps["document"] in texts and not re.search(rf"(?<![\d.]){re.escape(format(ps[m], '.2f'))}(?!\d)", texts[ps['document']]):
                rep.errors.append(f"{eid}：每股收益 {ps[m]} 没有出现在原文 {ps['document']} 中")
            else:
                rep.checked["values"] += 1
        if reg.get("annual_cash_ppe"):
            has(reg["annual_cash_ppe"]["document"], reg["annual_cash_ppe"]["value"], f"{reg['annual_cash_ppe']['year']} 年现金资本开支")

        def excerpt(doc_id: str, text: str, where: str) -> None:
            if doc_id not in docs:
                rep.errors.append(f"{eid}：{where} 引用的原文 {doc_id} 未登记")
            elif doc_id in texts:
                if _norm(text) in texts[doc_id]:
                    rep.checked["excerpts"] += 1
                else:
                    rep.errors.append(f"{eid}：{where} 的摘录没有逐字出现在原文 {doc_id} 中")

        ids = set()
        for g in reg.get("guidance") or []:
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
        if reg.get("guidance") and not reg.get("annual_cash_ppe"):
            rep.errors.append(f"{eid}：有资本开支展望时需要 annual_cash_ppe（展望目标年的实际现金资本开支）")
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
            chk = n.get("check") or {}
            for k in (k for k in chk if k != "document"):
                has(chk["document"], chk[k], f"{where} 的 {k}")
        rec = (rpo or {}).get("recognition")
        if rec:
            excerpt(rec["document"], rec["excerpt"], "积压订单确认期限")
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
            for m in reg["profile"]["income_metrics"]:
                add("income", pid, m, p["values"][m], p["end"], p["document"])
        for pid, p in reg["cash_flow"].items():
            for m in cash_metrics(reg["profile"]):
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
            "related_studies": reg.get("related_studies", []), "profile": reg["profile"], "issuer_fcf": reg.get("issuer_fcf"),
            "rpo": reg.get("rpo"), "fx": reg.get("fx"), "per_share": reg.get("per_share"),
            "annual_cash_ppe": reg.get("annual_cash_ppe"), "guidance": reg.get("guidance") or [], "notes": reg["notes"],
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
