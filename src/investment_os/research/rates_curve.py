"""研究分支：收益率曲线的水平、斜率与曲率描述（首个贯通案例）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..analytics.rates import curvature_bp, curve_frame, inversion_stats, level_summary, spread_bp
from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import StudySpec
from ..tenor import parse_tenor
from ..validation.crosscheck import compare_series
from .base import ResearchResult, StudyInput, input_record, register_branch

# 研究期间首尾允许的空档（日历天）；超过即认为期间未完整覆盖
PERIOD_EDGE_TOLERANCE_DAYS = 7


def _tenor_map(inp: StudyInput) -> dict[str, str]:
    mapping = {}
    for sid, meta in inp.version.series.items():
        if "tenor" in meta:
            mapping[sid] = parse_tenor(meta["tenor"]).code
    return mapping


def _in_period(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[(df["observation_at"] >= start) & (df["observation_at"] <= end)]


@register_branch("rates_curve")
def run(study: StudySpec, inputs: dict[str, StudyInput]) -> ResearchResult:
    if study.result_type is not ResultType.DESCRIPTIVE:
        raise ValueError("rates_curve 分支目前只支持描述性研究")
    curve_in = inputs["curve"]
    method = study.method
    start = pd.Timestamp(study.scope["start"])
    end = pd.Timestamp(study.scope["end"])
    min_cov = float(method.get("min_coverage", 0.95))

    tenor_of = _tenor_map(curve_in)
    period = _in_period(curve_in.frame, start, end)
    usable = ok_rows(period)
    curve = curve_frame(usable, tenor_of)
    curve = curve.reindex(columns=sorted(curve.columns, key=lambda c: parse_tenor(c).months))
    n_days = int(len(curve))

    unsupported: list[dict[str, str]] = []
    limitations = list(study.limitations)

    # ---- 覆盖 ----------------------------------------------------------
    tenor_cov: dict[str, Any] = {}
    supported: set[str] = set()
    for t in method["key_tenors"]:
        code = parse_tenor(t).code
        n = int(curve[code].notna().sum()) if code in curve else 0
        share = n / n_days if n_days else 0.0
        tenor_cov[code] = {"observations": n, "share": share}
        if share >= min_cov:
            supported.add(code)
        else:
            unsupported.append({"item": f"期限 {code}",
                                "reason": f"有效观测占比 {share:.1%} 低于要求 {min_cov:.0%}"})

    first = curve.index.min() if n_days else None
    last = curve.index.max() if n_days else None
    tol = pd.Timedelta(days=PERIOD_EDGE_TOLERANCE_DAYS)
    period_complete = bool(n_days) and first - start <= tol and end - last <= tol
    if not period_complete:
        covered = f"{first.date()} 至 {last.date()}" if n_days else "无"
        limitations.append(f"数据未完整覆盖研究期间 {start.date()} 至 {end.date()}（实际覆盖 {covered}），"
                           "期末数值与变化只代表已覆盖部分")
    coverage = {
        "curve_days": n_days,
        "first": first.date().isoformat() if first is not None else None,
        "last": last.date().isoformat() if last is not None else None,
        "period_complete": period_complete,
        "min_coverage": min_cov,
        "tenors": tenor_cov,
        "excluded_rows": period["quality_status"].value_counts().drop("ok", errors="ignore").to_dict(),
    }

    # ---- 水平、利差与曲率 -----------------------------------------------
    levels = {code: level_summary(curve[code], "percent") for code in sorted(
        supported, key=lambda c: parse_tenor(c).months)}

    spreads: dict[str, Any] = {}
    spread_series: dict[str, pd.Series] = {}
    for short, long in method.get("spreads", []):
        s, l = parse_tenor(short).code, parse_tenor(long).code
        name = f"{s}-{l}"
        if not {s, l} <= supported:
            unsupported.append({"item": f"利差 {name}", "reason": "所需期限覆盖不足"})
            continue
        series = spread_bp(curve, s, l)
        spread_series[name] = series
        spreads[name] = {**level_summary(series, "bp"), **{"inversion": inversion_stats(series)}}

    curvature: dict[str, Any] = {}
    if method.get("curvature"):
        s, m, l = (parse_tenor(t).code for t in method["curvature"])
        name = f"{s}/{m}/{l}"
        if {s, m, l} <= supported:
            series = curvature_bp(curve, s, m, l)
            spread_series[f"curvature {name}"] = series
            curvature[name] = level_summary(series, "bp")
        else:
            unsupported.append({"item": f"曲率 {name}", "reason": "所需期限覆盖不足"})

    # ---- 曲线快照（期初为比较基准） --------------------------------------
    snapshots: list[dict[str, Any]] = []
    if n_days:
        for label, day in (("start", first), ("end", last)):
            row = curve.loc[day].dropna()
            snapshots.append({"label": label, "date": day.date().isoformat(),
                              **{k: float(v) for k, v in row.items()}})
    snapshot_rows = []
    if len(snapshots) == 2:
        for code in curve.columns:
            a, b = snapshots[0].get(code), snapshots[1].get(code)
            snapshot_rows.append({"tenor": code, "start": a, "end": b,
                                  "change_bp": (b - a) * 100 if a is not None and b is not None else None})

    # ---- 交叉核验（可选输入） --------------------------------------------
    validation: dict[str, Any] = {}
    cross = inputs.get("cross_check")
    if cross is None:
        validation["cross_check"] = {"status": "skipped", "reason": "未提供交叉核验数据"}
    else:
        other = ok_rows(_in_period(cross.frame, start, end)).set_index("observation_at")["value"]
        validation["cross_check"] = {
            "against": cross.dataset_id,
            "tenor": "10Y",
            "independent": False,
            "note": "两者同源（Treasury/H.15），一致只说明接入与解析正确，不构成独立验证",
            **(compare_series(curve["10Y"], other, tolerance=0.005)
               if "10Y" in curve else {"status": "skipped", "reason": "曲线缺少 10Y"}),
        }

    tables = {
        "levels": [{"tenor": k, **v} for k, v in levels.items()],
        "spreads": [{"spread": k, **{kk: vv for kk, vv in v.items() if kk != "inversion"},
                     **{f"inversion_{kk}": vv for kk, vv in v["inversion"].items()}}
                    for k, v in spreads.items()],
        "curvature": [{"curvature": k, **v} for k, v in curvature.items()],
        "curve_change": snapshot_rows,
    }
    # 供图表使用的时间序列（日度，已是合格数据）
    series_table = curve.copy()
    for name, s in spread_series.items():
        series_table[name] = s
    tables["daily"] = [
        {"date": idx.date().isoformat(), **{c: (None if pd.isna(v) else float(v)) for c, v in row.items()}}
        for idx, row in series_table.iterrows()
    ]

    return ResearchResult(
        study_id=study.study_id,
        title=study.title,
        question=study.question,
        result_type=study.result_type,
        branch=study.branch,
        scope=study.scope,
        data_cutoff=coverage["last"],
        methods={
            "description": "按日对齐合格观测，计算关键期限水平、利差（长端−短端）与蝶式曲率（2×中端−短端−长端）；"
                           "不插值、不填补缺失",
            "benchmark": study.benchmark,
            "parameters": method,
            "availability_rule": curve_in.version.quality.get("availability_rule"),
        },
        inputs=[input_record(i) for i in inputs.values()],
        results={"levels": levels, "spreads": spreads, "curvature": curvature, "snapshots": snapshots},
        coverage=coverage,
        unsupported=unsupported,
        limitations=limitations,
        validation=validation,
        tables=tables,
    )
