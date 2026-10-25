"""关键发现：从结构化结果按固定规则生成的句子（不是自由文本，也不使用 AI）。

每条发现都列出所依据的指标路径与数值，读者可以逐条核对。描述性研究只用
「上升、下降、变陡、倒挂 N 天」这类描述，不使用「预示、看涨」等判断。
阈值写在本模块常量中，并随发现一起展示。

另外从同一研究的历次运行中提取「状态」（如利差期末是否倒挂、曲线变陡或变平），
状态改变即记为一次发现变化。

解释在运行时固定：`interpret()` 的输出（发现、状态、规则版本、规则指纹与阈值）写入运行结果，
纳入结果校验值与 verify。规则指纹由规则代码计算，规则改动后自动变化。
"""

from __future__ import annotations

import hashlib
import inspect
from typing import Any

from ..analytics.rates import curvature_label, spread_label

# 小于该幅度（bp）的变化视为「基本持平」，避免把噪声写成方向性描述
FLAT_BP = 5.0


def _direction(change_bp: float, up: str = "上升", down: str = "下降") -> str:
    if abs(change_bp) < FLAT_BP:
        return "基本持平"
    return up if change_bp > 0 else down


def _bp(v: float) -> str:
    return f"{v:+.0f} bp".replace("-", "−")


def _n(v: float) -> str:
    return f"{v:.0f}".replace("-", "−")


def _finding(fid: str, text: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"id": fid, "text": text, "evidence": evidence}


