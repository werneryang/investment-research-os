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
from ..contracts import DatasetSpec, ResultType
from ..data.timing import available_at
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from ..tenor import parse_tenor
from ..validation.crosscheck import compare_series
from .base import ResearchResult, StudyInput, input_record, register_branch

# 没有日历时，研究期间首尾允许的空档（日历天）
PERIOD_EDGE_TOLERANCE_DAYS = 7

# 期间统计：缺日会改变均值、极值与计数。覆盖不达标时不输出；有缺口但达标时标为已观测样本
PERIOD_STAT_KEYS = ("min", "min_date", "max", "max_date", "mean")

# 完整性判断结果
COMPLETE = "complete"  # 所有预期观测日都有数据，日历已核验
COMPLETE_TO_DATE = "complete_to_date"  # 已到保守可用时点的日期都有数据，另有日期下载时未到可用时点
GAPS = "gaps"  # 有应已发布但缺失的日期（覆盖仍达标）
UNVERIFIED_CALENDAR = "unverified_calendar"  # 没有缺失，但相关日期超出日历核验范围，无法证明完整
CALENDAR_CONFLICT = "calendar_conflict"  # 有日历预期之外的观测，隔离并等待核对
INSUFFICIENT = "insufficient"  # 覆盖低于要求
NO_CALENDAR = "no_calendar"  # 未登记预期日历，无法判断
COMPLETE_STATES = (COMPLETE, COMPLETE_TO_DATE)


def _tenor_map(inp: StudyInput) -> dict[str, str]:
    mapping = {}
    for sid, meta in inp.version.series.items():
        if "tenor" in meta:
            mapping[sid] = parse_tenor(meta["tenor"]).code
    return mapping


