"""研究分支：公司季度财报（docs/study-earnings.md）。

只读取固定的财报证据包（earnings_evidence），不直接读登记文件：
- 五个季度（2025 年第三季度至 2026 年第三季度）的合并利润表、分部、利润率与现金流；2025 年第四季度由全年减前三季度推出，
  不是申报中的直接季度值，结果里标明推导
- 同比（对 2025 年第三季度）与环比（对 2026 年第二季度）；分部营业利润变动合计等于营业利润变动（算术分解，不是因果）
- 示意性的税前局部剔除算术（权益证券损益、去年同期欧盟罚款）：不是发行人的正常化盈利，也不是预测
- 资产负债表时点、收入积压订单、恒定汇率对账、资本开支展望与实际的对照
- 可比性说明与覆盖分类（已完成、数据不足、需人工判断）

不判断估值、不预测、不作投资建议；不称有机增长，因为发行人没有披露并购与 TPU 系统销售的收入桥。
"""

from __future__ import annotations

from typing import Any

from ..contracts import ResultType
from ..earnings import QUARTERS, sub
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from .base import ResearchResult, StudyInput, input_record, register_branch

QUARTER_LABEL = {"q3_2025": "2025 Q3", "q4_2025": "2025 Q4", "q1_2026": "2026 Q1", "q2_2026": "2026 Q2", "q3_2026": "2026 Q3"}
QUARTER_END = {"q3_2025": "2025-09-30", "q4_2025": "2025-12-31", "q1_2026": "2026-03-31", "q2_2026": "2026-06-30", "q3_2026": "2026-09-30"}
GROWTH_METRICS = ("revenue", "Search", "YouTube_ads", "Network", "subscriptions_platforms_devices", "Services_revenue", "Cloud_revenue",
                  "OtherBets_revenue", "cost_of_revenues", "R_and_D", "sales_marketing", "G_and_A", "op_income", "EBT", "income_tax",
                  "consolidated_NI", "common_NI", "cfo", "cash_ppe")
MARGINS = ("gross_margin", "op_margin", "Services_margin", "Cloud_margin")
SEGMENT_OPS = ("Services_op", "Cloud_op", "OtherBets_op", "Alphabet_level_op")

CALIBER = {
    "ex_items": {"zh": "示意性的税前算术：税前利润减权益证券损益；营业利润加去年同期约 35 亿美元的欧盟相关费用。不是发行人的正常化盈利、"
                       "不含税率调整、不是预测；约数来自原文的四舍五入披露。",
                 "en": "Illustrative pretax arithmetic: pretax income less equity-security gains and losses; operating income plus the roughly USD 3.5 bn "
                       "EU-related charge of the prior-year quarter. Not issuer-normalised earnings, no tax adjustment, not a forecast; the "
                       "approximate amount comes from the filing's rounded disclosure."},
    "segment_delta": {"zh": "分部营业利润同比变动合计等于营业利润变动，只是算术分解；不区分 TPU 销售、服务消耗、价格或规模效应。",
                      "en": "Year-over-year changes of segment operating income sum to the change in operating income; this is an arithmetic split only and "
                            "does not separate TPU sales, service consumption, pricing or scale effects."},
    "remaining_capex": {"zh": "二月公布的全年区间减去前三季度现金资本开支，是同口径的剩余额算术，不是公司对第四季度的指引，也不是对现金支出路径的预测。",
                        "en": "The February full-year range less nine-month cash capital expenditure is same-definition residual arithmetic; it is neither "
                              "company guidance for Q4 nor a forecast of the cash-spend path."},
    "fcf": {"zh": "自由现金流按发行人定义：经营活动现金流减购置固定资产的现金支出。不是可分配现金，也未计入有价证券买卖、并购与融资。",
            "en": "Free cash flow as the issuer defines it: operating cash flow less cash purchases of property and equipment. Not distributable cash; "
                  "purchases of securities, acquisitions and financing are outside it."},
}


def _pct(a: float | None, b: float | None) -> float | None:
    return None if a is None or b in (None, 0) or b < 0 else (a / b - 1) * 100