def rates_curve_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    res, cov = result.get("results", {}), result.get("coverage", {})
    levels, spreads, curvature = res.get("levels", {}), res.get("spreads", {}), res.get("curvature", {})
    out: list[dict[str, Any]] = []
    state_ = completeness(cov)

    ten = levels.get("10Y")
    if ten and ten.get("observations"):
        out.append(_finding(
            "level_10y",
            f"10 年期收益率由 {ten['start']:.2f}% {_direction(ten['change_bp'], '升至', '降至')} "
            f"{ten['end']:.2f}%（{_bp(ten['change_bp'])}，{ten['start_date']} 至 {ten['end_date']}）。"
            if abs(ten["change_bp"]) >= FLAT_BP else
            f"10 年期收益率基本持平：{ten['start']:.2f}% 至 {ten['end']:.2f}%（{_bp(ten['change_bp'])}）。",
            {"results.levels.10Y.start": ten["start"], "results.levels.10Y.end": ten["end"],
             "results.levels.10Y.change_bp": ten["change_bp"]}))

    moves = {t: v["change_bp"] for t, v in levels.items() if v.get("observations")}
    if len(moves) >= 3:
        up = sorted(t for t, c in moves.items() if c >= FLAT_BP)
        down = sorted(t for t, c in moves.items() if c <= -FLAT_BP)
        tenors = list(moves)
        short, long = tenors[0], tenors[-1]
        if len(up) == len(moves):
            shape = "所有关键期限收益率均上升"
        elif len(down) == len(moves):
            shape = "所有关键期限收益率均下降"
        else:
            shape = f"关键期限涨跌不一：{len(up)} 个上升、{len(down)} 个下降、{len(moves) - len(up) - len(down)} 个基本持平"
        out.append(_finding(
            "curve_shift",
            f"{shape}；短端 {short} {_bp(moves[short])}，长端 {long} {_bp(moves[long])}。",
            {f"results.levels.{t}.change_bp": c for t, c in moves.items()}))

    for key, sp in spreads.items():
        if not sp.get("observations"):
            continue
        name = spread_label(key)
        start, end, chg = sp["start"], sp["end"], sp["change_bp"]
        shape = _direction(chg, "变陡", "变平")
        sign_change = ""
        if start < 0 <= end:
            sign_change = "，由倒挂转为正斜率"
        elif start >= 0 > end:
            sign_change = "，由正斜率转为倒挂"
        text = f"{name} 利差由 {_n(start)} bp 变为 {_n(end)} bp（{_bp(chg)}，该段曲线{shape}{sign_change}）"
        evidence = {f"results.spreads.{key}.start": start, f"results.spreads.{key}.end": end,
                    f"results.spreads.{key}.change_bp": chg}
        inv = sp.get("inversion")
        whole_period = sp.get("sample", "complete" if state_ == "complete" else None) == "complete"
        if inv and (whole_period or sp.get("sample") == "observed"):
            if whole_period:
                # 截至已覆盖日期完整：窗口里还有下载时未到可用时点的日期，只描述到最后一个有数据的日期
                span = f"截至 {cov['last']} " if state_ == "complete_to_date" else "期间"
                text += (f"；{span}倒挂 {inv['inverted_days']} 天，占有效观测 {inv['inverted_share']:.0%}"
                         if inv["inverted_days"] else f"；{span}未出现倒挂")
            else:
                # 有缺口：只能描述已观测日期，不能推及整个期间
                gap = f"缺 {sp['missing_days']} 天，" if sp.get("missing_days") else ""
                text += (f"；已观测的 {inv['observations']} 个交易日中倒挂 {inv['inverted_days']} 天"
                         if inv["inverted_days"] else f"；已观测的 {inv['observations']} 个交易日中未出现倒挂")
                text += f"（{gap}不能推及整个期间）"
            if inv.get("zero_days"):
                text += f"，另有 {inv['zero_days']} 天恰为 0（不计入倒挂）"
            evidence[f"results.spreads.{key}.inversion.inverted_days"] = inv["inverted_days"]
            evidence[f"results.spreads.{key}.sample"] = sp.get("sample", "complete")
        out.append(_finding(f"spread_{key}", text + "。", evidence))

    for key, cv in curvature.items():
        if not cv.get("observations"):
            continue
        out.append(_finding(
            f"curvature_{key}",
            f"曲率（{curvature_label(key)}）由 {_n(cv['start'])} bp 变为 {_n(cv['end'])} bp"
            f"（{_bp(cv['change_bp'])}，中段相对两端{_direction(cv['change_bp'], '抬升', '下沉')}）。",
            {f"results.curvature.{key}.start": cv["start"], f"results.curvature.{key}.end": cv["end"]}))

    evidence = {"coverage.completeness": state_}
    if state_ == "insufficient":
        out.append(_finding(
            "coverage_limit",
            f"研究期间覆盖不足（{cov.get('incomplete_reason', '原因见覆盖说明')}），"
            "以上只比较首尾有效观测；均值、极值与倒挂天数不输出。", evidence))
    elif state_ == "no_calendar":
        out.append(_finding("coverage_limit", "数据集未登记预期观测日历，无法判断覆盖是否完整；期间统计不输出。",
                            evidence))
    elif state_ == "gaps":
        out.append(_finding(
            "coverage_gaps",
            f"应已发布的 {cov['due_days']} 个观测日中缺少 {cov['missing_days']} 个；"
            "倒挂天数等期间统计只描述已观测日期，不能推及整个期间。", evidence))
    elif state_ == "unverified_calendar":
        out.append(_finding(
            "coverage_unverified",
            f"预期发布日历未在 {'、'.join(cov.get('calendar_unverified', []))} 核验，无法证明这些日期没有缺失；"
            "期间统计按已观测日期计算。", evidence))
    elif state_ == "calendar_conflict":
        out.append(_finding(
            "coverage_conflict", "实际观测与预期日历冲突；异常日期已隔离，需核对来源与日历。"
            "期间统计仅描述符合日历的已观测样本，不能称为完整期间。", evidence))
    elif state_ == "complete_to_date":
        out.append(_finding(
            "coverage_to_date",
            f"截至 {cov['last']}，已到保守可用时点的 {cov['due_days']} 个观测日均有数据；"
            f"另有 {cov.get('pending_days', 0)} 个日期未取得（数据下载时尚未到保守可用时点，不代表已确认尚未发布），不计入。",
            evidence))
    return out


COVERAGE_LABEL = {
    "complete": "完整",
    "complete_to_date": "截至已覆盖日期完整",
    "gaps": "有缺失",
    "unverified_calendar": "日历未核验",
    "calendar_conflict": "日历冲突",
    "insufficient": "覆盖不足",
    "no_calendar": "无预期日历",
}


def completeness(cov: dict[str, Any]) -> str:
    """覆盖结论；旧结果没有 completeness 字段时按旧的 period_complete 推断。"""
    if cov.get("completeness"):
        return cov["completeness"]
    return "complete" if cov.get("period_complete") else "insufficient"


