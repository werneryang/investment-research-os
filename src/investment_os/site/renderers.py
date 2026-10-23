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
from .findings_en import COVERAGE_LABEL_EN, coverage_summary_en
from .i18n import L, is_en, te

Html = str
Text = tuple[str, str]  # (中文, English)，取值时按当前语言


@dataclass(frozen=True)
class Renderer:
    key_stats: Callable[[dict[str, Any]], Html]
    method_items: Callable[[dict[str, Any]], list[Html]]
    coverage_title_t: Text
    coverage_section: Callable[[dict[str, Any]], Html]
    evidence_rows: Callable[[dict[str, Any]], list[tuple[str, Html]]]
    evidence_summary: Callable[[dict[str, Any]], list[str]]
    history_columns_t: tuple[tuple[Text, Callable[[dict[str, Any]], str]], ...]
    chart_data: Callable[[dict[str, Any]], dict[str, Any] | None]
    figures_t: tuple[tuple[str, Text], ...]
    use_note_t: Text
    state_description_t: Text
    rule_params_label: Callable[[dict[str, Any]], str] = field(default=lambda p: "")
    supported: bool = True

    @property
    def coverage_title(self) -> str:
        return L(*self.coverage_title_t)

    @property
    def history_columns(self) -> tuple[tuple[str, Callable[[dict[str, Any]], str]], ...]:
        return tuple((L(*label), fn) for label, fn in self.history_columns_t)

    @property
    def figures(self) -> tuple[tuple[str, str], ...]:
        return tuple((f, L(*alt)) for f, alt in self.figures_t)

    @property
    def use_note(self) -> str:
        return L(*self.use_note_t)

    @property
    def state_description(self) -> str:
        return L(*self.state_description_t)


def coverage_text(cov: dict[str, Any]) -> str:
    """一句话的覆盖说明（按当前语言）。"""
    return coverage_summary_en(cov) if is_en() else coverage_summary(cov)


def coverage_label(cov: dict[str, Any]) -> str:
    return (COVERAGE_LABEL_EN if is_en() else COVERAGE_LABEL)[completeness(cov)]


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
        stats.append(stat(L("10 年期收益率", "10-year yield"), f"{num(ten['start'])}% → {num(ten['end'])}%",
                          f"{num(ten['change_bp'], 0, True)} bp"))
    for key, sp in res.get("spreads", {}).items():
        if sp.get("observations"):
            inv = sp.get("inversion")
            if not inv:
                note = L("期间统计不输出", "Period statistics not reported")
            elif sp.get("sample") == "observed":
                note = L(f"已观测 {inv['observations']} 天中倒挂 {inv['inverted_days']} 天",
                         f"Inverted {inv['inverted_days']} of {inv['observations']} observed days")
            else:
                note = L(f"倒挂 {inv['inverted_days']} 天", f"Inverted {inv['inverted_days']} days")
            stats.append(stat(L(f"{spread_label(key)} 利差", f"{spread_label(key)} spread"),
                              f"{num(sp['start'], 0)} → {num(sp['end'], 0)} bp", note))
    if cov.get("expected_days"):
        due = cov.get("due_days", cov["expected_days"])
        note = coverage_label(cov)
        if cov.get("pending_days"):
            note += L(f"；另 {cov['pending_days']} 天未取得（未到保守可用时点）",
                      f"; {cov['pending_days']} more not yet retrieved (not past the conservative availability time)")
        stats.append(stat(L("日期覆盖", "Date coverage"),
                          f"{due - cov.get('missing_days', 0)} / {due} {L('天', 'days')}", note))
    return _stats(stats)


