"""研究分支：公司季度财报（docs/study-earnings.md）。

只读取固定的财报证据包（earnings_evidence），不直接读登记文件；公司之间的差异（季度列、分部、比率、恒等式、页面行、
关键发现措辞）全部来自登记里的 profile，随证据包进入结果（results.profile），代码里不写死任何公司：
- 各季度的合并利润表、分部、利润率与现金流；没有直接披露的季度由全年减前几季度推出，结果里标明推导
- 同比与环比；分部营业利润变动合计等于营业利润变动（算术分解，不是因果）
- 示意性的税前局部剔除算术（可选）：不是发行人的正常化盈利，也不是预测
- 资产负债表时点、收入积压订单、恒定汇率对账、资本开支展望与实际的对照（后三项可选）
- 可比性说明与覆盖分类（已完成、数据不足、需人工判断）

不判断估值、不预测、不作投资建议；不称有机增长，除非发行人披露了并购等因素的收入桥。
"""

from __future__ import annotations

from typing import Any

from ..contracts import ResultType
from ..earnings import sub
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from .base import ResearchResult, StudyInput, input_record, register_branch

# 口径说明：这两条对所有公司相同；示意算术与剩余额算术的口径随公司写在 profile.calibers
CALIBER = {
    "segment_delta": {"zh": "分部营业利润同比变动合计等于营业利润变动，只是算术分解；不区分价格、规模、产品组合或并购等原因。",
                      "en": "Year-over-year changes of segment operating income sum to the change in operating income; this is an arithmetic split only and "
                            "does not separate pricing, scale, product mix or acquisitions."},
    "fcf": {"zh": "自由现金流按发行人定义：经营活动现金流减购置固定资产的现金支出。不是可分配现金，也未计入有价证券买卖、并购与融资。",
            "en": "Free cash flow as the issuer defines it: operating cash flow less cash purchases of property and equipment. Not distributable cash; "
                  "purchases of securities, acquisitions and financing are outside it."},
}
NUMERALS = "零一二三四五六七八九十"
NUMERALS_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


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


def quarter_rows(table: dict[tuple[str, str], dict[str, float]], p: dict[str, Any]) -> list[dict[str, Any]]:
    """profile.quarters 的各季度合并指标；没有直接披露的季度 = derive.total − derive.less（推导）。"""
    rows = []
    for q in p["quarters"]:
        d = q.get("derive")
        v = sub(table[("income", d["total"])], table[("income", d["less"])]) if d else table[("income", q["id"])]
        c = table[("cash_flow", q["id"])]
        r: dict[str, Any] = {"period": q["id"], "label": q["label"], "end": q["end"], "derived": bool(d), **v,
                             "cfo": c["cfo"], "cash_ppe": c["cash_ppe"], "free_cash_flow": c["cfo"] - c["cash_ppe"]}
        r["gross_profit"] = v["revenue"] - v["cost_of_revenues"]
        r["gross_margin"] = _ratio(r["gross_profit"], v["revenue"])
        r["op_margin"] = _ratio(v["op_income"], v["revenue"])
        for ratio in p.get("ratios") or []:
            r[ratio["key"]] = _ratio(v[ratio["num"]], v[ratio["den"]])
        r["capex_to_sales"] = _ratio(c["cash_ppe"], v["revenue"])
        r["cfo_to_consolidated_ni"] = (c["cfo"] / v["consolidated_NI"]) if v["consolidated_NI"] > 0 else None
        if p.get("non_operating"):
            r["ebt_ex_equity_securities"] = v["EBT"] - v[p["non_operating"]["key"]]
        rows.append(r)
    return rows


def comparisons(rows: list[dict[str, Any]], p: dict[str, Any]) -> dict[str, Any]:
    by = {r["period"]: r for r in rows}
    cur = by[p["current"]]
    out: dict[str, Any] = {}
    for name, base in (("yoy", by[p["yoy_base"]]), ("qoq", by[p["qoq_base"]])):
        out[name] = {"base": base["label"], "current": cur["label"],
                     "pct": {m: _pct(cur[m], base[m]) for m in p["growth"]},
                     "margin_pp": {m: (cur[m] - base[m]) if cur[m] is not None and base[m] is not None else None for m in p["margins"]}}
    if p.get("segment_ops"):
        prior = by[p["yoy_base"]]
        delta = {m: cur[m] - prior[m] for m in p["segment_ops"]}
        total = cur["op_income"] - prior["op_income"]
        out["segment_op_delta_yoy"] = {"delta": delta, "total": total, "reconciles": sum(delta.values()) == total,
                                       "caliber": (p.get("calibers") or {}).get("segment_delta") or CALIBER["segment_delta"]}
    return out


