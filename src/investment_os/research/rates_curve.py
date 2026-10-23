"""研究分支：收益率曲线的水平、斜率与曲率描述（首个贯通案例）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..analytics.rates import (
    curvature_bp,
    curve_frame,
    inversion_stats,
    level_summary,
    spread_bp,
)
from ..calendars import CalendarSpec
from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
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


# 只在期间完整时才有意义的统计：缺日会改变均值、极值与计数
PERIOD_STAT_KEYS = ("min", "min_date", "max", "max_date", "mean")


def _date_coverage(curve: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                   calendar: CalendarSpec | None, min_cov: float) -> dict[str, Any]:
    """日期覆盖：对照经核验的预期观测日历，而不是只看已有日期。

    没有日历时无法证明完整，period_complete 为 False 并说明原因。
    """
    observed = curve.dropna(how="all").index
    n_obs = int(len(observed))
    first = observed.min() if n_obs else None
    last = observed.max() if n_obs else None
    tol = pd.Timedelta(days=PERIOD_EDGE_TOLERANCE_DAYS)
    edges_ok = bool(n_obs) and first - start <= tol and end - last <= tol
    out: dict[str, Any] = {
        "curve_days": n_obs,
        "first": first.date().isoformat() if first is not None else None,
        "last": last.date().isoformat() if last is not None else None,
        "min_coverage": min_cov,
        "calendar": calendar.id if calendar else None,
    }
    if calendar is None:
        out.update({"expected_days": None, "date_share": None, "period_complete": False,
                    "incomplete_reason": "数据集未登记预期观测日历，无法证明期间完整"})
        return out
    expected = calendar.expected_dates(start, end)
    unverified = calendar.unverified_span(start, end)
    if unverified:  # 只在确有未核验日期时记录，已核验期间的结果结构保持不变
        out["calendar_unverified"] = unverified
    missing = expected.difference(observed)
    if len(missing):  # 完整列表供覆盖图使用；没有缺失时不写，保持已核验期间的结果结构不变
        out["missing_dates"] = [d.date().isoformat() for d in missing]
    unexpected = observed.difference(expected)
    share = (len(expected) - len(missing)) / len(expected) if len(expected) else 0.0
    complete = edges_ok and share >= min_cov
    out.update({
        "expected_days": int(len(expected)),
        "date_share": share,
        "missing_days": int(len(missing)),
        "missing_examples": [d.date().isoformat() for d in missing[:10]],
        "unexpected_days": [d.date().isoformat() for d in unexpected[:10]],
        "period_complete": complete,
    })
    if not complete:
        out["incomplete_reason"] = (
            f"预期 {len(expected)} 个观测日，实际 {len(expected) - len(missing)} 个（{share:.1%}），"
            f"低于要求 {min_cov:.0%}" if share < min_cov else "数据首尾未覆盖研究期间边界")
    return out


def _restrict_period_stats(summary: dict[str, Any]) -> dict[str, Any]:
    return {**summary, **{k: None for k in PERIOD_STAT_KEYS if k in summary}}


@register_branch("rates_curve", result_types=(ResultType.DESCRIPTIVE,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    if study.result_type is not ResultType.DESCRIPTIVE:
        raise ValueError("rates_curve 分支目前只支持描述性研究")
    curve_in = inputs["curve"]
    method = study.method
    start = pd.Timestamp(study.scope["start"])
    end = pd.Timestamp(study.scope["end"])
    min_cov = float(method.get("min_coverage", 0.95))
    spec = registry.dataset(curve_in.dataset_id)
    calendar = registry.calendars.get(spec.calendar) if spec.calendar else None

    tenor_of = _tenor_map(curve_in)
    period = _in_period(curve_in.frame, start, end)
    usable = ok_rows(period)
    curve = curve_frame(usable, tenor_of)
    curve = curve.reindex(columns=sorted(curve.columns, key=lambda c: parse_tenor(c).months))

    unsupported: list[dict[str, str]] = []
    limitations = list(study.limitations)

    # ---- 日期覆盖与期限覆盖（分别判断） ------------------------------------
    coverage = _date_coverage(curve, start, end, calendar, min_cov)
    period_complete = coverage["period_complete"]
    # 期限覆盖的分母是预期观测日；没有日历时退回已有日期并在覆盖中注明
    denominator = coverage["expected_days"] or coverage["curve_days"]
    tenor_cov: dict[str, Any] = {}
    supported: set[str] = set()
    for t in method["key_tenors"]:
        code = parse_tenor(t).code
        n = int(curve[code].notna().sum()) if code in curve else 0
        share = n / denominator if denominator else 0.0
        tenor_cov[code] = {"observations": n, "share": share}
        if share >= min_cov:
            supported.add(code)
        else:
            unsupported.append({"item": f"期限 {code}",
                                "reason": f"有效观测占比 {share:.1%} 低于要求 {min_cov:.0%}"})
    coverage["tenors"] = tenor_cov
    coverage["tenor_denominator"] = "expected_days" if coverage["expected_days"] else "observed_days"
    coverage["excluded_rows"] = (period["quality_status"].value_counts()
                                 .drop("ok", errors="ignore").to_dict())
    coverage["dataset_issues"] = [
        i for i in curve_in.version.quality.get("issues", []) if i.get("series_id") in tenor_of]

    if coverage.get("calendar_unverified"):
        limitations.append(
            f"预期观测日历 {coverage['calendar']} 未在 {'、'.join(coverage['calendar_unverified'])} 核验，"
            "该段的预期日期按规则推定，临时休市或额外发布日可能使日期覆盖略有偏差")
    if not period_complete:
        covered = f"{coverage['first']} 至 {coverage['last']}" if coverage["curve_days"] else "无"
        limitations.append(
            f"研究期间 {start.date()} 至 {end.date()} 未能证明完整覆盖（{coverage['incomplete_reason']}；"
            f"实际覆盖 {covered}）。只保留首尾有效观测的对比，均值、极值与倒挂天数等期间统计不输出")
        unsupported.append({"item": "期间统计（均值、极值、倒挂天数）",
                            "reason": coverage["incomplete_reason"]})

    # ---- 水平、利差与曲率 -----------------------------------------------
    def summarize(series: pd.Series, unit: str) -> dict[str, Any]:
        out = level_summary(series, unit)
        return out if period_complete else _restrict_period_stats(out)

    levels = {code: summarize(curve[code], "percent") for code in sorted(
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
        spreads[name] = {**summarize(series, "bp"),
                         "inversion": inversion_stats(series) if period_complete else None}

    curvature: dict[str, Any] = {}
    if method.get("curvature"):
        s, m, l = (parse_tenor(t).code for t in method["curvature"])
        name = f"{s}/{m}/{l}"
        if {s, m, l} <= supported:
            series = curvature_bp(curve, s, m, l)
            spread_series[f"curvature {name}"] = series
            curvature[name] = summarize(series, "bp")
        else:
            unsupported.append({"item": f"曲率 {name}", "reason": "所需期限覆盖不足"})

    n_days = coverage["curve_days"]
    first = pd.Timestamp(coverage["first"]) if n_days else None
    last = pd.Timestamp(coverage["last"]) if n_days else None

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
                     **{f"inversion_{kk}": vv for kk, vv in (v["inversion"] or {}).items()}}
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
