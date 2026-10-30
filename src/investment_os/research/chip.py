"""研究分支：芯片经营分析（P3b；docs/supply-chain-research-design.md §8，docs/study-chips.md）。

只读取固定的芯片证据包（chip_segment_evidence），按研究单元逐一评估与计算：
- 每个单元的全部数字取自同一份年度申报（最新的、覆盖所需分部 × 指标 × 财年的 10-K），
  不跨申报拼接，因此不会混用分部重组前后的口径或后来修订的比较数
- 所需指标在证据包中没有观测（如型号出货量、供应商份额）时为 C，不按收入或假设单价推算
- 分部合计核对：同一申报各分部（含 AllOtherSegments）营收之和与合并营收比较；没有合并营收时跳过，不冒充通过；
  合并营收有多个值时判为冲突
- 毛利核对：分部报告了 GrossProfit 时，与营收减销售成本比较；任一项有多个值时判为冲突，不当作缺失跳过

输入能力等级只评价分部财务输入；分部到芯片活动的归属另记 attribution_status（只看指向本单元活动的有效映射）：
全部人工确认为 confirmed，全部经技术复核（或人工确认）为 reviewed，否则为 candidate。reviewed 不等于人工签认。
不论复核状态，partial 映射与未登记的有效期都作为限制保留：结果按分部口径陈述，不按活动分摊收入。
证据包带有技术复核记录时，结果另列各映射的结论边界（旧证据包没有该记录，结果结构不变）。
"""

from __future__ import annotations

from typing import Any

from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from .base import ResearchResult, StudyInput, input_record, register_branch
from .feasibility import assess

REVENUE_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
OPERATING_INCOME = "OperatingIncomeLoss"
COST_OF_REVENUE = "CostOfGoodsAndServicesSold"
GROSS_PROFIT = "GrossProfit"
TOL_USD = 1.0  # 同一申报内的加总核对：申报值为整数美元，差额超过 1 美元即不一致


def _records(inp: StudyInput) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """证据包的记录（附标准化值）与元数据；记录元数据与值都来自固定版本。"""
    meta = inp.version.series
    bundle = meta.get("_bundle") or {}
    rows = ok_rows(inp.frame)
    values = dict(zip(rows["series_id"], rows["value"].astype(float)))
    out = []
    for sid, m in meta.items():
        if sid == "_bundle" or sid not in values:
            continue
        out.append({**m, "value": values[sid]})
    return out, bundle


def _unique(values: list[float]) -> tuple[float | None, bool]:
    """同一对象的多行（同一分部的两种维度写法）数值须一致；不一致返回冲突。"""
    distinct = sorted(set(values))
    return (distinct[0], False) if len(distinct) == 1 else (None, len(distinct) > 1)


def _select_filing(recs: list[dict[str, Any]], entities: list[str], tags: list[str],
                   years: list[int]) -> tuple[str | None, dict[tuple[str, str, int], float], list[str]]:
    """从最新申报往回找第一份覆盖全部分部 × 指标 × 财年且没有冲突的年度申报。"""
    notes = []
    by_acc: dict[str, list[dict[str, Any]]] = {}
    for r in recs:
        if r["kind"] == "segment" and r["entity"] in entities and r["tag"] in tags:
            by_acc.setdefault(r["accession"], []).append(r)
    order = sorted(by_acc, key=lambda a: max(r["available_at"] for r in by_acc[a]), reverse=True)
    for acc in order:
        cells: dict[tuple[str, str, int], list[float]] = {}
        for r in by_acc[acc]:
            cells.setdefault((r["entity"], r["tag"], r["fiscal_year"]), []).append(r["value"])
        need = [(e, t, y) for e in entities for t in tags for y in years]
        missing = [k for k in need if k not in cells]
        conflicts = [k for k in need if k in cells and _unique(cells[k])[1]]
        if missing or conflicts:
            notes.append(f"{acc}：缺 {len(missing)} 项、冲突 {len(conflicts)} 项"
                         + (f"（如 {missing[0]}）" if missing else ""))
            continue
        return acc, {k: _unique(cells[k])[0] for k in need}, notes
    return None, {}, notes


