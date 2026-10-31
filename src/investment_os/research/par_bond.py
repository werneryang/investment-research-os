"""研究分支：假设平价债券的利率敏感性情景（情景与策略模拟类成果）。

在研究窗口内最后一个有效曲线日，按各期限的票面收益率构造「票息 = 收益率」的假设平价债券，
计算修正久期、凸性与 DV01，并对债券自身收益率施加平移冲击，比较完整重新定价与久期 / 久期 + 凸性近似。

这是对假设现金流的数学情景，不是任何真实国债、债券基金（如 TLT）的风险，也不是预测；
冲击幅度是假设，不代表概率。票面收益率曲线不等于零息曲线，本分支不做曲线换算。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..analytics import bonds
from ..analytics.rates import curve_frame
from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from ..tenor import parse_tenor
from .base import ResearchResult, StudyInput, input_record, register_branch

# 封闭解核对的容差
TOL_PRICE = 1e-8  # 平价债券价格应为面值
TOL_DURATION_REL = 1e-9  # 解析修正久期与封闭解
TOL_EFFECTIVE_REL = 1e-4  # 解析值与有效久期 / 凸性（有限差分）


def _tenor_map(inp: StudyInput) -> dict[str, str]:
    return {sid: parse_tenor(meta["tenor"]).code for sid, meta in inp.version.series.items() if "tenor" in meta}


def _checks(bonds_out: dict[str, dict[str, Any]], freq: int, h: float) -> dict[str, Any]:
    """独立核对：平价价格 = 面值；解析修正久期 = 封闭解；解析久期、凸性 ≈ 有限差分重定价。"""
    rows, failures = [], []
    for tenor, b in bonds_out.items():
        y, years = b["yield"], b["years"]
        checks = {
            "par_price": (b["price"], 100.0, abs(b["price"] - 100.0) <= TOL_PRICE),
            "duration_closed_form": (b["modified_duration"], bonds.par_modified_duration_closed_form(y, years, freq),
                                     None),
            "effective_duration": (b["modified_duration"], bonds.effective_duration(y, y, years, freq, h), None),
            "effective_convexity": (b["convexity"], bonds.effective_convexity(y, y, years, freq, h), None),
        }
        for name, (value, reference, ok) in checks.items():
            if ok is None:
                rel = TOL_DURATION_REL if name == "duration_closed_form" else TOL_EFFECTIVE_REL
                ok = abs(value - reference) <= rel * abs(reference)
            row = {"tenor": tenor, "check": name, "value": value, "reference": reference, "pass": bool(ok)}
            rows.append(row)
            if not ok:
                failures.append(row)
    return {"status": "pass" if not failures else "fail", "checked": len(rows), "failures": failures,
            "rows": rows, "tolerances": {"par_price_abs": TOL_PRICE, "duration_closed_form_rel": TOL_DURATION_REL,
                                         "effective_rel": TOL_EFFECTIVE_REL, "finite_difference_step": h}}


@register_branch("par_bond_scenarios", result_types=(ResultType.SIMULATION,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    if study.result_type is not ResultType.SIMULATION:
        raise ValueError("par_bond_scenarios 分支只产出情景模拟成果")
    curve_in = inputs["curve"]
    method = study.method
    freq = int(method.get("coupon_frequency", 2))
    shocks = [float(x) for x in method["shocks_bp"]]
    h = float(method.get("finite_difference_bp", 1)) / 1e4
    start, end = pd.Timestamp(study.scope["start"]), pd.Timestamp(study.scope["end"])

    frame = curve_in.frame
    usable = ok_rows(frame[(frame["observation_at"] >= start) & (frame["observation_at"] <= end)])
    curve = curve_frame(usable, _tenor_map(curve_in))
    wanted = [parse_tenor(t).code for t in method["tenors"]]
    unsupported: list[dict[str, str]] = []
    limitations = list(study.limitations)

    # 基准日：窗口内所有所需期限都有值的最后一天；没有则逐个期限取各自最后有值的一天会混用日期，不允许
    complete_days = curve[[t for t in wanted if t in curve]].dropna() if len(curve) else curve
    if not len(complete_days) or any(t not in curve for t in wanted):
        missing = [t for t in wanted if t not in curve]
        raise ValueError(f"研究窗口 {start.date()} 至 {end.date()} 内没有所有期限同时有值的曲线日"
                         + (f"（缺少期限 {', '.join(missing)}）" if missing else ""))
    base_date = complete_days.index.max()
    base = complete_days.loc[base_date]
    staleness = int((end - base_date).days)

    bonds_out: dict[str, dict[str, Any]] = {}
    scenarios: dict[str, list[dict[str, float]]] = {}
    for tenor in wanted:
        years = parse_tenor(tenor).months / 12
        y = float(base[tenor]) / 100
        try:
            bonds._periods(years, freq)
        except ValueError as exc:
            unsupported.append({"item": f"期限 {tenor}", "kind": "scope", "reason": str(exc)})
            continue
        bonds_out[tenor] = {
            "years": years, "yield": y, "yield_pct": y * 100, "coupon_pct": y * 100,
            "price": bonds.price(y, y, years, freq),
            "macaulay_duration": bonds.macaulay_duration(y, y, years, freq),
            "modified_duration": bonds.modified_duration(y, y, years, freq),
            "convexity": bonds.convexity(y, y, years, freq),
            "dv01": bonds.dv01(y, y, years, freq),
        }
        rows = []
        for s in shocks:
            try:
                rows.append(bonds.scenario(y, y, years, s, freq))
            except ValueError as exc:
                unsupported.append({"item": f"期限 {tenor} 冲击 {s:+.0f} bp", "kind": "scope", "reason": str(exc)})
        scenarios[tenor] = rows

    worst = {t: max(rows, key=lambda r: abs(r["duration_convexity_error_pp"])) for t, rows in scenarios.items() if rows}
    coverage = {
        "base_date": base_date.date().isoformat(),
        "window_end": end.date().isoformat(),
        "days_before_window_end": staleness,
        "tenors_requested": wanted,
        "tenors_used": list(bonds_out),
        "curve_days_in_window": int(len(curve)),
    }
    if staleness > 7:
        limitations.append(f"基准日 {coverage['base_date']} 距研究窗口终点 {staleness} 天；结果对应该日的收益率")

    return ResearchResult(
        study_id=study.study_id,
        title=study.title,
        question=study.question,
        result_type=study.result_type,
        branch=study.branch,
        scope=study.scope,
        data_cutoff=coverage["base_date"],
        methods={
            "description": "以基准日各期限票面收益率为票息与到期收益率构造假设平价债券（每年 "
                           f"{freq} 次付息、估值日为付息日、无应计利息）；对债券自身收益率施加平移冲击，"
                           "比较完整重新定价与修正久期、久期 + 凸性近似。",
            "benchmark": "完整重新定价（按冲击后收益率贴现全部现金流）",
            "parameters": method,
            "availability_rule": curve_in.version.quality.get("availability_rule"),
        },
        inputs=[input_record(i) for i in inputs.values()],
        results={"base_date": coverage["base_date"], "bonds": bonds_out, "scenarios": scenarios,
                 "worst_duration_convexity_error": worst},
        coverage=coverage,
        unsupported=unsupported,
        limitations=limitations,
        validation={"closed_form_checks": _checks(bonds_out, freq, h)},
        tables={
            "bonds": [{"tenor": t, **b} for t, b in bonds_out.items()],
            "scenarios": [{"tenor": t, **r} for t, rows in scenarios.items() for r in rows],
        },
    )
