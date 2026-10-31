"""炼油研究的展示组件：周度处理量统计与情景（refining_throughput）、投资对照（refining_investment）。"""

from __future__ import annotations

from typing import Any

from .common import CHECK_LABEL, USE_LABEL, chip, e, num, stat
from .i18n import L, te

GRADE = {"A": ("A：已核验输入", "A: verified inputs"), "B": ("B：明示假设的情景", "B: scenario with stated assumptions"),
         "C": ("C：受阻，不生成数值", "C: blocked, no values"), "unassessed": ("未评估：不计算", "Unassessed: not computed")}


def _stats(items: list[str]) -> str:
    return f'<div class="stats">{"".join(items)}</div>'


def _table(head: list[str], rows: list[list[str]]) -> str:
    return ('<div class="scroll"><table class="compact"><thead><tr>' + "".join(f"<th>{h}</th>" for h in head)
            + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
            + "</tbody></table></div>")


def _pct(v: Any, digits: int = 1, signed: bool = False) -> str:
    return "—" if v is None else f"{num(v * 100, digits, signed)}%"


def _feasibility(result: dict[str, Any]) -> str:
    rows = [[f"<code>{e(unit)}</code>", e(L(*GRADE.get(a["grade"], (a["grade"], a["grade"])))),
             te(L("；", "; ").join(a["reasons"]) or "—")]
            for unit, a in result["results"]["feasibility"].items()]
    return ("<p class='small'>" + L("每个研究单元单独定级：A 表示输入在声明范围内核验通过，不等于预测有效；C 与未评估的单元不生成数值。",
                                    "Each research unit is graded separately: A means inputs verified within the declared "
                                    "scope, not that a forecast is valid; C and unassessed units produce no values.")
            + "</p>" + _table([L("研究单元", "Unit"), L("输入能力", "Input capability"), L("依据", "Basis")], rows))


def _check(v: dict[str, Any] | None, text: str) -> str:
    return f"{chip(v['status'], CHECK_LABEL.get(v['status'], ''))} {text}" if v else "—"


def _model_items(result: dict[str, Any]) -> list[str]:
    m = result["methods"]
    model = m["model"]
    return [f"<li>{te(m['description'])}</li>",
            f"<li>{L('模型能回答：', 'The model answers: ')}{L('；', '; ').join(te(x) for x in model['answers'])}</li>",
            f"<li>{L('模型不能回答：', 'The model cannot answer: ')}{L('；', '; ').join(te(x) for x in model['cannot_answer'])}</li>",
            f"<li>{L('比较基准：', 'Benchmark: ')}{te(m.get('benchmark') or '—')}{L('；版本策略：', '; version policy: ')}"
            f"{e(USE_LABEL['scenario' if result.get('result_type') == 'simulation' else 'descriptive'])}{L('。', '.')}</li>"]


# ---- 周度处理量统计与情景 --------------------------------------------------------

def _throughput_stats(result: dict[str, Any]) -> str:
    s, cov = result["results"].get("statistics"), result["coverage"]
    items = [stat(L("齐全周", "Complete weeks"), f"{cov['valid_weeks']} / {cov['expected_weeks']}",
                  L(f"缺失 {len(cov['missing_weeks'])} 周，不插值", f"{len(cov['missing_weeks'])} missing, not interpolated"))]
    if s:
        items += [stat(L("平均利用率", "Mean utilization"), f"{num(s['mean_utilization'], 1)}%",
                       L(f"总投入之和 ÷ 产能之和 {num(s['aggregate_utilization'], 2)}%",
                         f"sum of inputs ÷ sum of capacity {num(s['aggregate_utilization'], 2)}%")),
                  stat(L("利用率区间", "Utilization range"), f"{num(s['min_utilization'], 1)}% – {num(s['max_utilization'], 1)}%",
                       L(f"≥ 95% 的有 {s['weeks_at_or_above_95']} 周", f"{s['weeks_at_or_above_95']} weeks at or above 95%"))]
    scen = result["results"].get("scenarios") or []
    if scen:
        grades = [x["grade"] for x in scen]
        items.append(stat(L("情景", "Scenarios"), str(len(scen)),
                          L(f"B {grades.count('B')} 个，C {grades.count('C')} 个（不生成数值）",
                            f"B: {grades.count('B')}, C: {grades.count('C')} (no values)")))
    return _stats(items)