def coverage_summary(cov: dict[str, Any]) -> str:
    """一句话的覆盖说明，供页面与报告使用。"""
    state_ = completeness(cov)
    due = cov.get("due_days", cov.get("expected_days"))
    observed = (due - cov.get("missing_days", 0)) if due is not None else cov.get("curve_days")
    head = f"{observed}/{due} 个应已发布的观测日有数据" if due is not None else f"{observed} 个观测日"
    tail = {
        "complete": "，期间完整",
        "complete_to_date": (f"，截至 {cov.get('last')} 完整；另 {cov.get('pending_days', 0)} 天未取得"
                             "（下载时尚未到保守可用时点）"),
        "gaps": f"，缺 {cov.get('missing_days', 0)} 天；期间统计为已观测样本",
        "unverified_calendar": "；相关日期超出日历核验范围，无法证明完整",
        "calendar_conflict": "；异常日期已隔离，日历冲突待核对，不能证明期间完整",
        "insufficient": "，覆盖不足；期间统计不输出",
        "no_calendar": "；未登记预期日历，无法判断完整性",
    }[state_]
    return head + tail


def _pct(v: float, digits: int = 2) -> str:
    return f"{v:+.{digits}f}%".replace("-", "−")


def _pp(v: float, digits: int = 2) -> str:
    return f"{v:+.{digits}f}".replace("-", "−")


# 情景研究：近似误差的档位（百分点），用于定性状态
ERROR_BANDS_PP = (0.1, 1.0)


def par_bond_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """假设平价债券情景的发现。只陈述计算结果与它们之间可验证的关系，不作预测。"""
    res = result.get("results", {})
    bonds_, scen = res.get("bonds", {}), res.get("scenarios", {})
    out: list[dict[str, Any]] = []
    if not bonds_:
        return out
    base = res.get("base_date")
    focus = "10Y" if "10Y" in bonds_ else next(iter(bonds_))
    b = bonds_[focus]
    up = next((r for r in scen.get(focus, []) if r["shock_bp"] == 100), None)
    text = (f"以 {base} 的票面收益率构造的 {focus} 假设平价债券（票息 {b['coupon_pct']:.2f}%）"
            f"修正久期 {b['modified_duration']:.2f} 年、凸性 {b['convexity']:.1f}")
    evidence = {f"results.bonds.{focus}.modified_duration": b["modified_duration"],
                f"results.bonds.{focus}.convexity": b["convexity"]}
    if up:
        text += (f"；收益率上升 100 bp 时，完整重新定价的价格变化为 {_pct(up['full_pct'])}，"
                 f"只用久期估计为 {_pct(up['duration_pct'])}（误差 {_pp(up['duration_error_pp'])} 个百分点），"
                 f"加入凸性后误差为 {_pp(up['duration_convexity_error_pp'], 3)} 个百分点")
        evidence[f"results.scenarios.{focus}[+100].full_pct"] = up["full_pct"]
        evidence[f"results.scenarios.{focus}[+100].duration_convexity_error_pp"] = up["duration_convexity_error_pp"]
    out.append(_finding("focus_bond", text + "。", evidence))

    durations = {t: v["modified_duration"] for t, v in bonds_.items()}
    out.append(_finding(
        "durations",
        "各期限修正久期：" + "，".join(f"{t} {d:.2f} 年" for t, d in durations.items())
        + (("；期限越长，久期越大" if list(durations.values()) == sorted(durations.values()) else "") + "。"),
        {f"results.bonds.{t}.modified_duration": d for t, d in durations.items()}))

    all_rows = [r for rows in scen.values() for r in rows]
    if all_rows and all(r["duration_error_pp"] < 0 for r in all_rows):
        out.append(_finding(
            "duration_understates",
            "只用久期时，所有期限与冲击下的估计都低于完整重新定价的价格（收益率下降时少算涨幅、上升时多算跌幅），"
            "与凸性为正一致。",
            {"results.scenarios[*].duration_error_pp": max(r["duration_error_pp"] for r in all_rows)}))

    worst = {t: max(abs(r["duration_convexity_error_pp"]) for r in rows) for t, rows in scen.items() if rows}
    if worst:
        biggest = max(abs(r["shock_bp"]) for rows in scen.values() for r in rows)
        monotone = list(worst.values()) == sorted(worst.values())
        out.append(_finding(
            "approximation_error",
            f"在最大 ±{biggest:.0f} bp 的冲击下，久期 + 凸性近似的最大绝对误差："
            + "，".join(f"{t} {w:.3f}" for t, w in worst.items()) + " 个百分点"
            + ("；期限越长，误差越大" if monotone else "") + "。",
            {f"results.worst_duration_convexity_error.{t}": w for t, w in worst.items()}))
    return out


