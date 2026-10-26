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
    inline_visuals: bool = False

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


# ---- 曲线变化的会计分解（解释与归因） --------------------------------------------

_ATTR_NAMES = {"real": ("实际收益率", "Real yield"), "breakeven": ("盈亏平衡通胀", "Breakeven inflation"),
               "policy": ("联邦基金有效利率", "Effective fed funds rate"),
               "spread": ("2 年期与联邦基金利率之差", "2-year minus fed funds"), "residual": ("取整残差", "Rounding residual")}


def _attr_stats(result: dict[str, Any]) -> Html:
    r = result["results"]
    if not r.get("long_end"):
        return f'<p class="muted">{L("没有可分解的期间。", "No period could be decomposed.")}</p>'
    lg, sh, sl = r["long_end"], r["short_end"], r["slope"]
    ident = result["validation"].get("identity_check", {})
    return _stats([
        stat(L(f"{lg['tenor']} 变化", f"{lg['tenor']} change"), f"{num(lg['nominal']['change_bp'], 0, True)} bp",
             L(f"实际 {num(lg['real']['change_bp'], 0, True)} · 通胀补偿 {num(lg['breakeven']['change_bp'], 0, True)}",
               f"real {num(lg['real']['change_bp'], 0, True)} · breakeven {num(lg['breakeven']['change_bp'], 0, True)}")),
        stat(L(f"{sh['tenor']} 变化", f"{sh['tenor']} change"), f"{num(sh['nominal']['change_bp'], 0, True)} bp",
             L(f"政策利率 {num(sh['policy']['change_bp'], 0, True)} · 利差 {num(sh['spread']['change_bp'], 0, True)}",
               f"policy rate {num(sh['policy']['change_bp'], 0, True)} · spread {num(sh['spread']['change_bp'], 0, True)}")),
        stat(L(f"{sl['label']} 变化", f"{sl['label']} change"), f"{num(sl['change_bp'], 0, True)} bp",
             L(f"{num(sl['start'])} → {num(sl['end'])} 个百分点", f"{num(sl['start'])} → {num(sl['end'])} pp")),
        stat(L("恒等式最大残差", "Max identity residual"),
             f"{num(ident.get('max_abs_level_residual_bp'), 2)} bp",
             L(f"{ident.get('checked', 0)} 个共同日期，容差 {ident.get('tolerance_bp')} bp",
               f"{ident.get('checked', 0)} common dates, tolerance {ident.get('tolerance_bp')} bp")),
    ])


def _attr_method(result: dict[str, Any]) -> list[Html]:
    th = result["results"].get("thresholds", {})
    return [
        f"<li>{te(result['methods']['description'])}</li>",
        L(f"<li>占比只在名义变化不小于 {th.get('share_min_bp')} bp 时给出；期初、期末各前后移动 "
          f"{th.get('sensitivity_days')} 个共同日期，占比范围超过 {th.get('sensitivity_max_range_pp')} 个百分点时只描述方向。</li>",
          f"<li>Shares are given only when the nominal change is at least {th.get('share_min_bp')} bp; when shifting the "
          f"start and end by up to {th.get('sensitivity_days')} common dates moves a share by more than "
          f"{th.get('sensitivity_max_range_pp')} percentage points, only the direction is described.</li>"),
        L("<li>解读的假设：盈亏平衡通胀含通胀风险溢价与流动性溢价，不等于通胀预期；实际收益率含实际期限溢价；"
          "2 年期与联邦基金利率之差混合了政策路径预期与期限溢价，本研究不能区分。</li>",
          "<li>Interpretive assumptions: breakeven inflation includes inflation-risk and liquidity premia and is not "
          "expected inflation; the real yield includes a real term premium; the 2-year-minus-fed-funds spread mixes "
          "expected policy and term premium, which this study cannot separate.</li>"),
        L("<li>CPI 同比与美联储总资产只作背景，不参与分解；不作因果主张，也不是预测。</li>",
          "<li>CPI inflation and Fed total assets are background only and not part of the decomposition; no causal "
          "claim and no forecast.</li>"),
        f"<li>{L('版本策略：', 'Version policy: ')}{e(USE_LABEL[use_key(result)])}</li>",
    ]