def _throughput_detail(result: dict[str, Any]) -> str:
    out = _feasibility(result)
    scen = result["results"].get("scenarios") or []
    if scen:
        rows = [[e(x["id"]), e(f"{x['g']:.0%}" if isinstance(x.get("g"), (int, float)) else str(x.get("g"))),
                 e(f"{x['kappa']:.2f}" if isinstance(x.get("kappa"), (int, float)) else str(x.get("kappa"))),
                 e(L(*GRADE.get(x["grade"], (x["grade"], x["grade"])))),
                 *([str(x["weeks_evaluated"]), str(x["weeks_with_shortfall"]), num(x["mean_shortfall"], 1),
                    num(x["max_shortfall"], 1)] if x["grade"] in ("A", "B") else ["—"] * 4)] for x in scen]
        out += ("<p class='small'>" + L("情景：D = (1 + g) × G，Q_cap = kappa × K，缺口 S = max(D − Q_cap, 0)，千桶/日；"
                                        "g 是外生情景定义，kappa 是允许假设，缺口不是历史短缺或预测。",
                                        "Scenarios: D = (1 + g) × G, Q_cap = kappa × K, shortfall S = max(D − Q_cap, 0), "
                                        "thousand barrels per day; g is an exogenous scenario, kappa an allowed assumption; "
                                        "shortfalls are neither historical shortages nor forecasts.") + "</p>"
                + _table([L("情景", "Scenario"), "g", "kappa", L("输入能力", "Capability"), L("计算周", "Weeks"),
                          L("有缺口周", "Weeks short"), L("平均缺口", "Mean shortfall"), L("最大缺口", "Max shortfall")], rows))
    return out


def _throughput_evidence(result: dict[str, Any]) -> list[tuple[str, str]]:
    v, cov = result["validation"], result["coverage"]
    rc = v.get("ratio_check")
    rows = [(L("周度覆盖", "Weekly coverage"),
             e(L(f"预期 {cov['expected_weeks']} 周，三项齐全 {cov['valid_weeks']} 周；数据最后观测 {cov.get('data_last_observation') or '—'}",
                 f"{cov['expected_weeks']} expected weeks, {cov['valid_weeks']} with all three values; last observation "
                 f"{cov.get('data_last_observation') or '—'}"))),
            (L("利用率区间复算", "Utilization recomputation"),
             _check(rc, L(f"{rc['checked']} 周复算，不相容 {len(rc['failures'])} 周，最大差 {num(rc['max_abs_diff_pp'], 3)} 个百分点"
                          "（按公布精度传播舍入区间，不设经验容差）",
                          f"{rc['checked']} weeks recomputed, {len(rc['failures'])} incompatible, max difference "
                          f"{num(rc['max_abs_diff_pp'], 3)} pp (rounding intervals at published precision, no empirical "
                          "tolerance)") if rc and rc.get("checked") else e(L("未复算", "not recomputed"))))]
    bc = v.get("baseline_check")
    if bc and bc.get("checked"):
        rows.append((L("基准情景核对", "Baseline scenario check"),
                     _check(bc, L(f"kappa = 1、g = 0 时 {bc['checked']} 周中可处理量等于实际总投入 {bc['matched']} 周",
                                  f"with kappa = 1 and g = 0, output equals actual gross inputs in {bc['matched']} of "
                                  f"{bc['checked']} weeks"))))
    return rows