def par_bond_state(result: dict[str, Any]) -> dict[str, str]:
    scen = result.get("results", {}).get("scenarios", {})
    rows = [r for rs in scen.values() for r in rs]
    if not rows:
        return {}
    worst = max(abs(r["duration_convexity_error_pp"]) for r in rows)
    lo, hi = ERROR_BANDS_PP
    band = f"< {lo} 个百分点" if worst < lo else (f"{lo}–{hi} 个百分点" if worst < hi else f"≥ {hi} 个百分点")
    return {"久期 + 凸性近似的最大误差": band,
            "只用久期的误差方向": "全部低估价格" if all(r["duration_error_pp"] < 0 for r in rows) else "方向不一致"}


ATTRIBUTION_NAMES = {"real": "实际收益率", "breakeven": "盈亏平衡通胀", "policy": "联邦基金有效利率",
                     "spread": "2 年期与联邦基金利率之差"}


def _share_text(part: str, res: dict[str, Any], leg: str) -> str:
    """占比说明：名义变化小于阈值、或随端点变化超过阈值时，只描述方向（docs/study-curve-attribution.md §6）。"""
    share = res[leg]["shares_pct"].get(part)
    sens, th = res["sensitivity"].get(part, {}), res["thresholds"]
    if share is None:
        return f"名义变化小于 {th['share_min_bp']:g} bp，不给占比"
    if not sens.get("stable"):
        return f"占比随端点变化超过 {th['sensitivity_max_range_pp']:g} 个百分点，只描述方向"
    return (f"{ATTRIBUTION_NAMES[part]}约占 {share:.0f}%（期初、期末各前后移动 {res['sensitivity']['shift_days']} "
            f"个共同日期时为 {sens['min']:.0f}%–{sens['max']:.0f}%）")


def curve_attribution_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """曲线变化的会计分解。只陈述恒等式拆出的各部分，不作因果或预测判断。"""
    res = result.get("results", {})
    if not res.get("long_end"):
        return []
    out: list[dict[str, Any]] = []
    span = f"{res['start_date']} 至 {res['end_date']}"
    lg, sh, sl = res["long_end"], res["short_end"], res["slope"]
    d10, real, be = lg["nominal"]["change_bp"], lg["real"]["change_bp"], lg["breakeven"]["change_bp"]
    identity_ok = result.get("validation", {}).get("identity_check", {}).get("status") != "fail"
    if identity_ok:
        move = _direction(d10) + ("" if abs(d10) < FLAT_BP else f" {_n(abs(d10))} bp")
        lead = "real" if abs(real) >= abs(be) else "breakeven"
        out.append(_finding("long_end",
                            f"{span}，{lg['tenor']} 名义收益率{move}：实际收益率 {_bp(real)}，"
                            f"盈亏平衡通胀（通胀补偿）{_bp(be)}；{_share_text(lead, res, 'long_end')}。",
                            {"results.long_end.nominal.change_bp": d10, "results.long_end.real.change_bp": real,
                             "results.long_end.breakeven.change_bp": be,
                             f"results.long_end.shares_pct.{lead}": lg["shares_pct"].get(lead)}))
    else:
        out.append(_finding("identity_failed",
                            "长端恒等式残差超过容差，名义收益率与 TIPS、盈亏平衡通胀的口径不一致，不给长端分解。",
                            {"validation.identity_check.max_abs_level_residual_bp":
                             result["validation"]["identity_check"]["max_abs_level_residual_bp"]}))

    d2, pol, spr = sh["nominal"]["change_bp"], sh["policy"]["change_bp"], sh["spread"]["change_bp"]
    text = (f"{sh['tenor']} 名义收益率{_direction(d2)}" + ("" if abs(d2) < FLAT_BP else f" {_n(abs(d2))} bp")
            + f"：联邦基金有效利率 {_bp(pol)}，{sh['tenor']} 与联邦基金利率之差 {_bp(spr)}")
    if abs(pol) >= FLAT_BP and abs(d2) < abs(pol) - FLAT_BP:
        text += (f"；政策利率变化 {_bp(pol)}，{sh['tenor']} 只变化 {_bp(d2)}，差额来自市场对未来政策路径与期限溢价的定价"
                 "（本研究不能区分两者）")
    elif abs(pol) >= FLAT_BP and abs(d2) >= FLAT_BP and (pol > 0) != (d2 > 0):
        text += f"；{sh['tenor']} 与政策利率反向变化"
    out.append(_finding("short_end", text + "。",
                        {"results.short_end.nominal.change_bp": d2, "results.short_end.policy.change_bp": pol,
                         "results.short_end.spread.change_bp": spr}))

    contrib = {k: v for k, v in sl["contributions_bp"].items() if k != "residual"}
    top = max(contrib, key=lambda k: abs(contrib[k]))
    out.append(_finding("slope",
                        f"{sl['label']} {_direction(sl['change_bp'], '变陡', '变平')}"
                        + ("" if abs(sl["change_bp"]) < FLAT_BP else f" {_n(abs(sl['change_bp']))} bp")
                        + f"；对斜率贡献最大的是{ATTRIBUTION_NAMES[top]}（{_bp(contrib[top])}，"
                        + ("短端项以负号计入" if top in ("policy", "spread") else "长端项") + "）。",
                        {"results.slope.change_bp": sl["change_bp"], f"results.slope.contributions_bp.{top}": contrib[top]}))

    bg = res.get("background", {})
    parts, evidence = [], {}
    if "cpi_yoy" in bg:
        c = bg["cpi_yoy"]
        parts.append(f"CPI 同比由 {c['start']['value_pct']:.1f}%（{c['start']['month']}）变为 "
                     f"{c['end']['value_pct']:.1f}%（{c['end']['month']}）")
        evidence["results.background.cpi_yoy.end.value_pct"] = c["end"]["value_pct"]
    if "fed_assets" in bg:
        f = bg["fed_assets"]
        parts.append(f"美联储总资产{'增加' if f['change_pct'] > 0 else '减少'} {abs(f['change_pct']):.1f}%")
        evidence["results.background.fed_assets.change_pct"] = f["change_pct"]
    if parts:
        out.append(_finding("background", "背景（只作描述，不参与分解）：" + "；".join(parts) + "。", evidence))
    return out