def _attr_detail(result: dict[str, Any]) -> Html:
    r, cov = result["results"], result["coverage"]
    if not r.get("long_end"):
        return ""
    lg, sh, sl, sens = r["long_end"], r["short_end"], r["slope"], r["sensitivity"]

    def share(v: Any) -> str:
        return "—" if v is None else f"{num(v, 0)}%"

    def rng(k: str) -> str:
        x = sens.get(k, {})
        if x.get("min") is None:
            return "—"
        return f"{num(x['min'], 0)}%–{num(x['max'], 0)}%" + ("" if x["stable"] else L("（不稳定）", " (unstable)"))

    rows = [
        (f"{lg['tenor']}", lg["nominal"], "", ""),
        (L(*_ATTR_NAMES["real"]), lg["real"], share(lg["shares_pct"]["real"]), rng("real")),
        (L(*_ATTR_NAMES["breakeven"]), lg["breakeven"], share(lg["shares_pct"]["breakeven"]), rng("breakeven")),
        (f"{sh['tenor']}", sh["nominal"], "", ""),
        (L(*_ATTR_NAMES["policy"]), sh["policy"], share(sh["shares_pct"]["policy"]), rng("policy")),
        (L(*_ATTR_NAMES["spread"]), sh["spread"], share(sh["shares_pct"]["spread"]), rng("spread")),
        (sl["label"], {"start": sl["start"], "end": sl["end"], "change_bp": sl["change_bp"]}, "", ""),
    ]
    body = "".join(f"<tr><td>{e(n)}</td><td>{num(x['start'])}</td><td>{num(x['end'])}</td>"
                   f"<td>{num(x['change_bp'], 0, True)}</td><td>{a}</td><td>{b}</td></tr>" for n, x, a, b in rows)
    head = L("<th>项目</th><th>期初 %</th><th>期末 %</th><th>变化 bp</th><th>占名义变化</th><th>端点敏感性</th>",
             "<th>Item</th><th>Start %</th><th>End %</th><th>Change bp</th><th>Share of nominal</th>"
             "<th>Endpoint sensitivity</th>")
    # 不足 0.5 bp 的取整残差显示为 0，避免出现「−0」
    contrib = " · ".join(f"{L(*_ATTR_NAMES[k])} {num(0.0 if abs(v) < 0.5 else v, 0, True)}"
                         for k, v in sl["contributions_bp"].items())
    out = (L(f"<p>{e(cov['start_date'])} 至 {e(cov['end_date'])}，共同观测日 {cov['common_days']} 天"
             f"（请求 {e(cov['requested_start'])} 至 {e(cov['requested_end'])}）。</p>",
             f"<p>{e(cov['start_date'])} to {e(cov['end_date'])}, {cov['common_days']} common observation dates "
             f"(requested {e(cov['requested_start'])} to {e(cov['requested_end'])}).</p>")
           + f'<div class="scroll"><table class="compact"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
           + f'<p class="small">{L("斜率变化的组成（短端项以负号计入）：", "Slope change components (short-end terms enter with a minus sign): ")}{contrib} bp</p>')
    bg = r.get("background", {})
    notes = []
    if "cpi_yoy" in bg:
        c = bg["cpi_yoy"]
        notes.append(L(f"CPI 同比 {c['start']['month']} {num(c['start']['value_pct'], 1)}% → {c['end']['month']} "
                       f"{num(c['end']['value_pct'], 1)}%",
                       f"CPI inflation {c['start']['month']} {num(c['start']['value_pct'], 1)}% → {c['end']['month']} "
                       f"{num(c['end']['value_pct'], 1)}%"))
    if "fed_assets" in bg:
        f = bg["fed_assets"]
        notes.append(L(f"美联储总资产 {num(f['change_pct'], 1, True)}%（{f['start']['date']} → {f['end']['date']}）",
                       f"Fed total assets {num(f['change_pct'], 1, True)}% ({f['start']['date']} → {f['end']['date']})"))
    if notes:
        out += (f'<p class="small muted">{L("背景（只作描述，不参与分解）：", "Background (descriptive only, not part of the decomposition): ")}'
                + e(L("；", "; ").join(notes)) + "</p>")
    return out