def bridges(rows: list[dict[str, Any]], notes: list[dict[str, Any]], p: dict[str, Any]) -> dict[str, Any] | None:
    """示意性的税前算术：剔除非经营项目、加回上年同期一次性费用。没有配置时为 None。"""
    no, ch = p.get("non_operating"), p.get("prior_year_charge")
    if not no and not ch:
        return None
    by = {r["period"]: r for r in rows}
    out: dict[str, Any] = {"estimate": True, "caliber": p["calibers"]["ex_items"]}
    if no:
        out["ebt_ex_equity_securities"] = {r["period"]: r["ebt_ex_equity_securities"] for r in rows}
        out["equity_security_gain_loss"] = {r["period"]: r[no["key"]] for r in rows}
    fine = None
    if ch:
        fine = next((n for n in notes if n["id"] == ch["note"]), {}).get("approx", {}).get(ch["field"])
    if fine:
        prior, cur = by[p["yoy_base"]], by[p["current"]]
        adj = prior["op_income"] + fine
        out["prior_year_charge_usd_m"] = fine
        out["prior_op_income_plus_charge"] = adj
        out["prior_op_margin_plus_charge"] = _ratio(adj, prior["revenue"])
        out["current_op_income_vs_prior_plus_charge_pct"] = _pct(cur["op_income"], adj)
        out["current_vs_prior_margin_pp"] = cur["op_margin"] - out["prior_op_margin_plus_charge"]
    return out


def cash_conversion(rows: list[dict[str, Any]], table: dict[tuple[str, str], dict[str, float]], fcf: dict[str, Any] | None,
                    p: dict[str, Any]) -> dict[str, Any]:
    by = {r["period"]: r for r in rows}
    out: dict[str, Any] = {"current_free_cash_flow": by[p["current"]]["free_cash_flow"],
                           "issuer_fcf": {k: v for k, v in (fcf or {}).items() if k != "document"}, "caliber": CALIBER["fcf"]}
    ytd = p.get("year_to_date")
    if ytd:
        cf = table[("cash_flow", ytd["id"])]
        ni = sum(by[q]["consolidated_NI"] for q in ytd["quarters"])
        out["year_to_date"] = {"cfo": cf["cfo"], "cash_ppe": cf["cash_ppe"], "consolidated_ni": ni,
                               "cfo_to_consolidated_ni": cf["cfo"] / ni if ni > 0 else None,
                               "cfo_to_cash_ppe": cf["cfo"] / cf["cash_ppe"], "label": ytd["label"]}
    if p.get("trailing"):
        t = table[("cash_flow", p["trailing"])]
        out["trailing"] = {"cfo": t["cfo"], "cash_ppe": t["cash_ppe"], "free_cash_flow": t["cfo"] - t["cash_ppe"]}
    return out


def balance_rows(table: dict[tuple[str, str], dict[str, float]]) -> list[dict[str, Any]]:
    out = []
    for (kind, date_), v in sorted(table.items(), key=lambda kv: kv[0][1], reverse=True):
        if kind != "balance":
            continue
        out.append({"date": date_, **v, "cash_and_securities": v["cash"] + v["marketable_securities"]})
    return out


def rpo_rows(rpo: dict[str, Any] | None, p: dict[str, Any]) -> dict[str, Any] | None:
    if not rpo:
        return None
    pts = sorted(rpo["points"], key=lambda x: x["date"])
    keys = [sr["key"] for sr in p["rpo"]["series"]]
    rows = []
    for i, pt in enumerate(pts):
        rows.append({**pt, **{f"{k}_qoq_pct": _pct(pt[k], pts[i - 1][k]) if i else None for k in keys}})
    return {"unit": rpo["unit"], "points": rows, "recognition": rpo.get("recognition"), "scope_change": rpo["scope_change"]}