def _throughput_summary(result: dict[str, Any]) -> list[str]:
    cov, rc = result["coverage"], result["validation"].get("ratio_check") or {}
    out = [L(f"{cov['valid_weeks']}/{cov['expected_weeks']} 周齐全", f"{cov['valid_weeks']}/{cov['expected_weeks']} complete weeks")]
    if rc.get("checked"):
        out.append(L(f"复算 {rc['checked']} 周，不相容 {len(rc['failures'])} 周",
                     f"{rc['checked']} weeks recomputed, {len(rc['failures'])} incompatible"))
    return out


# ---- 投资对照 -------------------------------------------------------------------

def _investment_stats(result: dict[str, Any]) -> str:
    r = result["results"]
    c, rel = r.get("crack_spread"), r.get("utilization_crack")
    items = []
    if c:
        items.append(stat(L("3-2-1 裂解价差均值", "Mean 3-2-1 crack spread"), f"${num(c['mean'], 2)}",
                          L(f"美元/桶，{c['weeks']} 周；最高 {num(c['max'], 2)}（{c['max_week']}）",
                            f"USD per barrel, {c['weeks']} weeks; high {num(c['max'], 2)} ({c['max_week']})")))
    if rel and rel.get("pearson") is not None:
        items.append(stat(L("利用率与价差相关", "Utilization–crack correlation"), num(rel["pearson"], 2, True),
                          L(f"周度水平，Spearman {num(rel['spearman'], 2, True)}", f"weekly levels, Spearman {num(rel['spearman'], 2, True)}")))
    for t in (r.get("tsr") or {}).values():
        items.append(stat(L(f"{t['name']} 累计总收益", f"{t['name']} cumulative TSR"), _pct(t["cumulative"]["company"], 0),
                          L(f"{t['years']} 年；标普 500 {_pct(t['cumulative']['sp500'], 0)}；{t['years_beating_sp500']} 年跑赢",
                            f"{t['years']} years; S&P 500 {_pct(t['cumulative']['sp500'], 0)}; beat it in {t['years_beating_sp500']} years")))
    return _stats(items)


def _investment_detail(result: dict[str, Any]) -> str:
    r = result["results"]
    out = _feasibility(result)
    years = [b for b in r.get("by_year") or [] if b.get("complete")]
    if years:
        out += _table([L("年份", "Year"), L("平均利用率", "Mean utilization"), L("平均价差（美元/桶）", "Mean crack ($/bbl)"),
                       L("价差变化", "Crack change"), L("年内相关（Pearson）", "Within-year correlation (Pearson)")],
                      [[str(b["year"]), f"{num(b['mean_utilization'], 1)}%", num(b["mean_crack"], 2),
                        num(b.get("crack_change"), 2, True), num(b.get("corr_pearson"), 2, True)] for b in years])
    annual = result["tables"].get("annual_tsr") or []
    tsr = r.get("tsr") or {}
    if annual and tsr:
        ids = list(tsr)
        rows = []
        for y in sorted({a["year"] for a in annual}):
            row = [str(y)]
            for cid in ids:
                a = next((x for x in annual if x["company"] == cid and x["year"] == y), None)
                row += [_pct(a["tsr"]) if a else "—", _pct(a["excess"], 1, True) if a else "—"]
            sp = next((x["sp500"] for x in annual if x["year"] == y), None)
            rows.append(row + [_pct(sp)])
        head = [L("年份", "Year")]
        for cid in ids:
            head += [e(tsr[cid]["name"]), L(f"{tsr[cid]['name']} 超额", f"{tsr[cid]['name']} excess")]
        out += ("<p class='small'>" + L("日历年股东总收益（含股息再投资，来自公司 10-K 业绩图）；超额收益 = 公司 − 标普 500。",
                                        "Calendar-year total shareholder return (dividends reinvested, from the companies' "
                                        "10-K performance graphs); excess = company − S&P 500.") + "</p>"
                + _table(head + [L("标普 500", "S&P 500")], rows))
    comp = r.get("comparison") or {}
    if comp:
        out += ("<p class='small'>" + L("年度超额收益与价差、利用率的 Spearman 相关（排序关系；样本只有十年左右，不检验显著性）：",
                                        "Spearman correlation of annual excess return with the crack spread and "
                                        "utilization (rank relation; about ten years, no significance test):") + "</p>"
                + _table([L("公司", "Company"), L("与年均价差", "vs mean crack"), L("与价差变化", "vs crack change"),
                          L("与年均利用率", "vs mean utilization")],
                         [[e(x["name"]), *(f"{num(x[k]['spearman'], 2, True)} ({x[k]['n']})" for k in
                                           ("excess_vs_mean_crack", "excess_vs_crack_change", "excess_vs_mean_utilization"))]
                          for x in comp.values()]))
    return out