def _segment_total_check(recs: list[dict[str, Any]], acc: str, years: list[int]) -> list[dict[str, Any]]:
    """同一申报各分部营收（按成员去重）之和与合并营收比较。"""
    rows = []
    for y in years:
        seg: dict[str, list[float]] = {}
        period = None
        for r in recs:
            if r["accession"] == acc and r["kind"] in ("segment", "other_segment") and r["tag"] in REVENUE_TAGS \
                    and r["fiscal_year"] == y:
                seg.setdefault(r["member"], []).append(r["value"])
                period = r["period_end_month"]
        if not seg:
            continue
        members = {m: _unique(v) for m, v in seg.items()}
        if any(conflict for _, conflict in members.values()):
            rows.append({"fiscal_year": y, "status": "fail", "reason": "同一分部的营收有冲突"})
            continue
        total = sum(v for v, _ in members.values())
        cons = [r["value"] for r in recs if r["accession"] == acc and r["kind"] == "consolidated"
                and r["tag"] in REVENUE_TAGS and r["period_end_month"] == period]
        if not cons:
            rows.append({"fiscal_year": y, "status": "skipped", "segment_total": total, "segments": sorted(members),
                         "reason": "证据包中没有该申报的合并营收（公司不在 E1 财报登记中）"})
            continue
        consolidated, conflict = _unique(cons)
        if conflict:  # 同一申报同一期末的合并营收不止一个值：不挑其中吻合的一个
            rows.append({"fiscal_year": y, "status": "fail", "segment_total": total, "consolidated": sorted(set(cons)),
                         "segments": sorted(members), "reason": "同一申报同一期末的合并营收有冲突"})
            continue
        rows.append({"fiscal_year": y, "status": "pass" if abs(total - consolidated) <= TOL_USD else "fail",
                     "segment_total": total, "consolidated": consolidated, "segments": sorted(members)})
    return rows


def _gross_profit_check(recs: list[dict[str, Any]], acc: str, entities: list[str], years: list[int],
                        rev_tag: str) -> list[dict[str, Any]]:
    rows = []
    for e in entities:
        for y in years:
            found = {t: _unique([r["value"] for r in recs if r["accession"] == acc and r["entity"] == e
                                 and r["tag"] == t and r["fiscal_year"] == y])
                     for t in (rev_tag, COST_OF_REVENUE, GROSS_PROFIT)}
            conflicts = [t for t, (_, conflict) in found.items() if conflict]
            if conflicts:  # 冲突不同于缺失：不能跳过
                rows.append({"entity": e, "fiscal_year": y, "status": "fail",
                             "reason": f"{', '.join(conflicts)} 有冲突"})
                continue
            pick = {t: v for t, (v, _) in found.items()}
            if None in pick.values():
                continue  # 分部没有报告其中某项：不核对
            diff = pick[rev_tag] - pick[COST_OF_REVENUE] - pick[GROSS_PROFIT]
            rows.append({"entity": e, "fiscal_year": y, "diff": diff, "status": "pass" if abs(diff) <= TOL_USD else "fail"})
    return rows


USABLE_LINKS = ("confirmed", "reviewed", "candidate")


def _attribution(bundle: dict[str, Any], entities: list[str], activity: str) -> tuple[str, list[str]]:
    """只看指向本单元活动、且未被判为无效或人工否定 / 撤回的映射：指向其他活动的映射不说明本活动的归属。"""
    links = [(lid, lk) for lid, lk in (bundle.get("links") or {}).items()
             if lk["entity"] in entities and lk["activity"] == activity and lk["status"] in USABLE_LINKS]
    linked = {lk["entity"] for _, lk in links}
    if not links or linked != set(entities):
        return "unmapped", [lid for lid, _ in links]
    states = {lk["status"] for _, lk in links}
    status = ("confirmed" if states == {"confirmed"} else "reviewed" if states <= {"confirmed", "reviewed"}
              else "candidate")
    return status, [lid for lid, _ in links]


