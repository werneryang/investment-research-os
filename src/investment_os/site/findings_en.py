"""英文页面上的关键发现与覆盖说明。

运行记录里的发现是中文，按规则在运行时固定，不改写。英文页面用同一规则的英文措辞，从同一份结构化结果
重新生成句子，只替换记录中已有的发现（按发现 id 对应、保持记录的顺序）；英文模板没有的发现保留中文原文。
阈值与判断取自 research/findings.py，保证中英文描述的是同一个结论。
"""

from __future__ import annotations

from typing import Any

from ..analytics.rates import curvature_label, spread_label
from ..research.findings import FLAT_BP, completeness

COVERAGE_LABEL_EN = {
    "complete": "complete",
    "complete_to_date": "complete to date",
    "gaps": "has gaps",
    "unverified_calendar": "calendar not verified",
    "calendar_conflict": "calendar conflict",
    "insufficient": "insufficient coverage",
    "no_calendar": "no expected calendar",
}

# 定性状态（运行时以中文记录）的英文：键与值分别对照
STATE_EN = {
    "期末": "at period end", "期间": "over the period", "期间覆盖": "Period coverage",
    "倒挂": "inverted", "正斜率": "positive slope", "变陡": "steepened", "变平": "flattened",
    "上升": "rose", "下降": "fell", "基本持平": "roughly flat",
    "久期 + 凸性近似的最大误差": "Max duration + convexity approximation error",
    "只用久期的误差方向": "Direction of duration-only error",
    "全部低估价格": "understates price in every case", "方向不一致": "mixed direction",
    "个百分点": "pp",
    # 旧规则版本记录的覆盖标签
    "截至目前完整": "complete to date",
    **{v: COVERAGE_LABEL_EN[k] for k, v in {
        "complete": "完整", "complete_to_date": "截至已覆盖日期完整", "gaps": "有缺失",
        "calendar_conflict": "日历冲突",
        "unverified_calendar": "日历未核验", "insufficient": "覆盖不足", "no_calendar": "无预期日历"}.items()},
}