def _investment_evidence(result: dict[str, Any]) -> list[tuple[str, str]]:
    v, cov = result["validation"], result["coverage"]
    rows = [(L("周度覆盖", "Weekly coverage"),
             e(L(f"预期 {cov['expected_weeks']} 周，利用率与三个价格齐全 {cov['valid_weeks']} 周；缺失周不插值",
                 f"{cov['expected_weeks']} expected weeks, {cov['valid_weeks']} with utilization and all three prices; "
                 "missing weeks are not interpolated")))]
    for name, x in v.items():
        if name.startswith("overlap_check:") and x.get("checked"):
            rows.append((L(f"重叠申报收益核对（{name.split(':', 1)[1]}）", f"Overlapping-filing check ({name.split(':', 1)[1]})"),
                         _check(x, L(f"{len(x.get('filings', []))} 份申报，{x['checked']} 个重叠年份收益，不一致 {len(x['failures'])} 个（两位小数舍入区间）",
                                     f"{len(x.get('filings', []))} filings, {x['checked']} overlapping annual returns, "
                                     f"{len(x['failures'])} inconsistent (two-decimal rounding intervals)"))))
    sp = v.get("sp500_cross_issuer")
    if sp and sp.get("checked"):
        rows.append((L("标普 500 跨公司核对", "S&P 500 cross-issuer check"),
                     _check(sp, L(f"{'、'.join(sp['companies'])} 的申报之间 {sp['checked']} 个年度收益，不一致 {len(sp['failures'])} 个",
                                  f"{sp['checked']} annual returns between {', '.join(sp['companies'])} filings, "
                                  f"{len(sp['failures'])} inconsistent"))))
    return rows


def _investment_summary(result: dict[str, Any]) -> list[str]:
    v = result["validation"]
    checks = [x for k, x in v.items() if k.startswith("overlap_check:") or k == "sp500_cross_issuer"]
    ok = sum(x["status"] == "pass" for x in checks)
    return [L(f"{result['coverage']['valid_weeks']} 周齐全", f"{result['coverage']['valid_weeks']} complete weeks"),
            L(f"总收益核对 {ok}/{len(checks)} 通过", f"total-return checks {ok}/{len(checks)} passed")]


def _throughput_home(result: dict[str, Any]) -> str | None:
    s, cov = result["results"].get("statistics"), result["coverage"]
    if not s:
        return None
    return L(f"平均利用率 {num(s['mean_utilization'], 1)}%（周度区间 {num(s['min_utilization'], 1)}%–{num(s['max_utilization'], 1)}%，"
             f"≥ 95% 的有 {s['weeks_at_or_above_95']} 周）；三项齐全 {cov['valid_weeks']}/{cov['expected_weeks']} 周",
             f"mean utilization {num(s['mean_utilization'], 1)}% (weekly range {num(s['min_utilization'], 1)}%–"
             f"{num(s['max_utilization'], 1)}%, {s['weeks_at_or_above_95']} weeks at or above 95%); "
             f"{cov['valid_weeks']}/{cov['expected_weeks']} complete weeks")