def _unit(spec: dict[str, Any], recs: list[dict[str, Any]], bundle: dict[str, Any],
          inp: StudyInput) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """一个研究单元：等级、所选申报、分部数字与派生比率、核对结果。"""
    entities, tags = list(spec["entities"]), list(spec["metrics"])
    y0, y1 = (int(x) for x in spec["period"]["fiscal_years"])
    years = list(range(y0, y1 + 1))
    known = {e for e, m in (bundle.get("entities") or {}).items() if m["type"] == "segment"}
    observed_tags = {r["tag"] for r in recs if r["kind"] == "segment"}
    hard, failed = [], []
    unobserved = [t for t in tags if t not in observed_tags]
    if unobserved:
        hard.append(f"所需指标 {', '.join(unobserved)} 在证据包中没有观测，也不在允许假设清单中；"
                    "不能用收入或假设单价推算")
    not_segment = [e for e in entities if e not in known]
    if not_segment and not unobserved:
        hard.append(f"主体 {', '.join(not_segment)} 不是登记的分部，没有分部财务")
    superseded = [e for e in entities if (bundle.get("entities") or {}).get(e, {}).get("superseded_in")]
    if superseded:
        hard.append(f"分部 {', '.join(superseded)} 已在重组后停用，不能与新口径混用")
    parents = {(bundle.get("entities") or {}).get(e, {}).get("parent") for e in entities}
    if len(parents) > 1 and not hard:
        hard.append(f"单元跨公司（{', '.join(sorted(map(str, parents)))}），分部数字不能直接合并")
    acc, values, notes = (None, {}, [])
    if not hard:
        acc, values, notes = _select_filing(recs, entities, tags, years)
        if acc is None:
            hard.append("没有一份年度申报同时覆盖全部分部、指标与财年且数值无冲突：" + "；".join(notes[:3]))
    checks: dict[str, Any] = {}
    if acc is not None:
        totals = _segment_total_check(recs, acc, years)
        rev_tag = next((t for t in tags if t in REVENUE_TAGS), None)
        gross = _gross_profit_check(recs, acc, entities, years, rev_tag) if rev_tag else []
        checks = {"segment_total": totals, "gross_profit": gross}
        bad = [f"{y['fiscal_year']} 财年分部营收合计与合并营收不一致" + (f"：{y['reason']}" if "reason" in y else "")
               for y in totals if y["status"] == "fail"]
        bad += [f"{g['entity']} {g['fiscal_year']} 财年毛利核对失败：{g['reason']}" if "reason" in g
                else f"{g['entity']} {g['fiscal_year']} 财年毛利 ≠ 营收 − 销售成本（差 {g['diff']:,.0f}）"
                for g in gross if g["status"] == "fail"]
        failed += bad
    grade = assess(spec["id"], inputs=[inp], hard_errors=hard, failed_checks=failed)
    attribution, link_ids = _attribution(bundle, entities, spec["activity"])
    rows: list[dict[str, Any]] = []
    if grade.computable and acc is not None:
        rev_tag = next((t for t in tags if t in REVENUE_TAGS), None)
        for e in entities:
            for y in years:
                row = {"entity": e, "fiscal_year": y, **{t: values[(e, t, y)] for t in tags}}
                rev = values.get((e, rev_tag, y)) if rev_tag else None
                if rev and rev > 0:
                    if OPERATING_INCOME in tags:
                        row["operating_margin"] = values[(e, OPERATING_INCOME, y)] / rev
                    if COST_OF_REVENUE in tags:
                        row["gross_margin"] = 1 - values[(e, COST_OF_REVENUE, y)] / rev
                prev = values.get((e, rev_tag, y - 1)) if rev_tag else None
                if rev is not None and prev and prev > 0:
                    row["revenue_growth"] = rev / prev - 1  # 只在同一申报内比较
                rows.append(row)
    filing_recs = [r for r in recs if r["accession"] == acc]
    out = {
        "id": spec["id"], "question": spec["question"], "activity": spec["activity"], "entities": entities,
        "metrics": tags, "fiscal_years": years, "observation": spec.get("observation", ""),
        "grade": grade.grade, "reasons": grade.reasons, "expected": spec.get("expected", ""),
        "attribution_status": attribution, "links": link_ids,
        "filing": acc, "filing_available_at": max((r["available_at"] for r in filing_recs), default=None),
        "filings_skipped": notes, "known_gaps": list(spec.get("known_gaps") or []), "checks": checks,
    }
    if "reviews" in bundle:  # 带技术复核记录的证据包：列出各映射的匹配程度、有效期、复核与结论边界
        links = bundle["links"]
        out["link_review"] = [{"link": lid, "match": links[lid]["match"], "valid_from": links[lid]["valid_from"],
                               "valid_to": links[lid]["valid_to"], "status": links[lid]["status"],
                               "technical_review": links[lid]["technical_review"]} for lid in link_ids]
    return out, rows, grade.to_dict()


