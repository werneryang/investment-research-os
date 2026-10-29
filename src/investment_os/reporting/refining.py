"""炼油处理量研究的报告段落与图表：输入能力等级、统计、复算核对与情景。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..research.refining import REFERENCE_SCOPE_LABEL

import pandas as pd

GRADE_LABEL = {"A": "A：已核验输入", "B": "B：明示假设的情景", "C": "C：受阻，不生成数值",
               "unassessed": "未评估：不计算"}


def _n(value: Any, digits: int = 0) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _feasibility_table(result: dict[str, Any]) -> tuple[str, list[str], list[list[str]]]:
    rows = [[unit, GRADE_LABEL.get(a["grade"], a["grade"]), "；".join(a["reasons"]) or "—"]
            for unit, a in result["results"]["feasibility"].items()]
    return ("table", ["研究单元", "输入能力", "依据"], rows)


def sections(result: dict[str, Any]) -> tuple[list[Any], str, list[Any]]:
    r, cov = result["results"], result["coverage"]
    model = result["methods"]["model"]
    body: list[Any] = [
        "每个研究单元单独定级：A 表示基准输入在声明范围内核验通过，不等于预测有效；"
        "B 表示使用了允许假设清单内的参数，结果是情景；C 与未评估的单元不生成数值。",
        _feasibility_table(result),
    ]
    s = r.get("statistics")
    if s:
        body += [
            f"{cov['first_week']} 至 {cov['last_week']} 共 {s['weeks']} 周三项数值齐全。"
            f"周均总投入 {_n(s['mean_gross_inputs'])} 千桶/日，周均可运行产能 {_n(s['mean_operable_capacity'])} 千桶/日历日；"
            f"官方周度利用率平均 {_n(s['mean_utilization'], 1)}%，最低 {_n(s['min_utilization'], 1)}%（{s['min_week']}），"
            f"最高 {_n(s['max_utilization'], 1)}%（{s['max_week']}），达到或超过 95% 的有 {s['weeks_at_or_above_95']} 周。"
            f"按总投入之和 ÷ 产能之和计的窗口利用率为 {_n(s['aggregate_utilization'], 2)}%。",
            f"窗口内可运行产能出现 {len(s['capacity_values'])} 个取值（{', '.join(_n(x) for x in s['capacity_values'])}），"
            "与周度利用率以最近报告的月度产能为分母一致。",
        ]
    scen = r.get("scenarios") or []
    if scen:
        body.append("情景：D = (1 + g) × G，Q_cap = kappa × K，Q = min(D, Q_cap)，S = max(D − Q_cap, 0)；单位千桶/日。"
                    "g 是外生情景定义，kappa 是假设参数；缺口不是历史真实短缺，也不是燃料短缺或需求预测。")
        body.append(("table", ["情景", "g", "kappa", "输入能力", "计算周", "不自洽周", "有缺口周",
                               "平均目标处理量", "平均可处理量", "平均缺口", "最大缺口（周）"],
                     [[x["id"], f"{x['g']:.0%}" if isinstance(x.get("g"), (int, float)) else str(x.get("g")),
                       f"{x['kappa']:.2f}" if isinstance(x.get("kappa"), (int, float)) else str(x.get("kappa")),
                       GRADE_LABEL.get(x["grade"], x["grade"]),
                       *([str(x["weeks_evaluated"]), str(x["weeks_inconsistent"]), str(x["weeks_with_shortfall"]),
                          _n(x["mean_demand"]), _n(x["mean_output"]), _n(x["mean_shortfall"], 1),
                          f"{_n(x['max_shortfall'], 1)}（{x['max_shortfall_week']}）" if x["max_shortfall_week"] else "—"]
                         if x["grade"] in ("A", "B") else ["—"] * 7)]
                      for x in scen]))
    ref = r.get("assumption_reference")
    if ref and ref.get("weeks"):
        line = (f"假设参照（不进入计算）：{ref['window'][0]} 至 {ref['window'][1]} 的 {ref['weeks']} 周官方利用率"
                f"平均 {_n(ref['mean_utilization'], 1)}%，95 分位 {_n(ref['p95_utilization'], 1)}%，"
                f"最高 {_n(ref['max_utilization'], 1)}%（{ref['max_week']}）。")
        scope = ref.get("use_scope")
        if scope is not None:
            gaps = "、".join(f"{a}—{b}" for a, b in scope["uncovered"])
            line += (f"用途核验：{REFERENCE_SCOPE_LABEL.get(scope['status'], scope['status'])}（{scope['status']}）"
                     + (f"，未覆盖 {gaps}" if gaps else "") + "。")
        body.append(line)
    detail: list[Any] = [
        f"预期周 {cov['expected_weeks']}，三项齐全 {cov['valid_weeks']}；缺失周 {len(cov['missing_weeks'])}"
        + (f"（{'、'.join(cov['missing_weeks'][:8])}）" if cov["missing_weeks"] else "")
        + f"；数据最后观测 {cov['data_last_observation'] or '—'}。缺失周不插值。",
        "模型能回答：" + "；".join(model["answers"]) + "。",
        "模型不能回答：" + "；".join(model["cannot_answer"]) + "。",
    ]
    used: dict[str, dict[str, Any]] = {}
    for unit, a in r["feasibility"].items():
        for item in a["assumptions"]:
            entry = used.setdefault(item["name"], {**item, "uses": []})
            entry["uses"].append(f"{unit.removeprefix('scenario:')} = {item['value']}")
    for name, item in used.items():
        detail.append(f"假设 {name}（{item.get('unit', '')}，允许范围 {item.get('allowed_range')}；"
                      f"{'、'.join(item['uses'])}）：{item.get('rationale', '')}")
    return body, "口径、假设与覆盖", detail


def baseline_line(v: dict[str, Any]) -> str:
    return (f"；kappa = 1、g = 0 时 {v['checked']} 周中可处理量等于实际总投入的 {v['matched']} 周，"
            f"基准已超过可运行产能的 {v['inconsistent']} 周标为不自洽")


def ratio_line(v: dict[str, Any]) -> str:
    if v.get("checked"):
        return (f"；{v['checked']} 周复算，不相容 {len(v['failures'])} 周，复算与公布值最大差 "
                f"{_n(v['max_abs_diff_pp'], 3)} 个百分点（{v['rule']}）")
    return f"；{v.get('reason', '未复算')}"


def figures(result: dict[str, Any], out_dir: Path) -> list[tuple[str, Path]]:
    import matplotlib.pyplot as plt

    from .report import _save, _style

    weekly = result["tables"].get("weekly") or []
    if not weekly:
        return []
    _style()
    out_dir.mkdir(parents=True, exist_ok=True)
    figs: list[tuple[str, Path]] = []
    w = pd.DataFrame(weekly)
    w["week_ending"] = pd.to_datetime(w["week_ending"])
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(w["week_ending"], w["gross_inputs"], label="Gross inputs (kb/d)")
    ax.plot(w["week_ending"], w["operable_capacity"], ls="--", label="Operable capacity (kb/cd)")
    ax.set_title("U.S. refinery gross inputs and operable capacity, weekly")
    ax.legend(frameon=False)
    figs.append(("周度总投入与可运行产能", _save(fig, out_dir / "refining_inputs_capacity.png")))

    # 复算值减公布值：竖线为 G、K 舍入带来的复算区间，虚线为公布值自身的舍入范围 ±0.05；二者相交即相容
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.vlines(w["week_ending"], w["calc_low"] - w["utilization"], w["calc_high"] - w["utilization"], lw=2,
              alpha=0.5, label="Recomputed interval − published (pp)")
    ax.plot(w["week_ending"], w["diff_pp"], "o", ms=2.5, label="Recomputed − published (pp)")
    for y in (-0.05, 0.05):
        ax.axhline(y, color="black", lw=0.8, ls="--")
    ax.set_title("Utilization recomputation vs published rounding range (±0.05 pp)")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    figs.append(("复算利用率与公布值之差及舍入区间", _save(fig, out_dir / "refining_utilization_check.png")))

    sw = pd.DataFrame(result["tables"].get("scenario_weeks") or [])
    if not sw.empty:
        sw["week_ending"] = pd.to_datetime(sw["week_ending"])
        fig, ax = plt.subplots(figsize=(8, 3.6))
        for sid, g in sw.groupby("scenario", sort=False):
            # 不自洽周没有缺口数值，断开折线而不是跨过去连接
            ax.plot(g["week_ending"], pd.to_numeric(g["shortfall"]).where(g["status"] == "ok").astype(float),
                    marker="o", ms=2, label=sid)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title("Scenario throughput shortfall S = max(D − Q_cap, 0), kb/d (assumptions, not forecasts)")
        ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4)
        figs.append(("各情景的周度处理缺口（假设情景）", _save(fig, out_dir / "refining_scenario_shortfall.png")))
    return figs
