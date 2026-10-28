"""研究分支：美国炼油周度处理量统计与处理能力情景（docs/supply-chain-research-design.md §5）。

统计单元：在研究窗口内逐周核对总投入 G、可运行产能 K 与官方利用率 U 是否齐全、同口径，
按公布精度做区间比较复算 U = 100 × G ÷ K，再给出窗口内的描述统计。

情景单元（simulation）：外生目标处理量增幅 g 下 D = (1 + g) × G，处理上限 Q_cap = kappa × K，
用公共约束引擎计算 Q = min(D, Q_cap) 与缺口 S = max(D − Q_cap, 0)。kappa 是假设参数，
必须在允许假设清单内；基准 G 已超过 Q_cap 的周标为不自洽，不计入缺口。

只回答处理量的机械关系；不含产品收率、进口、库存、物流与价格，不是需求预测、燃料短缺或利润结论。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..analytics.constraints import Capacity, Requirement, max_output
from ..analytics.rounding import compatible, decimals_ok, ratio_interval
from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from .base import ResearchResult, StudyInput, input_record, register_branch
from .feasibility import Assessment, assess, check_assumption

# 模型适用范围：研究定义的 scope 必须与此一致，否则拒绝运行（行业代码或数据形状相似不能决定模型）
MODEL = {
    "model_id": "refining_throughput.v1",
    "activity": "petroleum_refining",
    "market": "US",
    "frequency": "weekly",
    "answers": ["周度总投入、可运行产能与利用率的齐全性、复算与描述统计",
                "给定处理上限假设下，目标处理量提高时的机械性处理缺口"],
    "cannot_answer": ["汽油、馏分油等产品供需或短缺（不含收率、进口、库存与物流）",
                      "价格、裂解价差、炼厂或公司利润", "单个炼厂、地区（PADD）或公司",
                      "需求预测；增幅 g 是外生情景定义"],
}

# 每个角色所需的序列、单位与公布精度（小数位）；与数据不符为硬错误
INPUT_REQUIREMENTS = {
    "inputs": {"series": "WGIRIUS2", "unit": "thousand_barrels_per_day", "decimals": 0,
               "meaning": "总投入 G（Gross Inputs）"},
    "capacity": {"series": "WOCLEUS2", "unit": "thousand_barrels_per_calendar_day", "decimals": 0,
                 "meaning": "可运行产能 K（日历日口径）"},
    "utilization": {"series": "WPULEUS3", "unit": "percent", "decimals": 1,
                    "meaning": "官方利用率 U"},
}
WEEK_END = "FRI"  # EIA 周度观测日期为周结束日

# 日历日产能与日均投入同按每个日历日计；EIA 利用率即二者直接相除。情景中把 K 视为同一时间口径的处理能力
CAPACITY_AS_THROUGHPUT_UNIT = "thousand_barrels_per_day"


_EMPTY = pd.Series(dtype="float64", index=pd.DatetimeIndex([]))


def _series(inp: StudyInput, req: dict[str, Any], errors: list[str]) -> pd.Series:
    """角色对应序列的合格观测（按日期）；单位、序列代码不符时记硬错误并返回空序列。"""
    frame = inp.frame
    units = set(frame["unit"].dropna())
    if units != {req["unit"]}:
        errors.append(f"{inp.role}（{inp.dataset_id}）的单位为 {sorted(units)}，模型要求 {req['unit']}")
        return _EMPTY.copy()
    ids = set(frame["series_id"])
    if ids != {req["series"]}:
        errors.append(f"{inp.role}（{inp.dataset_id}）的序列为 {sorted(ids)}，模型要求 {req['series']}")
        return _EMPTY.copy()
    rows = ok_rows(frame)
    return pd.Series(rows["value"].astype(float).to_numpy(), index=pd.DatetimeIndex(rows["observation_at"]))


def _route(study: StudySpec) -> None:
    wrong = {k: (study.scope.get(k), MODEL[k]) for k in ("activity", "market", "frequency")
             if study.scope.get(k) != MODEL[k]}
    if wrong:
        raise ValueError("研究定义与炼油处理量模型的适用范围不符："
                         + "；".join(f"{k} 为 {a!r}，模型适用于 {b!r}" for k, (a, b) in wrong.items()))
    if study.result_type not in (ResultType.DESCRIPTIVE, ResultType.SIMULATION):
        raise ValueError("refining_throughput 分支只产出描述统计或情景模拟成果")
    if study.result_type is ResultType.DESCRIPTIVE and study.method.get("scenarios"):
        raise ValueError("描述统计研究不能包含情景；情景须单独定义为 simulation 研究")


def _weekly(series: dict[str, pd.Series], start: pd.Timestamp, end: pd.Timestamp,
            errors: list[str]) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """窗口内的预期周结束日，以及每周三个数值（缺失为 NaN，不插值）。"""
    expected = pd.date_range(start, end, freq=f"W-{WEEK_END}")
    for role, s in series.items():
        window = s[(s.index >= start) & (s.index <= end)]
        off = window.index[window.index.day_of_week != 4]
        if len(off):
            errors.append(f"{role} 有 {len(off)} 个观测日期不是周五（如 {off[0].date()}），周度口径可能已变化")
    frame = pd.DataFrame({role: s.reindex(expected) for role, s in series.items()}, index=expected)
    return frame, expected


def _precision(frame: pd.DataFrame, errors: list[str]) -> None:
    for role, req in INPUT_REQUIREMENTS.items():
        values = frame[role].dropna()
        bad = values[[not decimals_ok(v, req["decimals"]) for v in values]]
        if len(bad):
            errors.append(f"{role} 有 {len(bad)} 个值不是 {req['decimals']} 位小数（如 {bad.index[0].date()} 的 "
                          f"{bad.iloc[0]}），与区间复算所用的公布精度不符")


def _ratio_rows(valid: pd.DataFrame) -> list[dict[str, Any]]:
    dg, dk, du = (INPUT_REQUIREMENTS[r]["decimals"] for r in ("inputs", "capacity", "utilization"))
    rows = []
    for day, r in valid.iterrows():
        lo, hi = ratio_interval(r["inputs"], dg, r["capacity"], dk, scale=100.0)
        calc = 100.0 * r["inputs"] / r["capacity"]
        rows.append({"week_ending": day.date().isoformat(), "gross_inputs": r["inputs"],
                     "operable_capacity": r["capacity"], "utilization": r["utilization"],
                     "utilization_calc": calc, "calc_low": lo, "calc_high": hi,
                     "diff_pp": calc - r["utilization"],
                     "compatible": compatible((lo, hi), r["utilization"], du)})
    return rows


def _statistics(valid: pd.DataFrame) -> dict[str, Any]:
    u = valid["utilization"]
    return {
        "weeks": int(len(valid)),
        "mean_gross_inputs": float(valid["inputs"].mean()),
        "mean_operable_capacity": float(valid["capacity"].mean()),
        "mean_utilization": float(u.mean()),
        # 总投入之和 ÷ 产能之和：按周加权的窗口利用率，与周度利用率的简单平均不同
        "aggregate_utilization": float(100.0 * valid["inputs"].sum() / valid["capacity"].sum()),
        "min_utilization": float(u.min()), "min_week": u.idxmin().date().isoformat(),
        "max_utilization": float(u.max()), "max_week": u.idxmax().date().isoformat(),
        "weeks_at_or_above_95": int((u >= 95).sum()),
        "capacity_values": sorted(float(x) for x in valid["capacity"].unique()),
    }


def _reference(series: dict[str, pd.Series], window: list[str]) -> dict[str, Any]:
    """假设参数的经验参照：参照期内官方利用率的分布（不进入计算，只说明允许范围的依据）。"""
    lo, hi = (pd.Timestamp(x) for x in window)
    u = series["utilization"]
    u = u[(u.index >= lo) & (u.index <= hi)]
    if u.empty:
        return {"window": window, "weeks": 0}
    return {"window": window, "weeks": int(len(u)), "max_utilization": float(u.max()),
            "max_week": u.idxmax().date().isoformat(), "p95_utilization": float(u.quantile(0.95)),
            "mean_utilization": float(u.mean())}


def _scenario(sc: dict[str, Any], valid: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    g, kappa = float(sc["g"]), float(sc["kappa"])
    weeks, inconsistent = [], []
    for day, r in valid.iterrows():
        demand = (1 + g) * r["inputs"]
        q_cap = kappa * r["capacity"]
        row = {"scenario": sc["id"], "week_ending": day.date().isoformat(), "gross_inputs": r["inputs"],
               "demand": demand, "q_cap": q_cap}
        if r["inputs"] > q_cap:
            # 基准处理量已超过假设上限：不抬高上限、不截断观测，也不记成历史短缺
            inconsistent.append(row["week_ending"])
            weeks.append({**row, "status": "inconsistent_baseline", "output": None, "shortfall": None})
            continue
        out = max_output("throughput", demand,
                         [Requirement("throughput", "distillation", 1.0, CAPACITY_AS_THROUGHPUT_UNIT)],
                         [Capacity("distillation", q_cap, CAPACITY_AS_THROUGHPUT_UNIT)])
        weeks.append({**row, "status": "ok", "output": out["output"], "shortfall": out["shortfall"]})
    ok = [w for w in weeks if w["status"] == "ok"]
    short = [w for w in ok if w["shortfall"] > 0]
    worst = max(ok, key=lambda w: w["shortfall"]) if ok else None
    summary = {
        "id": sc["id"], "g": g, "kappa": kappa, "label": sc.get("label", ""),
        "weeks": len(weeks), "weeks_evaluated": len(ok), "weeks_inconsistent": len(inconsistent),
        "inconsistent_weeks": inconsistent,
        "weeks_with_shortfall": len(short),
        "mean_demand": sum(w["demand"] for w in ok) / len(ok) if ok else None,
        "mean_output": sum(w["output"] for w in ok) / len(ok) if ok else None,
        "mean_shortfall": sum(w["shortfall"] for w in ok) / len(ok) if ok else None,
        "max_shortfall": worst["shortfall"] if worst else None,
        "max_shortfall_week": worst["week_ending"] if worst else None,
    }
    return summary, weeks


def _baseline_check(valid: pd.DataFrame) -> dict[str, Any]:
    """基准情景（kappa = 1、g = 0）：可处理量应逐周等于实际总投入，缺口为零；基准超过产能的周标为不自洽。"""
    _, weeks = _scenario({"id": "baseline", "g": 0.0, "kappa": 1.0}, valid)
    ok = [w for w in weeks if w["status"] == "ok"]
    bad = [w["week_ending"] for w in ok if w["output"] != w["gross_inputs"] or w["shortfall"] != 0]
    return {"status": "pass" if ok and not bad else "fail", "checked": len(weeks), "matched": len(ok) - len(bad),
            "inconsistent": len(weeks) - len(ok), "failures": bad}


@register_branch("refining_throughput", result_types=(ResultType.DESCRIPTIVE, ResultType.SIMULATION))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    _route(study)
    method = study.method
    start, end = pd.Timestamp(study.scope["start"]), pd.Timestamp(study.scope["end"])
    hard: list[str] = []
    missing_roles = [r for r in INPUT_REQUIREMENTS if r not in inputs]
    if missing_roles:
        raise ValueError(f"研究定义缺少模型所需的输入角色：{', '.join(missing_roles)}")
    series = {role: _series(inputs[role], req, hard) for role, req in INPUT_REQUIREMENTS.items()}
    frame, expected = _weekly(series, start, end, hard)
    _precision(frame, hard)

    data_last = min((s.index.max() for s in series.values() if len(s)), default=None)
    complete = frame.dropna()
    missing_weeks = [d.date().isoformat() for d in frame.index if d not in complete.index]
    not_yet = [w for w in missing_weeks if data_last is None or pd.Timestamp(w) > data_last]
    gaps = [w for w in missing_weeks if w not in not_yet]

    ratio = _ratio_rows(complete) if not hard else []
    failures = [r for r in ratio if not r["compatible"]]
    ratio_check = {
        "status": "pass" if ratio and not failures else ("fail" if failures else "skipped"),
        "checked": len(ratio), "failures": failures,
        "max_abs_diff_pp": max((abs(r["diff_pp"]) for r in ratio), default=None),
        "rule": "按 G、K 整数与 U 一位小数的公布精度传播舍入区间，复算区间与 U ± 0.05 相交即相容；不设经验容差",
    }
    if hard:
        ratio_check["reason"] = "存在硬错误，未复算"

    stats_unit = assess("weekly_statistics", inputs=list(inputs.values()), hard_errors=hard,
                        failed_checks=[f"{len(failures)} 周复算利用率与公布值不相容"] if failures else [])
    units: list[Assessment] = [stats_unit]
    unsupported: list[dict[str, str]] = []
    limitations = list(study.limitations)
    statistics = _statistics(complete) if stats_unit.computable and len(complete) else None
    if not stats_unit.computable:
        unsupported.append({"item": "周度统计", "reason": f"输入能力为 {stats_unit.grade}："
                            + "；".join(stats_unit.reasons)})
    if gaps:
        unsupported.append({"item": "完整期间结论", "reason": f"{len(gaps)} 周缺少至少一个数值（不插值）："
                            + "、".join(gaps[:8]) + ("等" if len(gaps) > 8 else "")})
    if not_yet:
        limitations.append(f"窗口内 {len(not_yet)} 周晚于数据最后观测 {data_last.date() if data_last is not None else '—'}，"
                           "结论只覆盖到该日")
    completeness = "partial" if gaps or not len(complete) else ("complete_to_date" if not_yet else "complete")

    scenarios_out: list[dict[str, Any]] = []
    scenario_weeks: list[dict[str, Any]] = []
    reference = None
    if study.result_type is ResultType.SIMULATION:
        allowed = dict(method.get("allowed_assumptions") or {})
        if method.get("reference_window"):
            reference = _reference(series, [str(x) for x in method["reference_window"]])
        scenarios = list(method.get("scenarios") or [])
        if not scenarios:
            raise ValueError("情景研究没有定义任何情景")
        for sc in scenarios:
            record, err = check_assumption("kappa", sc.get("kappa"), allowed)
            definition = []
            g = sc.get("g")
            if not isinstance(g, (int, float)) or isinstance(g, bool) or g <= -1:
                definition.append(f"情景 {sc.get('id')} 的增幅 g 无效：{g!r}")
            unit = assess(f"scenario:{sc['id']}", inputs=list(inputs.values()), hard_errors=definition,
                          assumptions=[record] if err is None else [], assumption_errors=[err] if err else [],
                          depends_on=[stats_unit])
            units.append(unit)
            if not unit.computable:
                unsupported.append({"item": f"情景 {sc['id']}", "reason": f"输入能力为 {unit.grade}："
                                    + "；".join(unit.reasons)})
                scenarios_out.append({"id": sc["id"], "g": g, "kappa": sc.get("kappa"),
                                      "label": sc.get("label", ""), "grade": unit.grade})
                continue
            summary, weeks = _scenario(sc, complete)
            scenarios_out.append({**summary, "grade": unit.grade})
            scenario_weeks += weeks
            if summary["weeks_inconsistent"]:
                limitations.append(f"情景 {sc['id']}：{summary['weeks_inconsistent']} 周的基准总投入已超过假设上限，"
                                   "标为不自洽，未计入缺口")

    validation: dict[str, Any] = {"ratio_check": ratio_check}
    if study.result_type is ResultType.SIMULATION:
        validation["baseline_check"] = _baseline_check(complete) if stats_unit.computable else \
            {"status": "skipped", "reason": "统计单元不可计算"}

    cutoff = complete.index.max().date().isoformat() if len(complete) else None
    coverage = {
        "first_week": expected[0].date().isoformat() if len(expected) else None,
        "last_week": expected[-1].date().isoformat() if len(expected) else None,
        "expected_weeks": int(len(expected)), "valid_weeks": int(len(complete)),
        "missing_weeks": gaps, "not_yet_available_weeks": not_yet,
        "data_last_observation": data_last.date().isoformat() if data_last is not None else None,
        "completeness": completeness,
    }
    return ResearchResult(
        study_id=study.study_id,
        title=study.title,
        question=study.question,
        result_type=study.result_type,
        branch=study.branch,
        scope=study.scope,
        data_cutoff=cutoff,
        methods={
            "description": "逐周核对 EIA 周度总投入、可运行产能与官方利用率；按公布精度的舍入区间复算利用率；"
                           "缺失周不插值、不混用四周平均。"
                           + ("情景中 D = (1 + g) × G、Q_cap = kappa × K，经固定系数约束引擎计算可处理量与缺口；"
                              "g 为外生情景定义，kappa 为允许假设清单内的参数。"
                              if study.result_type is ResultType.SIMULATION else ""),
            "benchmark": study.benchmark,
            "model": MODEL,
            "input_requirements": INPUT_REQUIREMENTS,
            "parameters": method,
            "availability_rule": inputs["inputs"].version.quality.get("availability_rule"),
        },
        inputs=[input_record(i) for i in inputs.values()],
        results={
            "feasibility": {u.unit: u.to_dict() for u in units},
            "statistics": statistics,
            "scenarios": scenarios_out,
            "assumption_reference": reference,
        },
        coverage=coverage,
        unsupported=unsupported,
        limitations=limitations,
        validation=validation,
        tables={"weekly": ratio, "scenario_weeks": scenario_weeks},
    )
