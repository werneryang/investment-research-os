"""关键发现：从结构化结果按固定规则生成的句子（不是自由文本，也不使用 AI）。

每条发现都列出所依据的指标路径与数值，读者可以逐条核对。描述性研究只用
「上升、下降、变陡、倒挂 N 天」这类描述，不使用「预示、看涨」等判断。
阈值写在本模块常量中，并随发现一起展示。

另外从同一研究的历次运行中提取「状态」（如利差期末是否倒挂、曲线变陡或变平），
状态改变即记为一次发现变化。
"""

from __future__ import annotations

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
    complete = cov.get("period_complete", False)

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
        if complete and inv:
            if inv["inverted_days"]:
                text += f"；期间倒挂 {inv['inverted_days']} 天，占有效观测 {inv['inverted_share']:.0%}"
            else:
                text += "；期间未出现倒挂"
            if inv.get("zero_days"):
                text += f"，另有 {inv['zero_days']} 天恰为 0（不计入倒挂）"
            evidence[f"results.spreads.{key}.inversion.inverted_days"] = inv["inverted_days"]
        out.append(_finding(f"spread_{key}", text + "。", evidence))

    for key, cv in curvature.items():
        if not cv.get("observations"):
            continue
        out.append(_finding(
            f"curvature_{key}",
            f"曲率（{curvature_label(key)}）由 {_n(cv['start'])} bp 变为 {_n(cv['end'])} bp"
            f"（{_bp(cv['change_bp'])}，中段相对两端{_direction(cv['change_bp'], '抬升', '下沉')}）。",
            {f"results.curvature.{key}.start": cv["start"], f"results.curvature.{key}.end": cv["end"]}))

    if not complete:
        out.append(_finding(
            "coverage_limit",
            f"研究期间未能证明完整覆盖（{cov.get('incomplete_reason', '原因见覆盖说明')}），"
            "以上只比较首尾有效观测；均值、极值与倒挂天数不输出。",
            {"coverage.period_complete": False}))
    return out


_FINDERS = {"rates_curve": rates_curve_findings}


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
    out["期间覆盖"] = "完整" if result.get("coverage", {}).get("period_complete") else "未能证明完整"
    return out


def changes(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """history 为同一研究按时间从旧到新的结果；返回状态发生变化的记录。"""
    out: list[dict[str, Any]] = []
    previous: dict[str, str] | None = None
    for result in history:
        current = state(result)
        if previous is not None:
            for k, v in current.items():
                if k in previous and previous[k] != v:
                    out.append({"run_id": result.get("run_id"), "data_cutoff": result.get("data_cutoff"),
                                "item": k, "from": previous[k], "to": v})
        previous = current
    return out