def _attr_evidence(result: dict[str, Any]) -> list[tuple[str, Html]]:
    v, cov = result["validation"], result["coverage"]
    rows = []
    ident = v.get("identity_check")
    if ident:
        rows.append((L("恒等式核对", "Identity check"),
                     f"{chip(ident['status'], CHECK_LABEL.get(ident['status'], ''))} " + L(
                         f"{ident['checked']} 个共同日期，名义 − 实际 − 盈亏平衡的最大残差 "
                         f"{num(ident['max_abs_level_residual_bp'], 2)} bp（容差 {ident['tolerance_bp']} bp）",
                         f"{ident['checked']} common dates; max residual of nominal − real − breakeven "
                         f"{num(ident['max_abs_level_residual_bp'], 2)} bp (tolerance {ident['tolerance_bp']} bp)")))
    cc = v.get("cross_check")
    if cc and cc.get("matched"):
        rows.append((L("同源一致性检查", "Same-source consistency check"),
                     f"{chip(cc['status'], CHECK_LABEL.get(cc['status'], ''))} " + L(
                         f"Treasury {cc['tenor']} 与 {e(cc['against'])}：{cc['matched']} 个共同日期，最大差 "
                         f"{num(cc.get('max_abs_diff'), 4)}；两者同源，不是独立验证",
                         f"Treasury {cc['tenor']} vs {e(cc['against'])}: {cc['matched']} common dates, max diff "
                         f"{num(cc.get('max_abs_diff'), 4)}; same upstream, not independent validation")))
    rows.append((L("共同观测日期", "Common observation dates"),
                 L(f"{cov['common_days']} 天；不插值、不前值填充", f"{cov['common_days']} dates; no interpolation or carry-forward")))
    sens = result["results"].get("sensitivity", {})
    stable = [L(*_ATTR_NAMES[k]) for k in ("real", "breakeven", "policy", "spread") if sens.get(k, {}).get("stable")]
    rows.append((L("端点敏感性", "Endpoint sensitivity"),
                 L(f"期初、期末各前后移动 {sens.get('shift_days')} 个共同日期；占比稳定：",
                   f"start and end shifted by up to {sens.get('shift_days')} common dates; stable shares: ")
                 + (e(L("、", ", ").join(stable)) if stable else L("无", "none"))))
    return rows


def _attr_summary(result: dict[str, Any]) -> list[str]:
    ident = result["validation"].get("identity_check", {})
    out = [L("共同观测日 ", "Common dates ") + str(result["coverage"].get("common_days"))]
    if ident:
        out.append(L(f"恒等式核对{'通过' if ident['status'] == 'pass' else '未通过'}",
                     f"identity check {'passed' if ident['status'] == 'pass' else 'failed'}"))
    return out


ATTRIBUTION = Renderer(
    key_stats=_attr_stats,
    method_items=_attr_method,
    coverage_title_t=("分解明细与背景", "Decomposition detail and background"),
    coverage_section=_attr_detail,
    evidence_rows=_attr_evidence,
    evidence_summary=_attr_summary,
    history_columns_t=((("期末", "End"), lambda r: r["results"].get("end_date") or "—"),
                       (("10Y 变化 bp", "10Y change bp"),
                        lambda r: num(((r["results"].get("long_end") or {}).get("nominal") or {}).get("change_bp"), 0, True)),
                       (("斜率变化 bp", "Slope change bp"),
                        lambda r: num((r["results"].get("slope") or {}).get("change_bp"), 0, True))),
    chart_data=lambda r: None,
    figures_t=(("attribution_bars.png", ("各部分对 10Y、2Y 与斜率变化的贡献",
                                         "Contributions to the 10Y, 2Y and slope changes")),
               ("attribution_path.png", ("各部分相对期初的逐日累计变化", "Daily cumulative change of each part"))),
    use_note_t=("使用最新修订数据的会计分解，不是因果解释或预测",
                "Accounting decomposition on the latest revision; not a causal explanation or forecast"),
    state_description_t=("10Y 的主要来源、2Y 相对政策利率的方向、斜率变陡或变平",
                         "the main source of the 10Y move, the 2Y move relative to the policy rate, and whether the "
                         "curve steepened or flattened"),
    rule_params_label=lambda p: L(f"基本持平阈值 {p.get('flat_bp')} bp", f"flat threshold {p.get('flat_bp')} bp"),
)