def _curve_method(result: dict[str, Any]) -> list[Html]:
    m = result["methods"]
    params = m.get("parameters", {})
    sep = L("、", ", ")
    spreads = sep.join(spread_label(f"{a}-{b}") for a, b in params.get("spreads", []))
    curv = params.get("curvature")
    cover = params.get("min_coverage", 0)
    return [
        f"<li>{te(m['description'])}</li>",
        L(f"<li>关键期限：{e('、'.join(params.get('key_tenors', [])))}；利差（长端 − 短端）：{e(spreads or '无')}"
          + (f"；曲率：{e(curvature_label('/'.join(curv)))}" if curv else "") + "。</li>",
          f"<li>Key tenors: {e(', '.join(params.get('key_tenors', [])))}; spreads (long − short): {e(spreads or 'none')}"
          + (f"; curvature: {e(curvature_label('/'.join(curv)))}" if curv else "") + ".</li>"),
        f"<li>{L('比较基准：', 'Benchmark: ')}{te(m.get('benchmark') or '—')}{L('。', '.')}</li>",
        L(f"<li>覆盖要求：关键期限有效观测占应已发布观测日的比例不低于 {cover:.0%}，"
          "不足时依赖它的结论不输出。达到要求不等于期间完整：期间完整另需所有预期日期都有数据、且日期在日历核验范围内；"
          "有缺口的指标，期间统计只描述已观测日期。数据下载时尚未到保守可用时点的日期单独列为「未取得」，不计入覆盖；"
          "保守可用时点不是实际发布时间，未取得不代表已确认尚未发布。</li>",
          f"<li>Coverage requirement: valid key-tenor observations must cover at least {cover:.0%} of due observation "
          "dates, otherwise conclusions that depend on them are not reported. Meeting this is not the same as a complete "
          "period: completeness also needs every expected date to have data and to fall within the verified calendar. "
          "For metrics with gaps, period statistics describe observed dates only. Dates not yet past the conservative "
          "availability time when the data was downloaded are listed separately as \u201cnot yet retrieved\u201d and "
          "are not counted; that time is not the actual release time, so \u201cnot yet retrieved\u201d does not "
          "confirm a date was unpublished.</li>"),
        L("<li>倒挂定义为利差严格小于 0；恰为 0 的日期单独计数，不计入倒挂。</li>",
          "<li>A spread is inverted when it is strictly below 0; days at exactly 0 are counted separately, "
          "not as inverted.</li>"),
        f"<li>{L('时间规则：', 'Timing rule: ')}{te(m.get('availability_rule') or '—')}{L('；版本策略：', '; version policy: ')}"
        f"{e(USE_LABEL[use_key(result)])}{L('。', '.')}</li>",
    ]


def _curve_evidence(result: dict[str, Any]) -> list[tuple[str, Html]]:
    cov = result["coverage"]
    sep, semi = L("、", ", "), L("；", "; ")
    text = e(coverage_text(cov))
    if cov.get("expected_days") is not None:
        text += "<div class='small muted'>" + L(
            f"研究窗口内预期观测日 {cov['expected_days']} 天（日历 <code>{e(cov['calendar'])}</code>）",
            f"{cov['expected_days']} expected observation dates in the study window "
            f"(calendar <code>{e(cov['calendar'])}</code>)")
        if cov.get("pending_days"):
            dates = e(sep.join(cov["pending_dates"][:5]))
            text += semi + L(f"未取得 {cov['pending_days']} 天（{dates}，数据下载时尚未到保守可用时点，不代表已确认尚未发布）",
                             f"{cov['pending_days']} not yet retrieved ({dates}; not past the conservative availability "
                             "time when downloaded, which does not confirm they were unpublished)")
        if cov.get("missing_days"):
            ex = e(sep.join(cov["missing_examples"][:3]))
            text += semi + L(f"应已发布但缺失 {cov['missing_days']} 天（如 {ex}）",
                             f"{cov['missing_days']} due but missing (e.g. {ex})")
        if cov.get("calendar_unverified"):
            text += semi + L("日历未核验区间 ", "calendar not verified for ") + e(sep.join(cov["calendar_unverified"]))
        if cov.get("data_retrieved_at"):
            text += semi + L("数据最近一次下载 ", "data last downloaded ") + \
                e(str(cov["data_retrieved_at"])[:16].replace("T", " ")) + " UTC"
        if cov.get("availability_rule"):
            text += semi + L("保守可用时点规则：", "conservative availability rule: ") + te(cov["availability_rule"])
        if result["scope"].get("evaluated_at"):
            text += semi + L("评估时间 ", "evaluated at ") + \
                e(str(result["scope"]["evaluated_at"])[:16].replace("T", " ")) + " UTC"
        text += "</div>"
    rows = [(L("日期覆盖", "Date coverage"), text)]
    gaps = [L(f"{name} 缺 {m['missing']} 天", f"{name} missing {m['missing']} days")
            for group in (cov.get("metrics") or {}).values() for name, m in group.items() if m.get("missing")]
    if gaps:
        rows.append((L("指标覆盖", "Metric coverage"), e(semi.join(gaps)) + "<span class='muted small'>" + L(
            "（利差与曲率要求所需期限同一天都有值；有缺口的指标，期间统计标为已观测样本）",
            " (spreads and curvature need all required tenors on the same day; for metrics with gaps, period "
            "statistics are marked as observed samples)") + "</span>"))
    shares = [v["share"] for v in cov.get("tenors", {}).values()]
    if shares:
        rows.append((L("期限覆盖", "Tenor coverage"),
                     L(f"关键期限最低 {min(shares):.1%}（要求 ≥ {cov.get('min_coverage', 0):.0%}）",
                       f"Lowest key tenor {min(shares):.1%} (required ≥ {cov.get('min_coverage', 0):.0%})")))
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
    coverage_title_t=("数据覆盖", "Data coverage"),
    coverage_section=coverage_strip,
    evidence_rows=_curve_evidence,
    evidence_summary=lambda r: [L("日期覆盖：", "Date coverage: ") + coverage_text(r["coverage"])],
    history_columns_t=((("10Y 期末", "10Y at end"), _ten_end),
                       (("10Y − 2Y 期末 bp", "10Y − 2Y at end, bp"),
                        lambda r: num((r["results"].get("spreads", {}).get("2Y-10Y") or {}).get("end"), 0))),
    chart_data=_curve_chart,
    figures_t=(("curve_snapshots.png", ("期初与期末收益率曲线", "Yield curve at start and end of period")),
               ("key_tenors.png", ("关键期限收益率", "Key-tenor yields")),
               ("spreads.png", ("利差与曲率", "Spreads and curvature"))),
    use_note_t=("历史描述，不是预测或交易回测", "Historical description, not a forecast or trading backtest"),
    state_description_t=("利差是否倒挂、变陡或变平、覆盖是否完整",
                         "whether spreads are inverted, steepened or flattened, and whether coverage is complete"),
    rule_params_label=lambda p: L(f"基本持平阈值 {p.get('flat_bp', FLAT_BP)} bp",
                                  f"roughly-flat threshold {p.get('flat_bp', FLAT_BP)} bp"),
)