def state_text(text: str) -> str:
    """把记录中的状态键或值（如「10Y − 2Y 期末」「< 0.1 个百分点」）换成英文。"""
    out = text
    for zh, en in sorted(STATE_EN.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(zh, en)
    return out


def _direction(change_bp: float, up: str = "rose", down: str = "fell") -> str:
    if abs(change_bp) < FLAT_BP:
        return "was roughly flat"
    return up if change_bp > 0 else down


def _bp(v: float) -> str:
    return f"{v:+.0f} bp".replace("-", "−")


def _n(v: float) -> str:
    return f"{v:.0f}".replace("-", "−")


def coverage_summary_en(cov: dict[str, Any]) -> str:
    state_ = completeness(cov)
    due = cov.get("due_days", cov.get("expected_days"))
    observed = (due - cov.get("missing_days", 0)) if due is not None else cov.get("curve_days")
    head = f"{observed}/{due} due observation dates have data" if due is not None else f"{observed} observation dates"
    tail = {
        "complete": "; the period is complete",
        "complete_to_date": (f"; complete through {cov.get('last')}; {cov.get('pending_days', 0)} more date(s) "
                             "not yet retrieved (not past the conservative availability time when downloaded)"),
        "gaps": f"; {cov.get('missing_days', 0)} missing; period statistics use observed dates only",
        "unverified_calendar": "; some dates are outside the verified calendar, so completeness cannot be shown",
        "calendar_conflict": "; unexpected dates are excluded pending calendar review; completeness cannot be shown",
        "insufficient": "; coverage is insufficient, so period statistics are not reported",
        "no_calendar": "; no expected calendar is registered, so completeness cannot be judged",
    }[state_]
    return head + tail


def _curve(result: dict[str, Any]) -> dict[str, str]:
    res, cov = result.get("results", {}), result.get("coverage", {})
    levels, spreads, curvature = res.get("levels", {}), res.get("spreads", {}), res.get("curvature", {})
    out: dict[str, str] = {}
    state_ = completeness(cov)

    ten = levels.get("10Y")
    if ten and ten.get("observations"):
        if abs(ten["change_bp"]) >= FLAT_BP:
            verb = "rose" if ten["change_bp"] > 0 else "fell"
            out["level_10y"] = (f"The 10-year yield {verb} from {ten['start']:.2f}% to {ten['end']:.2f}% "
                                f"({_bp(ten['change_bp'])}, {ten['start_date']} to {ten['end_date']}).")
        else:
            out["level_10y"] = (f"The 10-year yield was roughly flat: {ten['start']:.2f}% to {ten['end']:.2f}% "
                                f"({_bp(ten['change_bp'])}).")

    moves = {t: v["change_bp"] for t, v in levels.items() if v.get("observations")}
    if len(moves) >= 3:
        up = [t for t, c in moves.items() if c >= FLAT_BP]
        down = [t for t, c in moves.items() if c <= -FLAT_BP]
        tenors = list(moves)
        short, long = tenors[0], tenors[-1]
        if len(up) == len(moves):
            shape = "All key-tenor yields rose"
        elif len(down) == len(moves):
            shape = "All key-tenor yields fell"
        else:
            shape = (f"Key tenors moved in different directions: {len(up)} up, {len(down)} down, "
                     f"{len(moves) - len(up) - len(down)} roughly flat")
        out["curve_shift"] = f"{shape}; short end {short} {_bp(moves[short])}, long end {long} {_bp(moves[long])}."

    for key, sp in spreads.items():
        if not sp.get("observations"):
            continue
        start, end, chg = sp["start"], sp["end"], sp["change_bp"]
        shape = _direction(chg, "steepened", "flattened")
        if shape == "was roughly flat":
            shape = "was roughly unchanged"
        sign = ""
        if start < 0 <= end:
            sign = ", turning from inverted to positive"
        elif start >= 0 > end:
            sign = ", turning from positive to inverted"
        text = (f"The {spread_label(key)} spread moved from {_n(start)} bp to {_n(end)} bp "
                f"({_bp(chg)}; this segment of the curve {shape}{sign})")
        inv = sp.get("inversion")
        whole = sp.get("sample", "complete" if state_ == "complete" else None) == "complete"
        if inv and (whole or sp.get("sample") == "observed"):
            if whole:
                span = f"through {cov['last']}" if state_ == "complete_to_date" else "over the period"
                text += (f"; inverted on {inv['inverted_days']} days {span}, {inv['inverted_share']:.0%} of valid "
                         "observations" if inv["inverted_days"] else f"; no inversion {span}")
            else:
                gap = f"{sp['missing_days']} missing; " if sp.get("missing_days") else ""
                text += (f"; inverted on {inv['inverted_days']} of {inv['observations']} observed trading days"
                         if inv["inverted_days"] else f"; no inversion in {inv['observations']} observed trading days")
                text += f" ({gap}this cannot be extended to the whole period)"
            if inv.get("zero_days"):
                text += f", plus {inv['zero_days']} day(s) at exactly 0 (not counted as inverted)"
        out[f"spread_{key}"] = text + "."

    for key, cv in curvature.items():
        if cv.get("observations"):
            move = _direction(cv["change_bp"], "rose", "sank")
            out[f"curvature_{key}"] = (f"Curvature ({curvature_label(key)}) moved from {_n(cv['start'])} bp to "
                                       f"{_n(cv['end'])} bp ({_bp(cv['change_bp'])}; the middle of the curve "
                                       f"{move} relative to the ends).")

    if state_ == "insufficient":
        out["coverage_limit"] = ("Coverage over the study period is insufficient; only the first and last valid "
                                 "observations are compared, and means, extremes and inversion counts are not reported.")
    elif state_ == "no_calendar":
        out["coverage_limit"] = ("No expected calendar is registered for the dataset, so completeness cannot be "
                                 "judged; period statistics are not reported.")
    elif state_ == "gaps":
        out["coverage_gaps"] = (f"{cov['missing_days']} of {cov['due_days']} due observation dates are missing; "
                                "period statistics such as inversion days describe observed dates only and cannot "
                                "be extended to the whole period.")
    elif state_ == "unverified_calendar":
        out["coverage_unverified"] = (f"The expected release calendar is not verified for "
                                      f"{', '.join(cov.get('calendar_unverified', []))}, so these dates cannot be "
                                      "shown to be complete; period statistics use observed dates.")
    elif state_ == "calendar_conflict":
        out["coverage_conflict"] = ("Observed dates conflict with the expected calendar. Unexpected dates are "
                                    "excluded pending source and calendar review; statistics describe only "
                                    "calendar-aligned observed dates, not a complete period.")
    elif state_ == "complete_to_date":
        out["coverage_to_date"] = (f"Through {cov['last']}, all {cov['due_days']} observation dates past the "
                                   f"conservative availability time have data; {cov.get('pending_days', 0)} more "
                                   "date(s) were not yet retrieved (not past that time when downloaded, which does "
                                   "not confirm they were unpublished) and are not counted.")
    return out


def _pct(v: float, digits: int = 2) -> str:
    return f"{v:+.{digits}f}%".replace("-", "−")


def _pp(v: float, digits: int = 2) -> str:
    return f"{v:+.{digits}f}".replace("-", "−")


def _bond(result: dict[str, Any]) -> dict[str, str]:
    res = result.get("results", {})
    bonds_, scen = res.get("bonds", {}), res.get("scenarios", {})
    out: dict[str, str] = {}
    if not bonds_:
        return out
    focus = "10Y" if "10Y" in bonds_ else next(iter(bonds_))
    b = bonds_[focus]
    up = next((r for r in scen.get(focus, []) if r["shock_bp"] == 100), None)
    text = (f"A hypothetical {focus} par bond built from the {res.get('base_date')} par yield (coupon "
            f"{b['coupon_pct']:.2f}%) has modified duration {b['modified_duration']:.2f} years and convexity "
            f"{b['convexity']:.1f}")
    if up:
        text += (f"; for a 100 bp rise in yield, full repricing gives a price change of {_pct(up['full_pct'])}, "
                 f"duration alone estimates {_pct(up['duration_pct'])} (error {_pp(up['duration_error_pp'])} pp), "
                 f"and adding convexity leaves an error of {_pp(up['duration_convexity_error_pp'], 3)} pp")
    out["focus_bond"] = text + "."
    durations = {t: v["modified_duration"] for t, v in bonds_.items()}
    out["durations"] = ("Modified duration by tenor: " + ", ".join(f"{t} {d:.2f} years" for t, d in durations.items())
                        + ("; longer tenors have longer duration" if list(durations.values()) == sorted(durations.values())
                           else "") + ".")
    rows = [r for rs in scen.values() for r in rs]
    if rows and all(r["duration_error_pp"] < 0 for r in rows):
        out["duration_understates"] = ("Using duration alone, every tenor and shock gives a price below full "
                                       "repricing (too small a gain when yields fall, too large a loss when they "
                                       "rise), consistent with positive convexity.")
    worst = {t: max(abs(r["duration_convexity_error_pp"]) for r in rs) for t, rs in scen.items() if rs}
    if worst:
        biggest = max(abs(r["shock_bp"]) for r in rows)
        monotone = list(worst.values()) == sorted(worst.values())
        out["approximation_error"] = (f"Under shocks of up to ±{biggest:.0f} bp, the largest absolute error of the "
                                      "duration + convexity approximation: "
                                      + ", ".join(f"{t} {w:.3f}" for t, w in worst.items()) + " pp"
                                      + ("; longer tenors have larger errors" if monotone else "") + ".")
    return out


_EN = {"rates_curve": _curve, "par_bond_scenarios": _bond}


def english_findings(result: dict[str, Any], recorded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """记录中的发现换成英文措辞；返回的每条带 translated 标记。"""
    maker = _EN.get(result.get("branch", ""))
    texts = maker(result) if maker else {}
    return [{**f, "text": texts.get(f["id"], f["text"]), "translated": f["id"] in texts} for f in recorded]