def _in_period(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[(df["observation_at"] >= start) & (df["observation_at"] <= end)]


def _pending_mask(expected: pd.DatetimeIndex, spec: DatasetSpec, retrieved_at: Any) -> pd.Series:
    """按数据集的保守可用时间规则，判断哪些预期日期在数据下载时尚未到可用时点。

    可用时间规则是「最早可用于研究决策」的保守时点，不是实际发布时间：这类日期没有数据，
    只能说明下载时还不应期望它有数据，不能确认它尚未发布。
    没有下载时间或规则无法给出时间时，一律视为应已可用，不放宽缺失判断。
    """
    if retrieved_at is None or pd.isna(retrieved_at) or not len(expected):
        return pd.Series(False, index=expected)
    obs = pd.Series(expected, index=expected)
    avail = available_at(obs, pd.Series(None, index=expected, dtype="object"), spec.frequency,
                         spec.availability, spec.timezone)
    at = pd.Timestamp(retrieved_at)
    at = at.tz_localize("UTC") if at.tzinfo is None else at.tz_convert("UTC")
    return avail.notna() & (avail > at)


def _date_coverage(curve: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                   calendar: CalendarSpec | None, spec: DatasetSpec, min_cov: float,
                   retrieved_at: Any) -> dict[str, Any]:
    """日期覆盖：对照经核验的预期观测日历，区分已观测、未取得（下载时未到可用时点）与缺失。

    - 未取得：数据下载时尚未到保守可用时点、且没有数据的预期日期；不计入分母，单独列出。
      这不代表已确认尚未发布——也可能已发布但下载时还不应期望取得
    - 缺失：下载时已过保守可用时点，却没有数据的预期日期
    - coverage_acceptable：覆盖是否达到 min_cov，决定期间统计能否输出
    - period_complete / completeness：所有应考虑的日期都有数据，且这些日期在日历核验范围内
    """
    observed = curve.dropna(how="all").index
    expected = calendar.expected_dates(start, end) if calendar is not None else None
    unexpected = observed.difference(expected) if expected is not None else pd.DatetimeIndex([])
    if expected is not None:
        observed = observed.intersection(expected)
    n_obs = int(len(observed))
    first = observed.min() if n_obs else None
    last = observed.max() if n_obs else None
    out: dict[str, Any] = {
        "curve_days": n_obs,
        "first": first.date().isoformat() if first is not None else None,
        "last": last.date().isoformat() if last is not None else None,
        "min_coverage": min_cov,
        "calendar": calendar.id if calendar else None,
    }
    if calendar is None:
        tol = pd.Timedelta(days=PERIOD_EDGE_TOLERANCE_DAYS)
        edges_ok = bool(n_obs) and first - start <= tol and end - last <= tol
        out.update({"expected_days": None, "due_days": None, "date_share": None,
                    "coverage_acceptable": False, "period_complete": False, "completeness": NO_CALENDAR,
                    "edges_ok": edges_ok,
                    "incomplete_reason": "数据集未登记预期观测日历，无法证明期间完整"})
        return out

    not_due = _pending_mask(expected, spec, retrieved_at)
    pending = expected[not_due.to_numpy()].difference(observed)  # 已有数据的日期照常计入
    considered = expected.difference(pending)
    missing = considered.difference(observed)
    share = (len(considered) - len(missing)) / len(considered) if len(considered) else 0.0
    last_considered = considered.max() if len(considered) else None
    unverified = calendar.unverified_span(start, last_considered) if last_considered is not None else []

    if len(unexpected):
        state = CALENDAR_CONFLICT
    elif not len(considered) or share < min_cov:
        state = INSUFFICIENT
    elif len(missing):
        state = GAPS
    elif unverified:
        state = UNVERIFIED_CALENDAR
    elif len(pending):
        state = COMPLETE_TO_DATE
    else:
        state = COMPLETE

    out.update({
        "expected_days": int(len(expected)),
        "due_days": int(len(considered)),
        "date_share": share,
        "missing_days": int(len(missing)),
        "missing_examples": [d.date().isoformat() for d in missing[:10]],
        "unexpected_days": [d.date().isoformat() for d in unexpected],
        "coverage_acceptable": bool(len(considered)) and share >= min_cov,
        "period_complete": state == COMPLETE,
        "completeness": state,
    })
    # 以下列表只在非空时写入
    if len(missing):
        out["missing_dates"] = [d.date().isoformat() for d in missing]
    if len(pending):
        out["pending_days"] = int(len(pending))
        out["pending_dates"] = [d.date().isoformat() for d in pending]
    if unverified:
        out["calendar_unverified"] = unverified
    if state not in COMPLETE_STATES:
        out["incomplete_reason"] = {
            CALENDAR_CONFLICT: f"发现 {len(unexpected)} 个日历预期之外的观测日，已隔离并等待核对："
                               + "、".join(d.date().isoformat() for d in unexpected[:10]),
            INSUFFICIENT: f"应已发布 {len(considered)} 个观测日，实际 {len(considered) - len(missing)} 个"
                          f"（{share:.1%}），低于要求 {min_cov:.0%}",
            GAPS: f"应已发布的 {len(considered)} 个观测日中缺少 {len(missing)} 个",
            UNVERIFIED_CALENDAR: f"预期日历未在 {'、'.join(unverified)} 核验，无法证明这些日期没有缺失",
        }[state]
    return out


def _metric_coverage(present: pd.Series, considered: pd.DatetimeIndex | None) -> dict[str, Any]:
    """单个指标在应考虑日期上的覆盖：present 为该指标有合格值的日期（利差要求两端同时有值）。"""
    have = present[present].index
    if considered is None:
        return {"observed": int(len(have)), "due": None, "missing": None, "complete": False}
    missing = considered.difference(have)
    return {"observed": int(len(considered.intersection(have))), "due": int(len(considered)),
            "missing": int(len(missing)), "complete": not len(missing)}


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
    # 以数据的下载时间（而不是评估时间）判断哪些日期还不应期望有数据：取数据版本的下载时间与
    # 运行时固定的「最近一次成功下载」（内容未变时不产生新版本）中较晚者；两者都随运行固定，复现时不变
    candidates = [curve_in.frame["retrieved_at"].max()] if len(curve_in.frame) else []
    checked = (study.scope.get("data_checked_at") or {}).get(curve_in.dataset_id)
    if checked:
        candidates.append(pd.Timestamp(checked))
    candidates = [pd.Timestamp(t).tz_convert("UTC") if pd.Timestamp(t).tzinfo else pd.Timestamp(t).tz_localize("UTC")
                  for t in candidates if t is not None and not pd.isna(t)]
    retrieved = max(candidates) if candidates else None
    coverage = _date_coverage(curve, start, end, calendar, spec, min_cov, retrieved)
    if retrieved is not None and not pd.isna(retrieved):
        coverage["data_retrieved_at"] = pd.Timestamp(retrieved).isoformat()
    coverage["availability_rule"] = spec.availability.describe()
    acceptable = coverage["coverage_acceptable"]
    complete_state = coverage["completeness"] in COMPLETE_STATES
    considered = None
    if calendar is not None:
        pending = pd.DatetimeIndex(pd.to_datetime(coverage.get("pending_dates", [])))
        considered = calendar.expected_dates(start, end).difference(pending)
        # 日历之外的观测只留在覆盖异常记录与原数据中，不进入任何研究统计或图表。
        curve = curve.loc[curve.index.isin(considered)]
    # 期限覆盖的分母是应已发布的观测日；没有日历时退回已有日期并在覆盖中注明
    denominator = coverage["due_days"] or coverage["curve_days"]
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
            unsupported.append({"item": f"期限 {code}", "kind": "data",
                                "reason": f"有效观测占比 {share:.1%} 低于要求 {min_cov:.0%}"})
    coverage["tenors"] = tenor_cov
    coverage["tenor_denominator"] = "due_days" if coverage["due_days"] else "observed_days"
    coverage["excluded_rows"] = (period["quality_status"].value_counts()
                                 .drop("ok", errors="ignore").to_dict())
    coverage["dataset_issues"] = [
        i for i in curve_in.version.quality.get("issues", []) if i.get("series_id") in tenor_of]

    if coverage.get("calendar_unverified"):
        limitations.append(
            f"预期观测日历 {coverage['calendar']} 未在 {'、'.join(coverage['calendar_unverified'])} 核验，"
            "该段的预期日期按规则推定，临时休市或额外发布日可能使日期覆盖略有偏差，无法证明没有缺失")
    if coverage.get("pending_days"):
        limitations.append(
            f"研究窗口内有 {coverage['pending_days']} 个预期观测日未取得（{'、'.join(coverage['pending_dates'][:5])}）："
            f"数据最近一次下载时尚未到保守可用时点（{coverage['availability_rule']}），不计入覆盖；"
            f"这不代表已确认尚未发布。结果截至 {coverage['last']}")
        # 下载时间不写进限制文字：它每次运行都不同，会让结论相同的运行被当作变化；时间见证据面板
    covered = f"{coverage['first']} 至 {coverage['last']}" if coverage["curve_days"] else "无"
    if not acceptable:
        limitations.append(
            f"研究期间 {start.date()} 至 {end.date()} 覆盖不足（{coverage['incomplete_reason']}；"
            f"实际覆盖 {covered}）。只保留首尾有效观测的对比，均值、极值与倒挂天数等期间统计不输出")
        unsupported.append({"item": "期间统计（均值、极值、倒挂天数）", "kind": "data",
                            "reason": coverage["incomplete_reason"]})
    elif not complete_state:
        limitations.append(
            f"研究期间未能证明完整（{coverage['incomplete_reason']}）。均值、极值与倒挂天数只基于已观测日期，"
            "是已观测样本统计，不能推及整个期间")

    metrics: dict[str, dict[str, Any]] = {"levels": {}, "spreads": {}, "curvature": {}}

    # ---- 水平、利差与曲率 -----------------------------------------------
    def summarize(series: pd.Series, unit: str, group: str, key: str) -> dict[str, Any]:
        """期间统计：覆盖不达标时不输出；指标或期间有缺口时标为已观测样本。"""
        mc = _metric_coverage(series.notna(), considered)
        metrics[group][key] = mc
        out = level_summary(series, unit)
        if not acceptable:
            return _restrict_period_stats(out)
        complete_sample = complete_state and mc["complete"]
        return {**out, "sample": "complete" if complete_sample else "observed",
                "missing_days": mc["missing"]}

    levels = {code: summarize(curve[code], "percent", "levels", code) for code in sorted(
        supported, key=lambda c: parse_tenor(c).months)}

    spreads: dict[str, Any] = {}
    spread_series: dict[str, pd.Series] = {}
    for short, long in method.get("spreads", []):
        s, l = parse_tenor(short).code, parse_tenor(long).code
        name = f"{s}-{l}"
        if not {s, l} <= supported:
            unsupported.append({"item": f"利差 {name}", "kind": "data", "reason": "所需期限覆盖不足"})
            continue
        series = spread_bp(curve, s, l)  # 两端同一天都有值才有利差
        spread_series[name] = series
        spreads[name] = {**summarize(series, "bp", "spreads", name),
                         "inversion": inversion_stats(series) if acceptable else None}

    curvature: dict[str, Any] = {}
    if method.get("curvature"):
        s, m, l = (parse_tenor(t).code for t in method["curvature"])
        name = f"{s}/{m}/{l}"
        if {s, m, l} <= supported:
            series = curvature_bp(curve, s, m, l)
            spread_series[f"curvature {name}"] = series
            curvature[name] = summarize(series, "bp", "curvature", name)
        else:
            unsupported.append({"item": f"曲率 {name}", "kind": "data", "reason": "所需期限覆盖不足"})

    coverage["metrics"] = metrics
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