# ---- 假设平价债券情景 -------------------------------------------------------

def _focus(result: dict[str, Any]) -> str | None:
    bonds = result["results"].get("bonds", {})
    return "10Y" if "10Y" in bonds else next(iter(bonds), None)


def _bond_stats(result: dict[str, Any]) -> Html:
    res = result["results"]
    focus = _focus(result)
    if focus is None:
        return f'<p class="muted">{L("没有可计算的假设债券。", "No hypothetical bond could be computed.")}</p>'
    b = res["bonds"][focus]
    up = next((r for r in res["scenarios"].get(focus, []) if r["shock_bp"] == 100), None)
    worst = res.get("worst_duration_convexity_error", {})
    longest = max(worst, key=lambda t: abs(worst[t]["duration_convexity_error_pp"])) if worst else None
    stats = [stat(L(f"{focus} 修正久期", f"{focus} modified duration"),
                  f"{num(b['modified_duration'])} {L('年', 'years')}", L("凸性 ", "Convexity ") + num(b["convexity"], 1)),
             stat(f"{focus} DV01", f"{num(b['dv01'], 4)}",
                  L("每 100 面值，收益率 −1 bp 的价格变化", "Price change per 100 face for a −1 bp yield move"))]
    if up:
        stats.append(stat(L(f"{focus} 收益率 +100 bp", f"{focus} yield +100 bp"), f"{num(up['full_pct'], 2, True)}%",
                          L("久期近似误差 ", "Duration approximation error ")
                          + f"{num(up['duration_error_pp'], 2, True)} pp"))
    if longest:
        w = worst[longest]
        err = num(w["duration_convexity_error_pp"], 3, True)
        stats.append(stat(L("久期 + 凸性最大绝对误差", "Max abs. duration + convexity error"),
                          f"{num(abs(w['duration_convexity_error_pp']), 3)} pp",
                          L(f"{longest}，冲击 {w['shock_bp']:+.0f} bp；对应误差 {err} pp（近似 − 完整重新定价）",
                            f"{longest}, shock {w['shock_bp']:+.0f} bp; signed error {err} pp "
                            "(approximation − full repricing)")))
    return _stats(stats)