# ---- 美国主要资产的长期回报与风险（描述与比较） ----------------------------------

_ASSET_NAMES = {"SP500": ("标普 500", "S&P 500"), "SMALLCAP": ("小盘股", "Small caps"),
                "TBOND10Y": ("10 年期国债", "10-year Treasury"), "BAA": ("Baa 公司债", "Baa corporate bonds"),
                "TBILL3M": ("3 个月国库券", "3-month T-bills"), "REALESTATE": ("房地产", "Real estate"),
                "GOLD": ("黄金", "Gold")}


def _an(a: str) -> str:
    return L(*_ASSET_NAMES.get(a, (a, a)))


def _pc(v: Any, digits: int = 1, signed: bool = False) -> str:
    return "—" if v is None else f"{num(v * 100, digits, signed)}%"


def _asset_stats(result: dict[str, Any]) -> Html:
    r = result["results"]
    nom, real = r.get("nominal", {}), r.get("real", {})
    if "SP500" not in nom:
        return f'<p class="muted">{L("没有可计算的资产。", "No asset could be computed.")}</p>'
    sp = nom["SP500"]
    items = [stat(L("标普 500 年化回报", "S&P 500 annualized return"), _pc(sp["geometric"]),
                  L(f"{r['first_year']}–{r['last_year']}，波动率 {_pc(sp['volatility'])}",
                    f"{r['first_year']}–{r['last_year']}, volatility {_pc(sp['volatility'])}"))]
    if real.get("SP500"):
        rs = real["SP500"]
        items.append(stat(L("扣除通胀后", "After inflation"), _pc(rs["geometric"]),
                          L(f"{rs['first_year']}–{rs['last_year']}；10 年期国债 {_pc(real.get('TBOND10Y', {}).get('geometric'))}",
                            f"{rs['first_year']}–{rs['last_year']}; 10Y Treasury {_pc(real.get('TBOND10Y', {}).get('geometric'))}")))
    me = r.get("monthly_equity") or {}
    items.append(stat(L("股票最大回撤", "Equity max drawdown"), _pc(me.get("max_drawdown", sp["max_drawdown"])),
                      L(f"月度，{me['peak']} 至 {me['trough']}" if me else "年度数据",
                        f"monthly, {me['peak']} to {me['trough']}" if me else "annual data")))
    corr = r.get("correlations", {})
    block = (corr.get("periods") or [corr.get("full")])[-1]
    c = (block or {}).get("matrix", {}).get("SP500", {}).get("TBOND10Y")
    if c is not None:
        items.append(stat(L("股票与国债相关", "Stock–Treasury correlation"), num(c, 2, True),
                          L(f"{block['first_year']}–{block['last_year']}，年度回报", f"{block['first_year']}–{block['last_year']}, annual returns")))
    return _stats(items)


def _asset_method(result: dict[str, Any]) -> list[Html]:
    p = result["methods"].get("parameters", {})
    periods = L("、", ", ").join(f"{a}–{b}" for a, b in p.get("periods", []))
    return [
        f"<li>{te(result['methods']['description'])}</li>",
        L(f"<li>实际回报从 {p.get('real_start_year')} 年起，按 CPI 12 月对 12 月的年通胀换算。</li>",
          f"<li>Real returns from {p.get('real_start_year')}, deflated by December-to-December CPI inflation.</li>"),
        (L(f"<li>相关系数的时期事先固定为 {periods}，不按结果挑选；边界前后移动 {p.get('period_shift_years')} 年作为敏感性。</li>",
           f"<li>Correlation periods are fixed in advance at {periods}, not chosen from results; boundaries shifted by "
           f"{p.get('period_shift_years')} years as a sensitivity check.</li>") if periods else
         L(f"<li>最近 {p.get('last_n_years')} 个完整年度；数据为年度，不截断年份。</li>",
           f"<li>The last {p.get('last_n_years')} complete years; data are annual, so no year is split.</li>")),
        L("<li>口径：债券回报由收益率推算；房地产为房价变化，不含租金；黄金在 1971 年以前价格基本固定；国库券为年内平均利率。</li>",
          "<li>Definitions: bond returns are derived from yields; real estate is house-price change without rent; gold "
          "prices were essentially fixed before 1971; T-bills are the average rate over the year.</li>"),
        f"<li>{L('版本策略：', 'Version policy: ')}{e(USE_LABEL[use_key(result)])}"
        + L("；只描述历史，不是预测或配置建议。</li>", "; describes history only, not a forecast or allocation advice.</li>"),
    ]