def guidance_rows(guidance: list[dict[str, Any]], actual: dict[str, Any] | None, ytd_cash_ppe: float | None,
                  p: dict[str, Any]) -> dict[str, Any] | None:
    if not guidance or not actual:
        return None
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
    rem = p.get("guidance_remaining")
    base = next((g for g in guidance if rem and g["id"] == rem["guidance"]), None)
    ytd = ytd_cash_ppe / 1000 if ytd_cash_ppe is not None else 0.0
    remaining = ({"guidance": base["id"], "target_year": base["target_year"], "low_usd_bn": base["low_usd_bn"] - ytd,
                  "high_usd_bn": base["high_usd_bn"] - ytd, "year_to_date_cash_ppe_usd_bn": ytd,
                  "estimate": True, "caliber": rem["caliber"]} if base else None)
    return {"observations": rows, "actual": actual, "remaining_arithmetic": remaining,
            "tolerance_note": {"zh": "点值展望没有定义容差，只给出实际值与点值的差，不判定「达成」或「未达成」。",
                               "en": "Point outlooks define no tolerance, so only the difference between actual and point is shown; no 'met' or 'missed' verdict."}}


def method_text(p: dict[str, Any], n_quarters: int) -> dict[str, str]:
    """方法说明（中英文），由 profile 的季度名与可选的推导、示意算术说明拼出。"""
    by = {q["id"]: q for q in p["quarters"]}
    derived = [q for q in p["quarters"] if q.get("derive")]
    n = NUMERALS[n_quarters] if n_quarters <= 10 else str(n_quarters)
    n_en = NUMERALS_EN[n_quarters].capitalize() if n_quarters <= 10 else str(n_quarters)
    zh = (f"从固定的财报证据包读取{n}个季度的合并利润表、分部与现金流（报告口径，百万美元）；"
          + "".join(f"{q['name']['zh']}由{q['derive']['method']['zh']}推出。" for q in derived)
          + f"利润率为占同期收入的比例；同比对 {by[p['yoy_base']]['name']['zh']}，环比对 {by[p['qoq_base']]['name']['zh']}；自由现金流按发行人定义。")
    en = (f"{n_en} quarters of consolidated results, segments and cash flow are read from a fixed evidence bundle (reported basis, USD millions); "
          + "".join(f"{q['name']['en']} is derived as {q['derive']['method']['en']}. " for q in derived)
          + f"Margins are percent of same-period revenue; year over year compares with {by[p['yoy_base']]['name']['en']} and quarter over quarter with "
            f"{by[p['qoq_base']]['name']['en']}; free cash flow follows the issuer definition. ")
    clause = p.get("bridge_clause")
    if clause:
        zh += clause["zh"]
        en += clause["en"] + " "
    return {"zh": zh + "不称有机增长，不估值、不预测。", "en": en + "No organic growth, valuation or forecast is stated."}


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
    p = reg.get("profile")
    if not p:
        raise ValueError(f"财报证据包中的 {earnings_id} 没有 profile；用 iros earnings bundle 重新生成")
    rows = quarter_rows(table, p)
    comp = comparisons(rows, p)
    notes = reg["notes"]
    ytd = p.get("year_to_date")
    guidance = guidance_rows(reg["guidance"], reg.get("annual_cash_ppe"), table[("cash_flow", ytd["id"])]["cash_ppe"] if ytd else None, p)
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
        "related_studies": reg.get("related_studies", []), "profile": p,
        "quarters": rows, "comparison": comp, "bridges": bridges(rows, notes, p),
        "cash": cash_conversion(rows, table, reg.get("issuer_fcf"), p), "balance": balance_rows(table),
        "rpo": rpo_rows(reg.get("rpo"), p), "fx": reg.get("fx"), "per_share": reg.get("per_share"), "guidance": guidance,
        "notes": notes, "coverage": coverage_items, "documents": reg["documents"],
        "summary": {"quarters": len(rows), "derived_quarters": sum(r["derived"] for r in rows), "notes": len(notes),
                    "coverage": {s: sum(c["status"] == s for c in coverage_items) for s in ("done", "data_gap", "judgment")}},
    }
    return ResearchResult(
        study_id=study.study_id, title=study.title, question=study.question, result_type=study.result_type,
        branch=study.branch, scope=study.scope, data_cutoff=max(published) if published else None,
        methods={
            "description": method_text(p, len(rows))["zh"],
            "parameters": {"earnings": earnings_id},
            "bundle": {k: bundle.get(k) for k in ("built_at", "earnings_files")},
        },
        inputs=[input_record(inp)], results=results,
        coverage={"completeness": "partial", "period_complete": True, "quarters": len(rows),
                  "coverage_items": results["summary"]["coverage"]},
        unsupported=unsupported, limitations=list(study.limitations), validation=validation,
        tables={"quarters": [{k: r[k] for k in ("period", "label", "revenue", "op_income", "consolidated_NI", "cfo", "cash_ppe")} for r in rows]},
    )