@register_branch("chip_operations", result_types=(ResultType.DESCRIPTIVE,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    if study.result_type is not ResultType.DESCRIPTIVE:
        raise ValueError("chip_operations 分支只产出描述统计成果")
    inp = inputs["evidence"]
    recs, bundle = _records(inp)
    defined = bundle.get("units") or {}
    wanted = list(study.method.get("units") or [])
    unknown = [u for u in wanted if u not in defined]
    if not wanted or unknown:
        raise ValueError(f"研究单元未在证据包中定义：{', '.join(unknown) or '（未列出任何单元）'}")
    if (bundle.get("catalog_check") or {}).get("errors"):
        raise ValueError("证据包记录的产业链登记核对有错误，不能用于研究")

    units, tables, feas = [], {}, {}
    unsupported, limitations = [], list(study.limitations)
    validation: dict[str, Any] = {}
    for uid in wanted:
        u, rows, f = _unit(defined[uid], recs, bundle, inp)
        units.append(u)
        feas[uid] = f
        tables[uid] = rows
        if u["grade"] not in ("A", "B"):
            unsupported.append({"item": f"研究单元 {uid}", "reason": f"输入能力为 {u['grade']}：" + "；".join(u["reasons"])})
            continue
        for name, items in u["checks"].items():
            if not items:
                continue
            statuses = {x["status"] for x in items}
            validation[f"{name}:{uid}"] = {
                "status": "fail" if "fail" in statuses else ("pass" if statuses == {"pass"} else "skipped"),
                "checked": sum(x["status"] != "skipped" for x in items), "rows": items,
                **({"reason": items[0]["reason"]} if statuses == {"skipped"} else {})}
        if "link_review" not in u:  # 旧证据包：沿用原限制说明，结果结构与校验值不变
            if u["attribution_status"] != "confirmed":
                why = ("映射与证据尚未人工复核" if u["attribution_status"] == "candidate"
                       else "部分分部没有登记活动映射")
                limitations.append(f"{uid}：分部到活动（{u['activity']}）的归属为 {u['attribution_status']}——{why}；"
                                   "结果按分部口径陈述，不称为该活动的财务")
            continue
        why = {"reviewed": "映射与证据经技术复核（事实核对与语义复核），未经人工签认",
               "candidate": "映射或证据尚未复核", "unmapped": "部分分部没有登记活动映射"}.get(u["attribution_status"])
        if why:
            limitations.append(f"{uid}：分部到活动（{u['activity']}）的归属为 {u['attribution_status']}——{why}")
        partial = [x["link"] for x in u["link_review"] if x["match"] != "exact"]
        if partial or u["attribution_status"] == "unmapped":
            limitations.append(f"{uid}：映射为 partial（{', '.join(partial)}）或不完整，分部还包括该活动以外的业务；"
                               "结果按分部口径陈述，不按活动分摊收入，不称为该活动的财务")
        undated = [x["link"] for x in u["link_review"] if not (x["valid_from"] or x["valid_to"])]
        if undated:
            limitations.append(f"{uid}：映射有效期未登记（{', '.join(undated)}），不据此断言历史时点的归属")
    computed = [u for u in units if u["grade"] in ("A", "B")]
    cutoff = max((u["filing_available_at"] for u in computed if u["filing_available_at"]), default=None)
    return ResearchResult(
        study_id=study.study_id, title=study.title, question=study.question, result_type=study.result_type,
        branch=study.branch, scope=study.scope, data_cutoff=cutoff[:10] if cutoff else None,
        methods={
            "description": "按研究单元从固定证据包中选取最新一份覆盖全部分部、指标与财年的年度申报，同一申报内计算营业利润率、"
                           "毛利率与营收同比；不跨申报拼接，不按收入推算出货量或份额。分部营收合计与合并营收、毛利与营收减销售成本"
                           "分别核对。",
            "benchmark": study.benchmark,
            "parameters": study.method,
            "bundle": {k: bundle.get(k) for k in ("built_at", "catalog_version", "catalog_files",
                                                    "segment_fact_partitions")},
        },
        inputs=[input_record(inp)],
        results={"units": units, "feasibility": feas},
        coverage={"units": len(units), "computed": len(computed),
                  "completeness": "complete" if len(computed) == len(units) else "partial"},
        unsupported=unsupported, limitations=limitations, validation=validation, tables=tables,
    )