def _asset_detail(result: dict[str, Any]) -> Html:
    r = result["results"]
    nom, real, assets = r.get("nominal", {}), r.get("real", {}), r.get("assets", [])
    if not nom:
        return ""
    head = L("<th>资产</th><th>几何平均</th><th>算术平均</th><th>波动率</th><th>最差年份</th><th>最大回撤</th><th>实际几何平均</th>",
             "<th>Asset</th><th>Geometric</th><th>Arithmetic</th><th>Volatility</th><th>Worst year</th><th>Max drawdown</th>"
             "<th>Real geometric</th>")
    body = "".join(
        f"<tr><td>{e(_an(a))}</td><td>{_pc(nom[a]['geometric'])}</td><td>{_pc(nom[a]['arithmetic'])}</td>"
        f"<td>{_pc(nom[a]['volatility'])}</td><td>{_pc(nom[a]['worst'])} ({nom[a]['worst_year']})</td>"
        f"<td>{_pc(nom[a]['max_drawdown'])}</td><td>{_pc((real.get(a) or {}).get('geometric'))}</td></tr>" for a in assets)
    first = next(iter(real.values()), None)
    out = (L(f"<p>{r['first_year']}–{r['last_year']}（{result['coverage']['years']} 个完整年度）；实际回报 "
             f"{first['first_year'] if first else '—'}–{first['last_year'] if first else '—'}。</p>",
             f"<p>{r['first_year']}–{r['last_year']} ({result['coverage']['years']} complete years); real returns "
             f"{first['first_year'] if first else '—'}–{first['last_year'] if first else '—'}.</p>")
           + f'<div class="scroll"><table class="compact"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    corr = r.get("correlations", {})
    blocks = [b for b in [corr.get("full"), *corr.get("periods", [])] if b and "SP500" in b["matrix"]]
    if blocks:
        ch = L("<th>期间</th><th>股票与 10 年期国债</th><th>股票与 Baa 公司债</th><th>股票与黄金</th>",
               "<th>Period</th><th>Stocks vs 10Y Treasury</th><th>Stocks vs Baa</th><th>Stocks vs gold</th>")
        rows = "".join(f"<tr><td>{b['first_year']}–{b['last_year']}</td>"
                       + "".join(f"<td>{num(b['matrix']['SP500'].get(x), 2, True)}</td>" for x in ("TBOND10Y", "BAA", "GOLD"))
                       + "</tr>" for b in blocks)
        out += (f'<p class="small">{L("年度回报的相关系数：", "Correlation of annual returns:")}</p>'
                f'<div class="scroll"><table class="compact"><thead><tr>{ch}</tr></thead><tbody>{rows}</tbody></table></div>')
    erp = r.get("equity_risk_premium", {})
    if erp:
        out += ('<p class="small muted">' + L("股票的历史超额回报（几何平均之差）：", "Historical equity excess return (difference of geometric means): ")
                + e(L("；", "; ").join(f"{L('相对' + (' ' if _an(k)[0].isdigit() else ''), 'vs ')}{_an(k)} {num(v * 100, 1)} pp"
                                      for k, v in erp.items())) + "</p>")
    return out


def _asset_evidence(result: dict[str, Any]) -> list[tuple[str, Html]]:
    v = result["validation"]
    rows = []
    for key, label, fmt in (
        ("cross_check_equity", ("股票跨来源核对", "Equity cross-source check"),
         lambda x: L(f"与 {e(x['against'])} 的 {x['years']} 年年度回报相关系数 {num(x['correlation'], 3)}（阈值 {x['threshold']}）；指数不同，只核对高度一致",
                     f"{x['years']} annual returns vs {e(x['against'])}: correlation {num(x['correlation'], 3)} (threshold {x['threshold']}); different indexes, consistency only")),
        ("cross_check_tbill", ("国库券跨来源核对", "T-bill cross-source check"),
         lambda x: L(f"与 {e(x['against'])} 年均值逐年比较 {x['years']} 年，最大差 {num(x['max_abs_diff_pp'], 2)} 个百分点（容差 {x['tolerance_pp']}）",
                     f"{x['years']} years vs {e(x['against'])} annual means, max diff {num(x['max_abs_diff_pp'], 2)} pp (tolerance {x['tolerance_pp']})")),
        ("cross_check_real", ("实际回报方向核对", "Real-return direction check"),
         lambda x: L(f"与 {e(x['against'])} 的实际总收益在 {x['years']} 年中方向一致 {num(x['same_direction_share'] * 100, 0)}%（阈值 {num(x['threshold'] * 100, 0)}%）",
                     f"Same direction as {e(x['against'])} real total return in {num(x['same_direction_share'] * 100, 0)}% of {x['years']} years (threshold {num(x['threshold'] * 100, 0)}%)")),
        ("monthly_drawdown", ("月度回撤核对", "Monthly drawdown check"),
         lambda x: L(f"月度 {_pc(x['monthly'])}，年度 {_pc(x['annual'])}；月度应不浅于年度",
                     f"monthly {_pc(x['monthly'])}, annual {_pc(x['annual'])}; monthly should be at least as deep")),
    ):
        x = v.get(key)
        if x:
            rows.append((L(*label), f"{chip(x['status'], CHECK_LABEL.get(x['status'], ''))} {fmt(x)}"))
    rows.append((L("与原表汇总", "Against the source's summary rows"),
                 L("由数据重算的算术平均与 Damodaran 表中汇总一致（接入核验，2026-10-23）；原始文件为 .xls，原始快照抽查不适用",
                   "Arithmetic means recomputed from the data match Damodaran's summary rows (access verification, "
                   "2026-10-23); the raw file is .xls, so the raw snapshot spot check does not apply")))
    return rows


def _asset_summary(result: dict[str, Any]) -> list[str]:
    v = result["validation"]
    checks = [k for k in ("cross_check_equity", "cross_check_tbill", "cross_check_real", "monthly_drawdown") if k in v]
    ok = sum(v[k]["status"] == "pass" for k in checks)
    return [L(f"{result['coverage']['years']} 个完整年度", f"{result['coverage']['years']} complete years"),
            L(f"跨来源与回撤核对 {ok}/{len(checks)} 通过", f"cross-source and drawdown checks {ok}/{len(checks)} passed")]


ASSETS = Renderer(
    key_stats=_asset_stats,
    method_items=_asset_method,
    coverage_title_t=("各资产统计与相关系数", "Asset statistics and correlations"),
    coverage_section=_asset_detail,
    evidence_rows=_asset_evidence,
    evidence_summary=_asset_summary,
    history_columns_t=((("期间", "Period"), lambda r: f"{r['results'].get('first_year')}–{r['results'].get('last_year')}"),
                       (("标普 500 年化", "S&P 500 annualized"),
                        lambda r: _pc(((r["results"].get("nominal") or {}).get("SP500") or {}).get("geometric")))),
    chart_data=lambda r: None,
    figures_t=(("risk_return.png", ("各资产的年化回报与波动率", "Annualized return and volatility by asset")),
               ("wealth.png", ("各资产 1 美元的累计财富", "Cumulative wealth of $1 by asset")),
               ("correlations.png", ("年度回报的相关系数", "Correlation of annual returns")),
               ("rolling.png", ("标普 500 的滚动年化回报", "S&P 500 rolling annualized return"))),
    use_note_t=("只描述历史，不是预测，也不是配置建议", "Describes history only; not a forecast or allocation advice"),
    state_description_t=("实际回报最高的资产、最近时期股债相关的正负",
                         "the asset with the highest real return and the sign of the recent stock–bond correlation"),
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

from .industry import make_renderer  # noqa: E402
from .company import make_renderer as company_renderer

RENDERERS: dict[str, Renderer] = {"rates_curve": CURVE, "par_bond_scenarios": BOND,
                                  "curve_attribution": ATTRIBUTION, "asset_history": ASSETS,
                                  "industry": make_renderer(Renderer), "company": company_renderer(Renderer)}


def get_renderer(branch: str) -> Renderer:
    return RENDERERS.get(branch, UNSUPPORTED)
