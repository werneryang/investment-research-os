"""研究分支的展示组件。

研究页与首页只负责共同结构（章节、导航、证据面板的共同行、历史与复现）；每个研究分支在这里提供
自己的指标卡片、方法说明、覆盖或假设、证据行、历史列、交互图表数据与静态图。没有注册展示组件的分支
使用 UNSUPPORTED：明确显示「暂无展示组件」，不套用其他分支的说明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..analytics.rates import curvature_label, spread_label
from ..research.findings import COVERAGE_LABEL, FLAT_BP, completeness, coverage_summary
from ..tenor import is_tenor, parse_tenor
from .common import CHECK_LABEL, USE_LABEL, chip, e, num, stat
from .coverage import coverage_strip

Html = str


@dataclass(frozen=True)
class Renderer:
    key_stats: Callable[[dict[str, Any]], Html]
    method_items: Callable[[dict[str, Any]], list[Html]]
    coverage_title: str
    coverage_section: Callable[[dict[str, Any]], Html]
    evidence_rows: Callable[[dict[str, Any]], list[tuple[str, Html]]]
    evidence_summary: Callable[[dict[str, Any]], list[str]]
    history_columns: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...]
    chart_data: Callable[[dict[str, Any]], dict[str, Any] | None]
    figures: tuple[tuple[str, str], ...]
    home_figures: tuple[tuple[str, str], ...]
    use_note: str
    state_description: str
    rule_params_label: Callable[[dict[str, Any]], str] = field(default=lambda p: "")
    supported: bool = True


def use_key(result: dict[str, Any]) -> str:
    if result.get("result_type") == "simulation":
        return "scenario"
    return "point_in_time" if result.get("scope", {}).get("vintage_policy") == "as_of" else "descriptive"


def _stats(items: list[Html]) -> Html:
    return f'<div class="stats">{"".join(items)}</div>'


# ---- 收益率曲线描述 ---------------------------------------------------------

def _curve_stats(result: dict[str, Any]) -> Html:
    res, cov = result["results"], result["coverage"]
    stats = []
    ten = res.get("levels", {}).get("10Y")
    if ten and ten.get("observations"):
        stats.append(stat("10 年期收益率", f"{num(ten['start'])}% → {num(ten['end'])}%",
                          f"{num(ten['change_bp'], 0, True)} bp"))
    for key, sp in res.get("spreads", {}).items():
        if sp.get("observations"):
            inv = sp.get("inversion")
            if not inv:
                note = "期间统计不输出"
            elif sp.get("sample") == "observed":
                note = f"已观测 {inv['observations']} 天中倒挂 {inv['inverted_days']} 天"
            else:
                note = f"倒挂 {inv['inverted_days']} 天"
            stats.append(stat(f"{spread_label(key)} 利差", f"{num(sp['start'], 0)} → {num(sp['end'], 0)} bp", note))
    if cov.get("expected_days"):
        due = cov.get("due_days", cov["expected_days"])
        note = COVERAGE_LABEL[completeness(cov)]
        if cov.get("pending_days"):
            note += f"；另 {cov['pending_days']} 天尚未发布"
        stats.append(stat("日期覆盖", f"{due - cov.get('missing_days', 0)} / {due} 天", note))
    return _stats(stats)


def _curve_method(result: dict[str, Any]) -> list[Html]:
    m = result["methods"]
    params = m.get("parameters", {})
    spreads = "、".join(spread_label(f"{a}-{b}") for a, b in params.get("spreads", []))
    curv = params.get("curvature")
    return [
        f"<li>{e(m['description'])}</li>",
        f"<li>关键期限：{e('、'.join(params.get('key_tenors', [])))}；利差（长端 − 短端）：{e(spreads or '无')}"
        + (f"；曲率：{e(curvature_label('/'.join(curv)))}" if curv else "") + "。</li>",
        f"<li>比较基准：{e(m.get('benchmark') or '—')}。</li>",
        f"<li>覆盖要求：关键期限有效观测占应已发布观测日的比例不低于 {params.get('min_coverage', 0):.0%}，"
        "不足时依赖它的结论不输出。达到要求不等于期间完整：期间完整另需所有预期日期都有数据、且日期在日历核验范围内；"
        "有缺口的指标，期间统计只描述已观测日期。尚未到发布时间的日期单独列出，不计入覆盖。</li>",
        "<li>倒挂定义为利差严格小于 0；恰为 0 的日期单独计数，不计入倒挂。</li>",
        f"<li>时间规则：{e(m.get('availability_rule') or '—')}；版本策略：{e(USE_LABEL[use_key(result)])}。</li>",
    ]


def _curve_evidence(result: dict[str, Any]) -> list[tuple[str, Html]]:
    cov = result["coverage"]
    text = e(coverage_summary(cov))
    if cov.get("expected_days") is not None:
        text += (f"<div class='small muted'>研究窗口内预期观测日 {cov['expected_days']} 天"
                 f"（日历 <code>{e(cov['calendar'])}</code>）")
        if cov.get("pending_days"):
            text += f"；评估时尚未发布 {cov['pending_days']} 天（{e('、'.join(cov['pending_dates'][:5]))}）"
        if cov.get("missing_days"):
            text += f"；应已发布但缺失 {cov['missing_days']} 天（如 {e('、'.join(cov['missing_examples'][:3]))}）"
        if cov.get("calendar_unverified"):
            text += f"；日历未核验区间 {e('、'.join(cov['calendar_unverified']))}"
        if result["scope"].get("evaluated_at"):
            text += f"；评估时间 {e(str(result['scope']['evaluated_at'])[:16].replace('T', ' '))} UTC"
        text += "</div>"
    rows = [("日期覆盖", text)]
    gaps = [f"{name} 缺 {m['missing']} 天" for group in (cov.get("metrics") or {}).values()
            for name, m in group.items() if m.get("missing")]
    if gaps:
        rows.append(("指标覆盖", e("；".join(gaps)) + "<span class='muted small'>（利差与曲率要求所需期限同一天都有值；"
                                                      "有缺口的指标，期间统计标为已观测样本）</span>"))
    shares = [v["share"] for v in cov.get("tenors", {}).values()]
    if shares:
        rows.append(("期限覆盖", f"关键期限最低 {min(shares):.1%}（要求 ≥ {cov.get('min_coverage', 0):.0%}）"))
    return rows


def _curve_chart(result: dict[str, Any]) -> dict[str, Any]:
    """交互图表数据：直接取结果中的合格日度表，不插值、不填补。"""
    res = result.get("results", {})
    daily = result.get("tables", {}).get("daily", [])
    columns = {k for row in daily for k in row if k != "date"}
    tenors = sorted((c for c in columns if is_tenor(c)), key=lambda c: parse_tenor(c).months)
    return {
        "kind": "curve",
        "run_id": result.get("run_id"),
        "levels": list(res.get("levels", {})),
        "tenors": [{"code": t, "months": parse_tenor(t).months} for t in tenors],
        "spreads": [{"key": k, "label": spread_label(k)} for k in res.get("spreads", {})],
        "curvature": [{"key": f"curvature {k}", "label": curvature_label(k)} for k in res.get("curvature", {})],
        "rows": daily,
    }


def _ten_end(r: dict[str, Any]) -> str:
    ten = r["results"].get("levels", {}).get("10Y") or {}
    return num(ten.get("end")) + "%" if ten.get("end") is not None else "—"


CURVE = Renderer(
    key_stats=_curve_stats,
    method_items=_curve_method,
    coverage_title="数据覆盖",
    coverage_section=coverage_strip,
    evidence_rows=_curve_evidence,
    evidence_summary=lambda r: [f"日期覆盖：{coverage_summary(r['coverage'])}"],
    history_columns=(("10Y 期末", _ten_end),
                     ("10Y − 2Y 期末 bp", lambda r: num((r["results"].get("spreads", {}).get("2Y-10Y") or {}).get("end"), 0))),
    chart_data=_curve_chart,
    figures=(("curve_snapshots.png", "期初与期末收益率曲线"), ("key_tenors.png", "关键期限收益率"),
             ("spreads.png", "利差与曲率")),
    home_figures=(("curve_snapshots.png", "期初与期末收益率曲线"), ("spreads.png", "利差与曲率")),
    use_note="历史描述，不是预测或交易回测",
    state_description="利差是否倒挂、变陡或变平、覆盖是否完整",
    rule_params_label=lambda p: f"基本持平阈值 {p.get('flat_bp', FLAT_BP)} bp",
)


# ---- 假设平价债券情景 -------------------------------------------------------

def _focus(result: dict[str, Any]) -> str | None:
    bonds = result["results"].get("bonds", {})
    return "10Y" if "10Y" in bonds else next(iter(bonds), None)


def _bond_stats(result: dict[str, Any]) -> Html:
    res = result["results"]
    focus = _focus(result)
    if focus is None:
        return '<p class="muted">没有可计算的假设债券。</p>'
    b = res["bonds"][focus]
    up = next((r for r in res["scenarios"].get(focus, []) if r["shock_bp"] == 100), None)
    worst = res.get("worst_duration_convexity_error", {})
    longest = max(worst, key=lambda t: abs(worst[t]["duration_convexity_error_pp"])) if worst else None
    stats = [stat(f"{focus} 修正久期", f"{num(b['modified_duration'])} 年", f"凸性 {num(b['convexity'], 1)}"),
             stat(f"{focus} DV01", f"{num(b['dv01'], 4)}", "每 100 面值，收益率 −1 bp 的价格变化")]
    if up:
        stats.append(stat(f"{focus} 收益率 +100 bp", f"{num(up['full_pct'], 2, True)}%",
                          f"久期近似误差 {num(up['duration_error_pp'], 2, True)} pp"))
    if longest:
        w = worst[longest]
        stats.append(stat("久期 + 凸性最大误差", f"{num(w['duration_convexity_error_pp'], 3, True)} pp",
                          f"{longest}，冲击 {w['shock_bp']:+.0f} bp"))
    return _stats(stats)


def _bond_method(result: dict[str, Any]) -> list[Html]:
    m = result["methods"]
    p = m.get("parameters", {})
    return [
        f"<li>{e(m['description'])}</li>",
        f"<li>期限：{e('、'.join(p.get('tenors', [])))}（只用有票息的期限）；每年 {p.get('coupon_frequency', 2)} 次付息；"
        f"冲击：{e('、'.join(f'{x:+d}' for x in p.get('shocks_bp', [])))} bp，平移施加在每只债券自身的收益率上。</li>",
        f"<li>比较基准：{e(m.get('benchmark') or '—')}。误差 = 近似 − 完整重新定价，单位为百分点。</li>",
        "<li>独立核对：平价债券价格 = 面值；解析修正久期 = 平价债券封闭解 (1 − (1 + y/f)^(−n)) / y；"
        f"解析久期、凸性与 ±{p.get('finite_difference_bp', 1)} bp 有限差分完整重新定价一致。</li>",
        "<li>票面收益率不等于零息利率，本研究不做曲线换算；结果是假设现金流的数学性质，不是真实国债或基金的风险。</li>",
        f"<li>版本策略：{e(USE_LABEL[use_key(result)])}；冲击幅度是假设情景，不代表概率。</li>",
    ]


def _bond_assumptions(result: dict[str, Any]) -> Html:
    cov, bonds = result["coverage"], result["results"].get("bonds", {})
    rows = "".join(f"<tr><td>{e(t)}</td><td>{num(b['yield_pct'])}%</td><td>{num(b['price'], 4)}</td>"
                   f"<td>{num(b['macaulay_duration'], 3)}</td><td>{num(b['modified_duration'], 3)}</td>"
                   f"<td>{num(b['convexity'], 2)}</td><td>{num(b['dv01'], 4)}</td></tr>" for t, b in bonds.items())
    return (f"<p>基准日 <strong>{e(cov['base_date'])}</strong>：研究窗口 {e(result['scope'].get('start'))} 至 "
            f"{e(cov['window_end'])} 内所有所需期限同时有值的最后一天（距窗口终点 {cov['days_before_window_end']} 天）。</p>"
            '<div class="scroll"><table class="compact"><thead><tr><th>期限</th><th>票息 = 收益率</th><th>价格</th>'
            "<th>麦考利久期</th><th>修正久期</th><th>凸性</th><th>DV01</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


def _bond_evidence(result: dict[str, Any]) -> list[tuple[str, Html]]:
    cov = result["coverage"]
    rows = [("基准日与期限", f"{e(cov['base_date'])}；使用 {e('、'.join(cov['tenors_used']))}"
                           f"（请求 {e('、'.join(cov['tenors_requested']))}）")]
    cf = result["validation"].get("closed_form_checks")
    if cf:
        tol = cf.get("tolerances", {})
        rows.append(("封闭解与重新定价核对",
                     f"{chip(cf['status'], CHECK_LABEL.get(cf['status'], ''))} {cf['checked']} 项，未通过 {len(cf['failures'])} 项"
                     f"<span class='muted small'>平价价格容差 {tol.get('par_price_abs')}；封闭解相对容差 "
                     f"{tol.get('duration_closed_form_rel')}；有限差分相对容差 {tol.get('effective_rel')}</span>"))
    return rows


def _bond_chart(result: dict[str, Any]) -> dict[str, Any]:
    res = result["results"]
    return {"kind": "scenarios", "run_id": result.get("run_id"), "base_date": res.get("base_date"),
            "tenors": list(res.get("bonds", {})), "focus": _focus(result), "scenarios": res.get("scenarios", {})}


def _bond_summary(result: dict[str, Any]) -> list[str]:
    cf = result["validation"].get("closed_form_checks") or {}
    out = [f"基准日 {result['coverage']['base_date']}"]
    if cf:
        out.append(f"封闭解与重新定价核对 {cf['checked']} 项{'全部通过' if cf['status'] == 'pass' else '有未通过'}")
    return out


BOND = Renderer(
    key_stats=_bond_stats,
    method_items=_bond_method,
    coverage_title="假设与输入",
    coverage_section=_bond_assumptions,
    evidence_rows=_bond_evidence,
    evidence_summary=_bond_summary,
    history_columns=(("基准日", lambda r: r["results"].get("base_date") or "—"),
                     ("10Y 修正久期", lambda r: num(((r["results"].get("bonds") or {}).get("10Y") or {})
                                                   .get("modified_duration"))),
                     ("最大近似误差 pp", lambda r: num(max((abs(w["duration_convexity_error_pp"]) for w in
                                                         (r["results"].get("worst_duration_convexity_error") or {})
                                                         .values()), default=None), 3))),
    chart_data=_bond_chart,
    figures=(("scenario_price.png", "价格变化：完整重新定价与近似"), ("approx_error.png", "久期 + 凸性近似误差")),
    home_figures=(("scenario_price.png", "价格变化：完整重新定价与近似"), ("approx_error.png", "久期 + 凸性近似误差")),
    use_note="假设情景，不是预测，也不是真实债券或基金的风险",
    state_description="近似误差档位、只用久期时的误差方向",
    rule_params_label=lambda p: f"误差档位 {p.get('error_bands_pp')} pp",
)


# ---- 未注册分支 ---------------------------------------------------------------

def _unsupported_html(_: dict[str, Any]) -> Html:
    return '<p class="muted">该研究分支暂无展示组件；请查看完整报告与结构化结果。</p>'


UNSUPPORTED = Renderer(
    key_stats=_unsupported_html,
    method_items=lambda r: [f"<li>{e(r.get('methods', {}).get('description', '—'))}</li>"],
    coverage_title="覆盖",
    coverage_section=_unsupported_html,
    evidence_rows=lambda r: [],
    evidence_summary=lambda r: [],
    history_columns=(),
    chart_data=lambda r: None,
    figures=(),
    home_figures=(),
    use_note="该研究分支暂无展示组件，用途见完整报告",
    state_description="定性状态",
    supported=False,
)

RENDERERS: dict[str, Renderer] = {"rates_curve": CURVE, "par_bond_scenarios": BOND}


def get_renderer(branch: str) -> Renderer:
    return RENDERERS.get(branch, UNSUPPORTED)