def curve_attribution_state(result: dict[str, Any]) -> dict[str, str]:
    res = result.get("results", {})
    if not res.get("long_end"):
        return {}
    lg, sh, sl = res["long_end"], res["short_end"], res["slope"]
    d10 = lg["nominal"]["change_bp"]
    real, be = lg["real"]["change_bp"], lg["breakeven"]["change_bp"]
    d2, pol = sh["nominal"]["change_bp"], sh["policy"]["change_bp"]
    return {
        f"{lg['tenor']} 主要来源": "基本持平" if abs(d10) < FLAT_BP else ("实际收益率" if abs(real) >= abs(be) else "盈亏平衡通胀"),
        f"{sh['tenor']} 相对政策利率": ("政策利率基本未变" if abs(pol) < FLAT_BP else
                                  "反向" if abs(d2) >= FLAT_BP and (pol > 0) != (d2 > 0) else "同向或基本持平"),
        f"{sl['label']} 期间": _direction(sl["change_bp"], "变陡", "变平"),
    }


ASSET_NAMES = {"SP500": "标普 500", "SMALLCAP": "小盘股", "TBOND10Y": "10 年期国债", "BAA": "Baa 公司债",
               "TBILL3M": "3 个月国库券", "REALESTATE": "房地产", "GOLD": "黄金"}


def _p1(v: float) -> str:
    return f"{v * 100:.1f}%".replace("-", "−")