def _bond_method(result: dict[str, Any]) -> list[Html]:
    m = result["methods"]
    p = m.get("parameters", {})
    tenors = e(L("、", ", ").join(p.get("tenors", [])))
    shocks = e(L("、", ", ").join(f"{x:+d}" for x in p.get("shocks_bp", [])))
    fd = p.get("finite_difference_bp", 1)
    return [
        f"<li>{te(m['description'])}</li>",
        L(f"<li>期限：{tenors}（只用有票息的期限）；每年 {p.get('coupon_frequency', 2)} 次付息；"
          f"冲击：{shocks} bp，平移施加在每只债券自身的收益率上。</li>",
          f"<li>Tenors: {tenors} (coupon-bearing tenors only); {p.get('coupon_frequency', 2)} coupons a year; "
          f"shocks: {shocks} bp, applied as parallel shifts to each bond's own yield.</li>"),
        f"<li>{L('比较基准：', 'Benchmark: ')}{te(m.get('benchmark') or '—')}"
        + L("。误差 = 近似 − 完整重新定价，单位为百分点。</li>",
            ". Error = approximation − full repricing, in percentage points.</li>"),
        L("<li>独立核对：平价债券价格 = 面值；解析修正久期 = 平价债券封闭解 (1 − (1 + y/f)^(−n)) / y；"
          f"解析久期、凸性与 ±{fd} bp 有限差分完整重新定价一致。</li>",
          "<li>Independent checks: par bond price = face value; analytic modified duration = the par-bond closed form "
          f"(1 − (1 + y/f)^(−n)) / y; analytic duration and convexity agree with ±{fd} bp finite-difference full "
          "repricing.</li>"),
        L("<li>票面收益率不等于零息利率，本研究不做曲线换算；结果是假设现金流的数学性质，不是真实国债或基金的风险。</li>",
          "<li>Par yields are not zero-coupon rates, and this study does not convert the curve; results are "
          "mathematical properties of hypothetical cash flows, not the risk of a real Treasury or fund.</li>"),
        f"<li>{L('版本策略：', 'Version policy: ')}{e(USE_LABEL[use_key(result)])}"
        + L("；冲击幅度是假设情景，不代表概率。</li>", "; shock sizes are hypothetical scenarios, not probabilities.</li>"),
    ]