def _ratio(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b or b <= 0 else a / b * 100


def _load(inp: StudyInput, earnings_id: str) -> tuple[dict[tuple[str, str], dict[str, float]], dict[str, Any], dict[str, Any]]:
    meta = inp.version.series
    bundle = meta.get("_bundle") or {}
    rows = ok_rows(inp.frame)
    values = dict(zip(rows["series_id"], rows["value"].astype(float)))
    table: dict[tuple[str, str], dict[str, float]] = {}
    for sid, m in meta.items():
        if sid == "_bundle" or sid not in values or m.get("earnings") != earnings_id:
            continue
        table.setdefault((m["record"], m["period"]), {})[m["metric"]] = values[sid]
    return table, bundle, (bundle.get("earnings") or {}).get(earnings_id) or {}


def quarter_rows(table: dict[tuple[str, str], dict[str, float]]) -> list[dict[str, Any]]:
    """五个季度的合并指标。2025 年第四季度 = 全年 − 前三季度（推导）。"""
    inc = {p: table[("income", p)] for p in ("q3_2025", "q1_2026", "q2_2026", "q3_2026")}
    inc["q4_2025"] = sub(table[("income", "fy_2025")], table[("income", "nine_months_2025")])
    cash = {p: table[("cash_flow", p)] for p in QUARTERS}
    rows = []
    for q in QUARTERS:
        v, c = inc[q], cash[q]
        r: dict[str, Any] = {"period": q, "label": QUARTER_LABEL[q], "end": QUARTER_END[q], "derived": q == "q4_2025", **v,
                             "cfo": c["cfo"], "cash_ppe": c["cash_ppe"], "free_cash_flow": c["cfo"] - c["cash_ppe"]}
        r["gross_profit"] = v["revenue"] - v["cost_of_revenues"]
        r["gross_margin"] = _ratio(r["gross_profit"], v["revenue"])
        r["op_margin"] = _ratio(v["op_income"], v["revenue"])
        r["Services_margin"] = _ratio(v["Services_op"], v["Services_revenue"])
        r["Cloud_margin"] = _ratio(v["Cloud_op"], v["Cloud_revenue"])
        r["OtherBets_margin"] = _ratio(v["OtherBets_op"], v["OtherBets_revenue"])
        r["Services_share"] = _ratio(v["Services_revenue"], v["revenue"])
        r["Cloud_share"] = _ratio(v["Cloud_revenue"], v["revenue"])
        r["Alphabet_level_op_to_sales"] = _ratio(v["Alphabet_level_op"], v["revenue"])
        r["capex_to_sales"] = _ratio(c["cash_ppe"], v["revenue"])
        r["cfo_to_consolidated_ni"] = (c["cfo"] / v["consolidated_NI"]) if v["consolidated_NI"] > 0 else None
        r["ebt_ex_equity_securities"] = v["EBT"] - v["equity_security_gain_loss"]
        rows.append(r)
    return rows


def comparisons(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = {r["period"]: r for r in rows}
    cur = by["q3_2026"]
    out: dict[str, Any] = {}
    for name, base in (("yoy", by["q3_2025"]), ("qoq", by["q2_2026"])):
        out[name] = {"base": base["label"], "current": cur["label"],
                     "pct": {m: _pct(cur[m], base[m]) for m in GROWTH_METRICS},
                     "margin_pp": {m: (cur[m] - base[m]) if cur[m] is not None and base[m] is not None else None for m in MARGINS}}
    prior = by["q3_2025"]
    delta = {m: cur[m] - prior[m] for m in SEGMENT_OPS}
    total = cur["op_income"] - prior["op_income"]
    out["segment_op_delta_yoy"] = {"delta": delta, "total": total, "reconciles": sum(delta.values()) == total,
                                   "caliber": CALIBER["segment_delta"]}
    return out


def bridges(rows: list[dict[str, Any]], notes: list[dict[str, Any]]) -> dict[str, Any]:
    by = {r["period"]: r for r in rows}
    fine = next((n for n in notes if n["id"] == "ec_fine"), {}).get("approx", {}).get("prior_year_charge_usd_m")
    out: dict[str, Any] = {"estimate": True, "caliber": CALIBER["ex_items"],
                           "ebt_ex_equity_securities": {r["period"]: r["ebt_ex_equity_securities"] for r in rows},
                           "equity_security_gain_loss": {r["period"]: r["equity_security_gain_loss"] for r in rows}}
    if fine:
        prior, cur = by["q3_2025"], by["q3_2026"]
        adj = prior["op_income"] + fine
        out["prior_year_charge_usd_m"] = fine
        out["prior_op_income_plus_charge"] = adj
        out["prior_op_margin_plus_charge"] = _ratio(adj, prior["revenue"])
        out["current_op_income_vs_prior_plus_charge_pct"] = _pct(cur["op_income"], adj)
        out["current_vs_prior_margin_pp"] = cur["op_margin"] - out["prior_op_margin_plus_charge"]
    return out


def cash_conversion(rows: list[dict[str, Any]], table: dict[tuple[str, str], dict[str, float]], fcf: dict[str, Any]) -> dict[str, Any]:
    by = {r["period"]: r for r in rows}
    nine = table[("cash_flow", "nine_months_2026")]
    ni9 = sum(by[q]["consolidated_NI"] for q in ("q1_2026", "q2_2026", "q3_2026"))
    ttm = table[("cash_flow", "ttm_2026q3")]
    return {"nine_months": {"cfo": nine["cfo"], "cash_ppe": nine["cash_ppe"], "consolidated_ni": ni9,
                            "cfo_to_consolidated_ni": nine["cfo"] / ni9 if ni9 > 0 else None,
                            "cfo_to_cash_ppe": nine["cfo"] / nine["cash_ppe"]},
            "ttm": {"cfo": ttm["cfo"], "cash_ppe": ttm["cash_ppe"], "free_cash_flow": ttm["cfo"] - ttm["cash_ppe"]},
            "q3_free_cash_flow": by["q3_2026"]["free_cash_flow"], "issuer_fcf": {k: v for k, v in fcf.items() if k != "document"},
            "caliber": CALIBER["fcf"]}


def balance_rows(table: dict[tuple[str, str], dict[str, float]]) -> list[dict[str, Any]]:
    out = []
    for (kind, date_), v in sorted(table.items(), key=lambda kv: kv[0][1], reverse=True):
        if kind != "balance":
            continue
        out.append({"date": date_, **v, "cash_and_securities": v["cash"] + v["marketable_securities"]})
    return out


def rpo_rows(rpo: dict[str, Any]) -> dict[str, Any]:
    pts = sorted(rpo["points"], key=lambda p: p["date"])
    rows = []
    for i, p in enumerate(pts):
        rows.append({**p, "total_qoq_pct": _pct(p["total"], pts[i - 1]["total"]) if i else None,
                     "cloud_qoq_pct": _pct(p["cloud"], pts[i - 1]["cloud"]) if i else None})
    return {"unit": rpo["unit"], "points": rows, "recognition": rpo["recognition"], "scope_change": rpo["scope_change"]}


def guidance_rows(guidance: list[dict[str, Any]], actual: dict[str, Any], nine_months_cash_ppe: float) -> dict[str, Any]:
    actual_bn = actual["value"] / 1000
    rows = []
    for g in guidance:
        r = {k: g.get(k) for k in ("id", "announced", "target_year", "kind", "statement", "excerpt", "document")}
        r["low_usd_bn"], r["high_usd_bn"], r["point_usd_bn"] = g.get("low_usd_bn"), g.get("high_usd_bn"), g.get("point_usd_bn")
        r["actual_usd_bn"] = actual_bn if g["target_year"] == actual["year"] else None
        if g["target_year"] != actual["year"]:
            r["result"] = "pending" if g["target_year"] > actual["year"] else "not_comparable"
        elif g["kind"] == "point":
            r["result"] = "difference_only"
            r["difference_usd_bn"] = actual_bn - g["point_usd_bn"]
        elif g["kind"] == "range":
            r["result"] = ("within_range" if g["low_usd_bn"] <= actual_bn <= g["high_usd_bn"]
                           else "above_range" if actual_bn > g["high_usd_bn"] else "below_range")
            r["difference_usd_bn"] = actual_bn - (g["low_usd_bn"] + g["high_usd_bn"]) / 2
        else:
            r["result"] = "not_comparable"
        rows.append(r)
    feb = next((g for g in guidance if g["id"] == "g_2026_feb"), None)
    nine = nine_months_cash_ppe / 1000
    remaining = ({"low_usd_bn": feb["low_usd_bn"] - nine, "high_usd_bn": feb["high_usd_bn"] - nine, "nine_months_cash_ppe_usd_bn": nine,
                  "estimate": True, "caliber": CALIBER["remaining_capex"]} if feb else None)
    return {"observations": rows, "actual": actual, "remaining_2026_arithmetic": remaining,
            "tolerance_note": {"zh": "点值展望没有定义容差，只给出实际值与点值的差，不判定「达成」或「未达成」。",
                               "en": "Point outlooks define no tolerance, so only the difference between actual and point is shown; no 'met' or 'missed' verdict."}}


@register_branch("earnings_quarter", result_types=(ResultType.DESCRIPTIVE,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    inp = inputs["evidence"]
    earnings_id = study.method["earnings"]
    table, bundle, reg = _load(inp, earnings_id)
    check = bundle.get("check") or {}
    if check.get("errors"):
        raise ValueError("财报证据包的登记核对有错误，不能使用：" + "；".join(check["errors"][:3]))
    if not reg or not table:
        raise ValueError(f"财报证据包中没有 {earnings_id}")
    rows = quarter_rows(table)
    comp = comparisons(rows)
    notes = reg["notes"]
    guidance = guidance_rows(reg["guidance"], reg["annual_cash_ppe"], table[("cash_flow", "nine_months_2026")]["cash_ppe"])
    coverage_items = reg["coverage"]
    unsupported = [{"item": c["item"]["zh"], "kind": "data" if c["status"] == "data_gap" else "scope",
                    "reason": ("发行人没有披露所需数据，或本研究没有取得可核验的数据" if c["status"] == "data_gap"
                               else "需要人工判断或本研究未处理的外部材料；不在公开财报算术的范围内")}
                   for c in coverage_items if c["status"] != "done"]
    published = [m["published_at"] for sid, m in inp.version.series.items() if sid != "_bundle" and m.get("earnings") == earnings_id]
    checked = check.get("checked") or {}
    validation = {"evidence_check": {
        "status": "pass", "checked": sum(checked.values()),
        "reason": "证据包生成前逐份核对原文 SHA256、数值出现在所引原文中、会计恒等式成立、文字摘录逐字出现在原文中"}}
    results = {
        "company": {"entity": reg["entity"], "name": reg["company"], "cik": reg["cik"], "tickers": reg["tickers"]},
        "latest_period": reg["latest_period"], "as_of": reg["as_of"], "release": reg["release"],
        "related_studies": reg.get("related_studies", []),
        "quarters": rows, "comparison": comp, "bridges": bridges(rows, notes),
        "cash": cash_conversion(rows, table, reg["issuer_fcf"]), "balance": balance_rows(table),
        "rpo": rpo_rows(reg["rpo"]), "fx": reg["fx"], "per_share": reg["per_share"], "guidance": guidance,
        "notes": notes, "coverage": coverage_items, "documents": reg["documents"],
        "summary": {"quarters": len(rows), "derived_quarters": sum(r["derived"] for r in rows), "notes": len(notes),
                    "coverage": {s: sum(c["status"] == s for c in coverage_items) for s in ("done", "data_gap", "judgment")}},
    }
    return ResearchResult(
        study_id=study.study_id, title=study.title, question=study.question, result_type=study.result_type,
        branch=study.branch, scope=study.scope, data_cutoff=max(published) if published else None,
        methods={
            "description": "从固定的财报证据包读取五个季度的合并利润表、分部与现金流（报告口径，百万美元）；2025 年第四季度由全年减前三季度推出。"
                           "利润率为占同期收入的比例；同比对 2025 年第三季度，环比对 2026 年第二季度；自由现金流按发行人定义。"
                           "权益证券损益与去年同期罚款的剔除只是税前示意算术。不称有机增长，不估值、不预测。",
            "parameters": {"earnings": earnings_id},
            "bundle": {k: bundle.get(k) for k in ("built_at", "earnings_files")},
        },
        inputs=[input_record(inp)], results=results,
        coverage={"completeness": "partial", "period_complete": True, "quarters": len(rows),
                  "coverage_items": results["summary"]["coverage"]},
        unsupported=unsupported, limitations=list(study.limitations), validation=validation,
        tables={"quarters": [{k: r[k] for k in ("period", "label", "revenue", "op_income", "consolidated_NI", "cfo", "cash_ppe")} for r in rows]},
    )