def asset_history_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """长期回报与风险。只陈述历史统计量，措辞避免「预期」「将会」等推断。"""
    res = result.get("results", {})
    nom, real = res.get("nominal", {}), res.get("real", {})
    if "SP500" not in nom:
        return []
    out: list[dict[str, Any]] = []
    span = f"{res['first_year']}–{res['last_year']} 年"
    sp = nom["SP500"]
    text = f"{span}，标普 500 年化回报 {_p1(sp['geometric'])}（算术平均 {_p1(sp['arithmetic'])}，波动率 {_p1(sp['volatility'])}）"
    ev = {"results.nominal.SP500.geometric": sp["geometric"], "results.nominal.SP500.volatility": sp["volatility"]}
    if real.get("SP500"):
        r = real["SP500"]
        text += f"；扣除通胀（{r['first_year']}–{r['last_year']} 年）为 {_p1(r['geometric'])}"
        ev["results.real.SP500.geometric"] = r["geometric"]
    out.append(_finding("equity_long_run", text + "。", ev))

    if real:
        first = next(iter(real.values()))
        ranked = sorted(real, key=lambda a: real[a]["geometric"], reverse=True)
        out.append(_finding("real_ranking",
                            f"扣除通胀后的年化回报（{first['first_year']}–{first['last_year']} 年）："
                            + "，".join(f"{ASSET_NAMES.get(a, a)} {_p1(real[a]['geometric'])}" for a in ranked) + "。",
                            {f"results.real.{a}.geometric": real[a]["geometric"] for a in ranked}))

    me = res.get("monthly_equity") or {}
    text = (f"标普 500 按年度数据的最大回撤为 {_p1(sp['max_drawdown'])}（{sp['drawdown_peak_year']} 年末至 "
            f"{sp['drawdown_trough_year']} 年末）")
    ev = {"results.nominal.SP500.max_drawdown": sp["max_drawdown"]}
    if me:
        text += (f"；按月度数据（CRSP 全市场）为 {_p1(me['max_drawdown'])}（{me['peak']} 至 {me['trough']}），"
                 "年度数据低估了年内跌幅")
        ev["results.monthly_equity.max_drawdown"] = me["max_drawdown"]
    out.append(_finding("drawdown", text + "。", ev))

    erp = res.get("equity_risk_premium", {})
    if erp:
        # 名称以数字开头（如「3 个月国库券」）时前面加空格，与其他中英文混排一致
        parts = [f"相对{' ' if ASSET_NAMES[k][0].isdigit() else ''}{ASSET_NAMES[k]} {v * 100:.1f} 个百分点".replace("-", "−")
                 for k, v in erp.items()]
        out.append(_finding("equity_premium", "股票相对无风险资产的历史超额回报（几何平均之差）：" + "，".join(parts) + "。",
                            {f"results.equity_risk_premium.{k}": v for k, v in erp.items()}))

    corr = res.get("correlations", {})
    periods = corr.get("periods", [])
    if periods and all("TBOND10Y" in p["matrix"].get("SP500", {}) for p in periods):
        sens = {tuple(x["period"]): x for x in res.get("period_sensitivity", {}).get("stock_bond_correlation", [])}
        stable = all(x["sign_stable"] for x in sens.values()) if sens else None
        text = "股票与 10 年期国债年度回报的相关系数：" + "，".join(
            f"{p['first_year']}–{p['last_year']} 年 {p['matrix']['SP500']['TBOND10Y']:+.2f}".replace("-", "−")
            for p in periods)
        if stable is True:
            text += f"；各时期边界前后移动 {res['period_sensitivity']['shift_years']} 年时符号不变"
        elif stable is False:
            text += "；部分时期的符号随边界移动而改变"
        out.append(_finding("stock_bond_correlation", text + "。",
                            {f"results.correlations.periods[{i}].matrix.SP500.TBOND10Y": p["matrix"]["SP500"]["TBOND10Y"]
                             for i, p in enumerate(periods)}))
    elif "TBOND10Y" in corr.get("full", {}).get("matrix", {}).get("SP500", {}):
        c = corr["full"]["matrix"]["SP500"]["TBOND10Y"]
        out.append(_finding("stock_bond_correlation",
                            f"{span}股票与 10 年期国债年度回报的相关系数为 {c:+.2f}。".replace("-", "−"),
                            {"results.correlations.full.matrix.SP500.TBOND10Y": c}))

    roll = res.get("rolling") or {}
    if roll:
        out.append(_finding("rolling",
                            f"标普 500 的 {roll['window_years']} 年滚动年化回报在 {_p1(roll['min'])}（截至 {roll['min_end_year']} 年）"
                            f"到 {_p1(roll['max'])}（截至 {roll['max_end_year']} 年）之间。",
                            {"results.rolling.min": roll["min"], "results.rolling.max": roll["max"]}))
    return out


def asset_history_state(result: dict[str, Any]) -> dict[str, str]:
    res = result.get("results", {})
    real, corr = res.get("real", {}), res.get("correlations", {})
    out: dict[str, str] = {}
    if real:
        top = max(real, key=lambda a: real[a]["geometric"])
        out["实际回报最高的资产"] = ASSET_NAMES.get(top, top)
    periods = corr.get("periods") or []
    matrix = (periods[-1] if periods else corr.get("full", {})).get("matrix", {})
    c = matrix.get("SP500", {}).get("TBOND10Y")
    if c is not None:
        out["股债相关（最近时期）"] = "正" if c > 0 else "负"
    return out