def _investment_home(result: dict[str, Any]) -> str | None:
    r = result["results"]
    c, rel = r.get("crack_spread"), r.get("utilization_crack")
    if not c:
        return None
    out = L(f"3-2-1 裂解价差均值 {num(c['mean'], 2)} 美元/桶（{c['weeks']} 周，最高 {num(c['max'], 2)}，{c['max_week']}）",
            f"mean 3-2-1 crack spread USD {num(c['mean'], 2)} per barrel ({c['weeks']} weeks, high {num(c['max'], 2)} "
            f"in {c['max_week']})")
    if rel and rel.get("pearson") is not None:
        out += L(f"；周度利用率与价差相关 {num(rel['pearson'], 2, True)}",
                 f"; weekly utilization–crack correlation {num(rel['pearson'], 2, True)}")
    return out


def make_renderers(Renderer: Any) -> dict[str, Any]:
    throughput = Renderer(
        key_stats=_throughput_stats,
        method_items=lambda r: _model_items(r)[:3] + [
            L("<li>复算：按总投入、产能整数与利用率一位小数的公布精度传播舍入区间，与公布值的舍入区间相交即相容。</li>",
              "<li>Recomputation: rounding intervals at the published precision (integer inputs and capacity, one-decimal "
              "utilization); compatible when they intersect the published value's rounding interval.</li>")],
        coverage_title_t=("输入能力与情景", "Input capability and scenarios"),
        coverage_section=_throughput_detail,
        evidence_rows=_throughput_evidence,
        evidence_summary=_throughput_summary,
        history_columns_t=((("齐全周", "Complete weeks"), lambda r: str(r["coverage"].get("valid_weeks", "—"))),
                           (("平均利用率", "Mean utilization"),
                            lambda r: num((r["results"].get("statistics") or {}).get("mean_utilization"), 1))),
        chart_data=lambda r: None,
        figures_t=(("refining_inputs_capacity.png", ("周度总投入与可运行产能", "Weekly gross inputs and operable capacity")),
                   ("refining_utilization_check.png", ("复算利用率与公布值之差及舍入区间",
                                                       "Recomputed minus published utilization, with rounding intervals")),
                   ("refining_scenario_shortfall.png", ("各情景的周度处理缺口（假设情景）",
                                                        "Weekly throughput shortfall by scenario (assumptions)"))),
        use_note_t=("历史描述与假设情景，不是需求、产量或燃料短缺预测",
                    "Historical description and hypothetical scenarios; not a demand, output or fuel-shortage forecast"),
        state_description_t=("输入能力等级与复算是否相容", "input-capability grades and whether recomputation is compatible"),
        home_summary=_throughput_home,
    )
    investment = Renderer(
        key_stats=_investment_stats,
        method_items=_model_items,
        coverage_title_t=("年度对照与输入能力", "Annual comparison and input capability"),
        coverage_section=_investment_detail,
        evidence_rows=_investment_evidence,
        evidence_summary=_investment_summary,
        history_columns_t=((("平均价差", "Mean crack"), lambda r: num((r["results"].get("crack_spread") or {}).get("mean"), 2)),
                           (("周度相关", "Weekly correlation"),
                            lambda r: num((r["results"].get("utilization_crack") or {}).get("pearson"), 2, True))),
        chart_data=lambda r: None,
        figures_t=(("refining_crack_utilization.png", ("周度裂解价差与利用率", "Weekly crack spread and utilization")),
                   ("refining_excess_vs_crack.png", ("年度超额收益与年均价差", "Annual excess return vs mean crack spread"))),
        use_note_t=("历史描述，不是因果解释、交易信号或收益预测",
                    "Historical description; not a causal explanation, trading signal or return forecast"),
        state_description_t=("输入能力等级与总收益核对是否通过", "input-capability grades and whether total-return checks pass"),
        home_summary=_investment_home,
    )
    return {"refining_throughput": throughput, "refining_investment": investment}
