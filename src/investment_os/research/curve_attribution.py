"""研究分支：国债曲线变化的会计分解（解释与归因类成果，设计见 docs/study-curve-attribution.md）。

只用恒等式拆分，每一部分都由数据直接给出，不估计参数、不重复归因、不作因果主张：

    Δ10Y 名义 = Δ10Y 实际（TIPS） + Δ10Y 盈亏平衡通胀 （+ 取整残差）
    Δ2Y 名义  = Δ联邦基金有效利率 + Δ(2Y − 联邦基金利率)
    Δ(10Y − 2Y) 由以上四项（及残差）组成

期间取所有输入都有观测值的共同日期，不插值、不前值填充。各部分占比只在名义变化不小于阈值时给出，
并报告期初、期末各前后移动若干个共同日期时占比的范围；范围超过阈值时，结论只写方向。
CPI 同比与美联储总资产只作背景描述，不参与分解。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..analytics.rates import curve_frame
from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from ..tenor import parse_tenor
from ..validation.crosscheck import compare_series
from .base import ResearchResult, StudyInput, input_record, register_branch

# 分解的组成部分：(结果键, 中文名)。短端两项在斜率中取负号
LONG_PARTS = (("real", "实际收益率"), ("breakeven", "盈亏平衡通胀"))
SHORT_PARTS = (("policy", "联邦基金有效利率"), ("spread", "2 年期与联邦基金利率之差"))


def _series(inp: StudyInput, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    f = ok_rows(inp.frame)
    f = f[(f["observation_at"] >= start) & (f["observation_at"] <= end)]
    return f.set_index("observation_at")["value"].sort_index()


def _tenor_map(inp: StudyInput) -> dict[str, str]:
    return {sid: parse_tenor(meta["tenor"]).code for sid, meta in inp.version.series.items() if "tenor" in meta}


def _leg(a: float, b: float) -> dict[str, float]:
    return {"start": a, "end": b, "change_bp": (b - a) * 100}


def _decompose(frame: pd.DataFrame, i: int, j: int) -> dict[str, float]:
    """以第 i 个共同日期为期初、倒数第 j+1 个为期末的各项变化（bp）。"""
    a, b = frame.iloc[i], frame.iloc[-1 - j]
    d = (b - a) * 100
    return {"long": d["long"], "real": d["real"], "breakeven": d["breakeven"],
            "residual": d["long"] - d["real"] - d["breakeven"],
            "short": d["short"], "policy": d["policy"], "spread": d["short"] - d["policy"]}


def _shares(d: dict[str, float], min_bp: float) -> dict[str, float | None]:
    """各部分占对应名义变化的比例（%）；名义变化小于阈值时不给比例。"""
    long_ok, short_ok = abs(d["long"]) >= min_bp, abs(d["short"]) >= min_bp
    return {"real": d["real"] / d["long"] * 100 if long_ok else None,
            "breakeven": d["breakeven"] / d["long"] * 100 if long_ok else None,
            "policy": d["policy"] / d["short"] * 100 if short_ok else None,
            "spread": d["spread"] / d["short"] * 100 if short_ok else None}


def _sensitivity(frame: pd.DataFrame, days: int, min_bp: float, max_range_pp: float) -> dict[str, Any]:
    """期初、期末各前后移动 0–days 个共同日期时，各部分占比的范围。范围不超过 max_range_pp 时视为稳定。"""
    k = min(days, (len(frame) - 2) // 2)
    grid = [(i, j, _shares(_decompose(frame, i, j), min_bp)) for i in range(k + 1) for j in range(k + 1)]
    out: dict[str, Any] = {"shift_days": k, "endpoints": len(grid)}
    for part in ("real", "breakeven", "policy", "spread"):
        values = [s[part] for _, _, s in grid]
        if any(v is None for v in values):
            out[part] = {"min": None, "max": None, "range_pp": None, "stable": False,
                         "reason": f"部分端点组合下名义变化小于 {min_bp:g} bp，不给比例"}
            continue
        lo, hi = min(values), max(values)
        out[part] = {"min": lo, "max": hi, "range_pp": hi - lo, "stable": hi - lo <= max_range_pp}
    return out


def _background(inputs: dict[str, StudyInput], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    """CPI 同比与美联储总资产在期初、期末的值（只描述，不参与分解）；取各日期之前最近一次观测。"""
    out: dict[str, Any] = {}
    if "cpi" in inputs:
        cpi = ok_rows(inputs["cpi"].frame).set_index("observation_at")["value"].sort_index()
        yoy = (cpi / cpi.shift(12) - 1) * 100
        yoy = yoy[cpi.index.to_series().diff(12).dt.days.between(360, 370)]  # 只在恰好间隔 12 个月时计算
        pick = {k: yoy[yoy.index <= d].dropna() for k, d in (("start", start), ("end", end))}
        if all(len(v) for v in pick.values()):
            out["cpi_yoy"] = {k: {"month": v.index[-1].strftime("%Y-%m"), "value_pct": float(v.iloc[-1])}
                              for k, v in pick.items()}
    if "fed_assets" in inputs:
        w = ok_rows(inputs["fed_assets"].frame).set_index("observation_at")["value"].sort_index()
        pick = {k: w[w.index <= d] for k, d in (("start", start), ("end", end))}
        if all(len(v) for v in pick.values()):
            a, b = float(pick["start"].iloc[-1]), float(pick["end"].iloc[-1])
            out["fed_assets"] = {"start": {"date": pick["start"].index[-1].date().isoformat(), "value_musd": a},
                                 "end": {"date": pick["end"].index[-1].date().isoformat(), "value_musd": b},
                                 "change_pct": (b / a - 1) * 100}
    return out


@register_branch("curve_attribution", result_types=(ResultType.EXPLANATORY,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    if study.result_type is not ResultType.EXPLANATORY:
        raise ValueError("curve_attribution 分支只产出解释与归因成果")
    m = study.method
    long_t, short_t = parse_tenor(m.get("long_tenor", "10Y")).code, parse_tenor(m.get("short_tenor", "2Y")).code
    min_bp = float(m.get("share_min_bp", 10))
    shift = int(m.get("sensitivity_days", 5))
    max_range = float(m.get("sensitivity_max_range_pp", 15))
    tol = float(m.get("identity_tolerance_bp", 0.5))
    start, end = pd.Timestamp(study.scope["start"]), pd.Timestamp(study.scope["end"])

    curve_in = inputs["curve"]
    usable = ok_rows(curve_in.frame[(curve_in.frame["observation_at"] >= start)
                                    & (curve_in.frame["observation_at"] <= end)])
    curve = curve_frame(usable, _tenor_map(curve_in))
    missing = [t for t in (long_t, short_t) if t not in curve]
    if missing:
        raise ValueError(f"研究窗口内曲线缺少期限 {', '.join(missing)}")
    parts = {"long": curve[long_t], "short": curve[short_t], "real": _series(inputs["real"], start, end),
             "breakeven": _series(inputs["breakeven"], start, end), "policy": _series(inputs["policy"], start, end)}
    counts = {k: int(v.notna().sum()) for k, v in parts.items()}
    frame = pd.concat(parts, axis=1, sort=True).dropna()  # 共同观测日期，不插值、不前值填充
    if len(frame) < 2:
        raise ValueError(f"研究窗口 {start.date()} 至 {end.date()} 内共同观测日期不足 2 天")
    first, last = frame.index[0], frame.index[-1]

    d = _decompose(frame, 0, 0)
    shares = _shares(d, min_bp)
    sens = _sensitivity(frame, shift, min_bp, max_range)

    # 长端恒等式逐日核对：名义 − 实际 − 盈亏平衡 应只有取整误差
    level_resid = (frame["long"] - frame["real"] - frame["breakeven"]) * 100
    bad = level_resid[level_resid.abs() > tol]
    identity = {"status": "pass" if bad.empty and abs(d["residual"]) <= tol else "fail",
                "checked": int(len(frame)), "tolerance_bp": tol,
                "max_abs_level_residual_bp": float(level_resid.abs().max()),
                "change_residual_bp": d["residual"],
                "failures": [{"date": t.date().isoformat(), "residual_bp": float(v)} for t, v in bad.head(20).items()]}
    unsupported: list[dict[str, str]] = []
    if identity["status"] == "fail":
        unsupported.append({"item": "长端分解（实际收益率与盈亏平衡通胀的贡献）",
                            "reason": f"恒等式残差超过 {tol:g} bp：名义收益率与 TIPS、盈亏平衡通胀的口径不一致"})

    validation: dict[str, Any] = {"identity_check": identity}
    if "cross_check" in inputs:
        other = _series(inputs["cross_check"], start, end)
        validation["cross_check"] = {
            "against": inputs["cross_check"].dataset_id, "tenor": long_t, "independent": False,
            "note": "两者同源（Treasury/H.15），一致只说明接入与解析正确，不构成独立验证",
            **compare_series(curve[long_t], other, tolerance=0.005)}

    leg = lambda k: _leg(float(frame[k].iloc[0]), float(frame[k].iloc[-1]))  # noqa: E731
    spread_series = frame["short"] - frame["policy"]
    results = {
        "start_date": first.date().isoformat(), "end_date": last.date().isoformat(),
        "long_end": {"tenor": long_t, "nominal": leg("long"), "real": leg("real"), "breakeven": leg("breakeven"),
                     "residual_bp": d["residual"], "shares_pct": {"real": shares["real"],
                                                                 "breakeven": shares["breakeven"]}},
        "short_end": {"tenor": short_t, "nominal": leg("short"), "policy": leg("policy"),
                      "spread": _leg(float(spread_series.iloc[0]), float(spread_series.iloc[-1])),
                      "shares_pct": {"policy": shares["policy"], "spread": shares["spread"]}},
        "slope": {"label": f"{long_t} − {short_t}", "start": float(frame["long"].iloc[0] - frame["short"].iloc[0]),
                  "end": float(frame["long"].iloc[-1] - frame["short"].iloc[-1]), "change_bp": d["long"] - d["short"],
                  # 斜率变化 = 实际 + 盈亏平衡 + 残差 − 政策利率 − 利差
                  "contributions_bp": {"real": d["real"], "breakeven": d["breakeven"], "residual": d["residual"],
                                       "policy": -d["policy"], "spread": -d["spread"]}},
        "sensitivity": sens,
        "background": _background(inputs, first, last),
        "thresholds": {"share_min_bp": min_bp, "sensitivity_days": shift, "sensitivity_max_range_pp": max_range,
                       "identity_tolerance_bp": tol},
    }
    path = ((frame - frame.iloc[0]) * 100).assign(spread=lambda x: x["short"] - x["policy"])
    tables = {
        "path_bp": [{"date": t.date().isoformat(), **{k: float(v) for k, v in row.items()}}
                    for t, row in path.iterrows()],
        "sensitivity": [{"start_shift": i, "end_shift": j, **{f"{k}_share_pct": v for k, v in
                                                              _shares(_decompose(frame, i, j), min_bp).items()}}
                        for i in range(sens["shift_days"] + 1) for j in range(sens["shift_days"] + 1)],
    }
    coverage = {"requested_start": start.date().isoformat(), "requested_end": end.date().isoformat(),
                "start_date": results["start_date"], "end_date": results["end_date"],
                "common_days": int(len(frame)), "observations_by_part": counts,
                "dropped_days": int(max(counts.values()) - len(frame))}
    limitations = list(study.limitations)
    if not any(sens[p]["stable"] for p in ("real", "breakeven")):
        limitations.append("长端各部分的占比随端点选择变化较大或名义变化过小，结论只描述方向")

    return ResearchResult(
        study_id=study.study_id,
        title=study.title,
        question=study.question,
        result_type=study.result_type,
        branch=study.branch,
        scope=study.scope,
        data_cutoff=results["end_date"],
        methods={
            "description": f"会计恒等式分解：Δ{long_t} = Δ实际收益率 + Δ盈亏平衡通胀；Δ{short_t} = Δ联邦基金有效利率 + "
                           f"Δ({short_t} − 联邦基金利率)；斜率变化由以上四项组成。只用所有输入都有观测值的共同日期，"
                           "不插值、不前值填充；不估计参数，不作因果推断。",
            "benchmark": "期初（窗口内第一个共同观测日）",
            "parameters": m,
            "availability_rule": curve_in.version.quality.get("availability_rule"),
        },
        inputs=[input_record(i) for i in inputs.values()],
        results=results,
        coverage=coverage,
        unsupported=unsupported,
        limitations=limitations,
        validation=validation,
        tables=tables,
    )