_FINDERS = {"rates_curve": rates_curve_findings, "par_bond_scenarios": par_bond_findings,
            "curve_attribution": curve_attribution_findings, "asset_history": asset_history_findings}
_STATES = {"par_bond_scenarios": par_bond_state, "curve_attribution": curve_attribution_state,
           "asset_history": asset_history_state}

# 规则版本：人工维护的名称；规则改动时递增。指纹会自动反映代码改动，两者一起展示
# rates_curve v2（2026-10-23）：「尚未发布」改为「未取得（下载时尚未到保守可用时点）」
RULE_VERSIONS = {"rates_curve": "rates_curve-findings.v2", "par_bond_scenarios": "par_bond-findings.v1",
                 "curve_attribution": "curve_attribution-findings.v1", "asset_history": "asset_history-findings.v1"}


def findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """按研究分支选择规则；没有规则的分支返回空列表（页面显示「暂无规则化发现」）。"""
    finder = _FINDERS.get(result.get("branch", ""))
    return finder(result) if finder else []


def state(result: dict[str, Any]) -> dict[str, str]:
    """用于比较历次运行的定性状态。"""
    out: dict[str, str] = {}
    for key, sp in result.get("results", {}).get("spreads", {}).items():
        if sp.get("observations"):
            out[f"{spread_label(key)} 期末"] = "倒挂" if sp["end"] < 0 else "正斜率"
            out[f"{spread_label(key)} 期间"] = _direction(sp["change_bp"], "变陡", "变平")
    ten = result.get("results", {}).get("levels", {}).get("10Y")
    if ten and ten.get("observations"):
        out["10Y 期间"] = _direction(ten["change_bp"])
    out["期间覆盖"] = COVERAGE_LABEL[completeness(result.get("coverage", {}))]
    return out


def changes(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """history 为同一研究按时间从旧到新的结果；返回状态发生变化的记录。"""
    out: list[dict[str, Any]] = []
    previous: dict[str, str] | None = None
    for result in history:
        current = state(result)
        if previous is not None:
            out += [{"run_id": result.get("run_id"), "data_cutoff": result.get("data_cutoff"), **c}
                    for c in state_changes(previous, current)]
        previous = current
    return out


def state_changes(previous: dict[str, str], current: dict[str, str]) -> list[dict[str, str]]:
    return [{"item": k, "from": previous[k], "to": v}
            for k, v in current.items() if k in previous and previous[k] != v]


def rule_fingerprint(branch: str) -> str | None:
    """规则代码（发现、状态、措辞与覆盖说明）的校验值；只要规则代码变化，指纹就变化。"""
    finder = _FINDERS.get(branch)
    if finder is None:
        return None
    if branch == "par_bond_scenarios":
        parts = [inspect.getsource(f) for f in (finder, par_bond_state, _pct, _pp)] + [repr(ERROR_BANDS_PP)]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    if branch == "asset_history":
        parts = [inspect.getsource(f) for f in (finder, asset_history_state, _p1)] + [repr(sorted(ASSET_NAMES.items()))]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    if branch == "curve_attribution":
        parts = [inspect.getsource(f) for f in (finder, curve_attribution_state, _share_text, _direction, _bp, _n)]
        parts.append(repr(sorted(ATTRIBUTION_NAMES.items())))
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    parts = [inspect.getsource(f) for f in (finder, state, completeness, coverage_summary, _direction, _bp, _n)]
    parts.append(repr(sorted(COVERAGE_LABEL.items())))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def rule_params(branch: str) -> dict[str, Any]:
    if branch == "par_bond_scenarios":
        return {"error_bands_pp": list(ERROR_BANDS_PP)}
    if branch == "asset_history":
        return {}
    return {"flat_bp": FLAT_BP} if branch in _FINDERS else {}


def interpret(result: dict[str, Any]) -> dict[str, Any] | None:
    """一次运行的解释：发现、定性状态与所用规则。没有规则的分支返回 None。"""
    branch = result.get("branch", "")
    if branch not in _FINDERS:
        return None
    return {
        "rule_version": RULE_VERSIONS[branch],
        "rule_fingerprint": rule_fingerprint(branch),
        "params": rule_params(branch),
        "items": findings(result),
        "state": _STATES.get(branch, state)(result),
    }