def _bond_assumptions(result: dict[str, Any]) -> Html:
    cov, bonds = result["coverage"], result["results"].get("bonds", {})
    rows = "".join(f"<tr><td>{e(t)}</td><td>{num(b['yield_pct'])}%</td><td>{num(b['price'], 4)}</td>"
                   f"<td>{num(b['macaulay_duration'], 3)}</td><td>{num(b['modified_duration'], 3)}</td>"
                   f"<td>{num(b['convexity'], 2)}</td><td>{num(b['dv01'], 4)}</td></tr>" for t, b in bonds.items())
    base, start, end = e(cov["base_date"]), e(result["scope"].get("start")), e(cov["window_end"])
    head = L(f"<p>基准日 <strong>{base}</strong>：研究窗口 {start} 至 {end} 内所有所需期限同时有值的最后一天"
             f"（距窗口终点 {cov['days_before_window_end']} 天）。</p>",
             f"<p>Base date <strong>{base}</strong>: the last day in the study window {start} to {end} on which all "
             f"required tenors have values ({cov['days_before_window_end']} days before the window end).</p>")
    cols = L("<th>期限</th><th>票息 = 收益率</th><th>价格</th><th>麦考利久期</th><th>修正久期</th><th>凸性</th>",
             "<th>Tenor</th><th>Coupon = yield</th><th>Price</th><th>Macaulay duration</th><th>Modified duration</th>"
             "<th>Convexity</th>")
    return (head + f'<div class="scroll"><table class="compact"><thead><tr>{cols}<th>DV01</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def _bond_evidence(result: dict[str, Any]) -> list[tuple[str, Html]]:
    cov = result["coverage"]
    sep = L("、", ", ")
    used, asked = e(sep.join(cov["tenors_used"])), e(sep.join(cov["tenors_requested"]))
    rows = [(L("基准日与期限", "Base date and tenors"),
             L(f"{e(cov['base_date'])}；使用 {used}（请求 {asked}）",
               f"{e(cov['base_date'])}; using {used} (requested {asked})"))]
    cf = result["validation"].get("closed_form_checks")
    if cf:
        tol = cf.get("tolerances", {})
        rows.append((L("封闭解与重新定价核对", "Closed-form and repricing checks"),
                     f"{chip(cf['status'], CHECK_LABEL.get(cf['status'], ''))} " + L(
                         f"{cf['checked']} 项，未通过 {len(cf['failures'])} 项"
                         f"<span class='muted small'>平价价格容差 {tol.get('par_price_abs')}；封闭解相对容差 "
                         f"{tol.get('duration_closed_form_rel')}；有限差分相对容差 {tol.get('effective_rel')}</span>",
                         f"{cf['checked']} checks, {len(cf['failures'])} failed"
                         f"<span class='muted small'> par price tolerance {tol.get('par_price_abs')}; closed-form "
                         f"relative tolerance {tol.get('duration_closed_form_rel')}; finite-difference relative "
                         f"tolerance {tol.get('effective_rel')}</span>")))
    return rows


def _bond_chart(result: dict[str, Any]) -> dict[str, Any]:
    res = result["results"]
    return {"kind": "scenarios", "run_id": result.get("run_id"), "base_date": res.get("base_date"),
            "tenors": list(res.get("bonds", {})), "focus": _focus(result), "scenarios": res.get("scenarios", {})}


def _bond_summary(result: dict[str, Any]) -> list[str]:
    cf = result["validation"].get("closed_form_checks") or {}
    out = [L("基准日 ", "Base date ") + str(result["coverage"]["base_date"])]
    if cf:
        ok = cf["status"] == "pass"
        out.append(L(f"封闭解与重新定价核对 {cf['checked']} 项{'全部通过' if ok else '有未通过'}",
                     f"{cf['checked']} closed-form and repricing checks, {'all passed' if ok else 'some failed'}"))
    return out


BOND = Renderer(
    key_stats=_bond_stats,
    method_items=_bond_method,
    coverage_title_t=("假设与输入", "Assumptions and inputs"),
    coverage_section=_bond_assumptions,
    evidence_rows=_bond_evidence,
    evidence_summary=_bond_summary,
    history_columns_t=((("基准日", "Base date"), lambda r: r["results"].get("base_date") or "—"),
                       (("10Y 修正久期", "10Y modified duration"),
                        lambda r: num(((r["results"].get("bonds") or {}).get("10Y") or {}).get("modified_duration"))),
                       (("最大绝对误差 pp", "Max abs. error, pp"),
                        lambda r: num(max((abs(w["duration_convexity_error_pp"]) for w in
                                           (r["results"].get("worst_duration_convexity_error") or {}).values()),
                                          default=None), 3))),
    chart_data=_bond_chart,
    figures_t=(("scenario_price.png", ("价格变化：完整重新定价与近似", "Price change: full repricing and approximations")),
               ("approx_error.png", ("久期 + 凸性近似误差", "Duration + convexity approximation error"))),
    use_note_t=("假设情景，不是预测，也不是真实债券或基金的风险",
                "Hypothetical scenario, not a forecast, and not the risk of a real bond or fund"),
    state_description_t=("近似误差档位、只用久期时的误差方向",
                         "the approximation-error band and the direction of the duration-only error"),
    rule_params_label=lambda p: L(f"误差档位 {p.get('error_bands_pp')} pp", f"error bands {p.get('error_bands_pp')} pp"),
)


# ---- 未注册分支 ---------------------------------------------------------------

def _unsupported_html(_: dict[str, Any]) -> Html:
    return '<p class="muted">' + L("该研究分支暂无展示组件；请查看完整报告与结构化结果。",
                                   "This research branch has no display component yet; see the full report and "
                                   "structured result.") + "</p>"


UNSUPPORTED = Renderer(
    key_stats=_unsupported_html,
    method_items=lambda r: [f"<li>{te(r.get('methods', {}).get('description', '—'))}</li>"],
    coverage_title_t=("覆盖", "Coverage"),
    coverage_section=_unsupported_html,
    evidence_rows=lambda r: [],
    evidence_summary=lambda r: [],
    history_columns_t=(),
    chart_data=lambda r: None,
    figures_t=(),
    use_note_t=("该研究分支暂无展示组件，用途见完整报告", "No display component for this branch yet; see the full report for its use"),
    state_description_t=("定性状态", "qualitative state"),
    supported=False,
)

RENDERERS: dict[str, Renderer] = {"rates_curve": CURVE, "par_bond_scenarios": BOND}


def get_renderer(branch: str) -> Renderer:
    return RENDERERS.get(branch, UNSUPPORTED)
