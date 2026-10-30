"""研究分支：美国炼油利用率、裂解价差与炼油公司股东总收益的描述性对照（docs/supply-chain-research-design.md §5.4）。

裂解价差单元：逐周用声明的成分与系数计算裂解价差（美元/桶），缺任一成分的周不计算、不插值。
利用率与价差单元：两者同周的水平相关（Pearson、Spearman），以及逐年的相关与年均值。
总收益单元（每家公司一个）：从 10-K 业绩图的累计总收益指数换算日历年收益 r = V_t ÷ V_(t-1) − 1，
每年取声明的主申报中同时含两个年末的一份；与其他申报重叠的年份按两位小数的舍入区间核对，标普 500 另在公司之间核对。
对照单元：每家公司的年度超额收益（公司 − 标普 500）与年均价差、价差变化、年均利用率的 Spearman 相关。

结果是描述性的：价差是声明的指标定义，不是炼厂实际毛利；年度样本只有十年左右，不检验显著性，不输出交易信号或收益预测。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..analytics.rounding import ratio_interval
from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from .base import ResearchResult, StudyInput, input_record, register_branch
from .feasibility import Assessment, assess

MODEL = {
    "model_id": "refining_investment.v1",
    "activity": "petroleum_refining",
    "market": "US",
    "frequency": "weekly",
    "answers": ["周度炼厂利用率与声明裂解价差的历史关系（水平相关与年度汇总）",
                "选定炼油公司日历年股东总收益相对标普 500 的表现，与年均价差、利用率的描述性对照"],
    "cannot_answer": ["炼厂或公司的实际炼油毛利（价差是指标定义）", "股价预测、交易信号或因果关系",
                      "业绩图未以文字列出数值的公司", "一体化石油公司（上游、化工、零售另有影响）"],
}

# 每个价格与利用率角色所需的序列与单位；与数据不符为硬错误
SERIES_REQUIREMENTS = {
    "utilization": {"series": "WPULEUS3", "unit": "percent", "meaning": "官方周度利用率"},
    "crude": {"series": "RWTC", "unit": "usd_per_barrel", "meaning": "WTI 库欣现货周均价"},
    "gasoline": {"series": "EER_EPMRU_PF4_RGC_DPG", "unit": "usd_per_gallon", "meaning": "墨西哥湾沿岸常规汽油现货周均价"},
    "distillate": {"series": "EER_EPD2DXL0_PF4_RGC_DPG", "unit": "usd_per_gallon",
                   "meaning": "墨西哥湾沿岸超低硫柴油现货周均价"},
}
TSR_UNIT = "index_base_100"
TSR_DECIMALS = 2  # 业绩图数值保留两位小数
WEEK_END = "FRI"

_EMPTY = pd.Series(dtype="float64", index=pd.DatetimeIndex([]))


def _series(inp: StudyInput, req: dict[str, Any], errors: list[str]) -> pd.Series:
    frame = inp.frame
    units = set(frame["unit"].dropna())
    if units != {req["unit"]}:
        errors.append(f"{inp.role}（{inp.dataset_id}）的单位为 {sorted(units)}，模型要求 {req['unit']}")
        return _EMPTY.copy()
    ids = set(frame["series_id"])
    if ids != {req["series"]}:
        errors.append(f"{inp.role}（{inp.dataset_id}）的序列为 {sorted(ids)}，模型要求 {req['series']}")
        return _EMPTY.copy()
    rows = ok_rows(frame)
    return pd.Series(rows["value"].astype(float).to_numpy(), index=pd.DatetimeIndex(rows["observation_at"]).tz_localize(None))


def _route(study: StudySpec) -> None:
    wrong = {k: (study.scope.get(k), MODEL[k]) for k in ("activity", "market", "frequency")
             if study.scope.get(k) != MODEL[k]}
    if wrong:
        raise ValueError("研究定义与炼油投资对照模型的适用范围不符："
                         + "；".join(f"{k} 为 {a!r}，模型适用于 {b!r}" for k, (a, b) in wrong.items()))
    if study.result_type is not ResultType.DESCRIPTIVE:
        raise ValueError("refining_investment 分支只产出描述统计成果")


def _crack_definition(method: dict[str, Any]) -> dict[str, Any]:
    spec = dict(method.get("crack_spread") or {})
    weights = {k: spec.get(k) for k in ("crude", "gasoline", "distillate")}
    bad = [k for k, v in weights.items() if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0]
    if bad or weights["gasoline"] + weights["distillate"] != weights["crude"]:
        raise ValueError("裂解价差须声明正的 crude、gasoline、distillate 桶数，且产品桶数之和等于原油桶数："
                         f"{weights}")
    if spec.get("gallons_per_barrel") != 42:
        raise ValueError("gallons_per_barrel 须为 42（美制加仑/桶）")
    return {"id": spec.get("id", "crack"), **weights, "gallons_per_barrel": 42}


def _spearman(x: pd.Series, y: pd.Series) -> float:
    """Spearman 相关 = 平均秩的 Pearson 相关（不依赖 scipy）。"""
    return float(x.rank().corr(y.rank()))


def _corr(a: pd.Series, b: pd.Series) -> dict[str, Any]:
    j = pd.concat([a, b], axis=1).dropna()
    if len(j) < 3:
        return {"n": int(len(j)), "pearson": None, "spearman": None}
    x, y = j.iloc[:, 0], j.iloc[:, 1]
    return {"n": int(len(j)), "pearson": float(x.corr(y)), "spearman": _spearman(x, y)}


def _weekly(series: dict[str, pd.Series], crack: dict[str, Any], start: pd.Timestamp, end: pd.Timestamp,
            errors: dict[str, list[str]]) -> pd.DataFrame:
    expected = pd.date_range(start, end, freq=f"W-{WEEK_END}")
    for role, s in series.items():
        window = s[(s.index >= start) & (s.index <= end)]
        off = window.index[window.index.day_of_week != 4]
        if len(off):
            errors[role].append(f"{role} 有 {len(off)} 个观测日期不是周五（如 {off[0].date()}），周度口径可能已变化")
    frame = pd.DataFrame({role: s.reindex(expected) for role, s in series.items()}, index=expected)
    gal = crack["gallons_per_barrel"]
    frame["crack"] = (crack["gasoline"] * gal * frame["gasoline"] + crack["distillate"] * gal * frame["distillate"]
                      - crack["crude"] * frame["crude"]) / crack["crude"]
    return frame


def _annual_returns(frame: pd.DataFrame, primary: list[str], years: list[int], key: str
                    ) -> tuple[dict[int, dict[str, Any]], list[str]]:
    """每年从第一份同时含两个年末的主申报换算收益与舍入区间；找不到时记为缺失。"""
    out, missing = {}, []
    for y in years:
        for acc in primary:
            s = _index(frame, key, acc)
            a, b = pd.Timestamp(f"{y - 1}-12-31"), pd.Timestamp(f"{y}-12-31")
            if a in s.index and b in s.index:
                lo, hi = ratio_interval(s[b], TSR_DECIMALS, s[a], TSR_DECIMALS)
                out[y] = {"return": s[b] / s[a] - 1, "low": lo - 1, "high": hi - 1, "accession": acc,
                          "start_index": s[a], "end_index": s[b]}
                break
        else:
            missing.append(str(y))
    return out, missing


def _index(frame: pd.DataFrame, key: str, accession: str) -> pd.Series:
    rows = ok_rows(frame[frame["series_id"] == f"{key}|{accession}"])
    return pd.Series(rows["value"].astype(float).to_numpy(),
                     index=pd.DatetimeIndex(rows["observation_at"]).tz_localize(None).normalize())


def _overlap_check(frame: pd.DataFrame, chosen: dict[int, dict[str, Any]], filings: list[str], key: str
                   ) -> dict[str, Any]:
    """其他申报覆盖同一年时，两份申报换算的收益区间须相交（两位小数的舍入，不设经验容差）。"""
    checked, failures = 0, []
    for acc in filings:
        s = _index(frame, key, acc)
        for y, c in chosen.items():
            if acc == c["accession"]:
                continue
            a, b = pd.Timestamp(f"{y - 1}-12-31"), pd.Timestamp(f"{y}-12-31")
            if a not in s.index or b not in s.index:
                continue
            lo, hi = ratio_interval(s[b], TSR_DECIMALS, s[a], TSR_DECIMALS)
            checked += 1
            if hi - 1 < c["low"] or lo - 1 > c["high"]:
                failures.append({"year": y, "series": key, "accession": acc, "return": s[b] / s[a] - 1,
                                 "against": c["accession"], "against_return": c["return"]})
    return {"status": "pass" if checked and not failures else ("fail" if failures else "skipped"),
            "checked": checked, "failures": failures,
            "rule": "同一年由两份申报换算的收益，按指数两位小数传播舍入区间，区间相交即一致"}


def _tsr(inp: StudyInput, company: dict[str, Any], years: list[int], errors: list[str]
         ) -> tuple[dict[str, dict[int, dict[str, Any]]], list[str], dict[str, Any]]:
    frame = inp.frame
    units = set(frame["unit"].dropna())
    if units != {TSR_UNIT}:
        errors.append(f"{inp.role}（{inp.dataset_id}）的单位为 {sorted(units)}，模型要求 {TSR_UNIT}")
        return {}, [str(y) for y in years], {"status": "skipped", "reason": "单位不符"}
    primary = [str(a) for a in company.get("primary") or []]
    filings = sorted({sid.split("|", 1)[1] for sid in frame["series_id"]})
    unknown = [a for a in primary if a not in filings]
    if not primary or unknown:
        errors.append(f"{company['id']} 的主申报 {unknown or '未声明'} 不在 {inp.dataset_id} 中")
        return {}, [str(y) for y in years], {"status": "skipped", "reason": "主申报不在数据中"}
    returns, missing, checks = {}, set(), []
    for key in ("company", "sp500"):
        chosen, miss = _annual_returns(frame, primary, years, key)
        returns[key] = chosen
        missing.update(miss)
        checks.append(_overlap_check(frame, chosen, filings, key))
    check = {"status": "fail" if any(c["status"] == "fail" for c in checks) else
             ("pass" if any(c["status"] == "pass" for c in checks) else "skipped"),
             "checked": sum(c["checked"] for c in checks), "failures": [f for c in checks for f in c["failures"]],
             "filings": filings, "rule": checks[0]["rule"]}
    return returns, sorted(missing), check


def _sp500_check(returns: dict[str, dict[str, dict[int, dict[str, Any]]]]) -> dict[str, Any]:
    """不同公司申报中的标普 500 年度收益区间须相交：同一指数，口径应一致。"""
    ids = [c for c, r in returns.items() if r.get("sp500")]
    checked, failures = 0, []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for y in sorted(set(returns[a]["sp500"]) & set(returns[b]["sp500"])):
                x, z = returns[a]["sp500"][y], returns[b]["sp500"][y]
                checked += 1
                if x["high"] < z["low"] or x["low"] > z["high"]:
                    failures.append({"year": y, a: x["return"], b: z["return"]})
    return {"status": "pass" if checked and not failures else ("fail" if failures else "skipped"),
            "checked": checked, "failures": failures, "companies": ids}


@register_branch("refining_investment", result_types=(ResultType.DESCRIPTIVE,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    _route(study)
    method = study.method
    crack = _crack_definition(method)
    companies = list(method.get("companies") or [])
    if not companies:
        raise ValueError("研究定义没有声明任何公司")
    missing_roles = [r for r in [*SERIES_REQUIREMENTS, *(c["role"] for c in companies)] if r not in inputs]
    if missing_roles:
        raise ValueError(f"研究定义缺少模型所需的输入角色：{', '.join(missing_roles)}")
    start, end = pd.Timestamp(study.scope["start"]), pd.Timestamp(study.scope["end"])
    years = list(range(start.year, end.year + 1))
    if start != pd.Timestamp(f"{start.year}-01-01") or end != pd.Timestamp(f"{end.year}-12-31"):
        raise ValueError("研究期间须为完整日历年（年度总收益按 12 月 31 日换算）")

    errors: dict[str, list[str]] = {role: [] for role in SERIES_REQUIREMENTS}
    series = {role: _series(inputs[role], req, errors[role]) for role, req in SERIES_REQUIREMENTS.items()}
    weekly = _weekly(series, crack, start, end, errors)
    price_roles = [inputs[r] for r in ("crude", "gasoline", "distillate")]
    crack_unit = assess("crack_spread", inputs=price_roles,
                        hard_errors=[e for r in ("crude", "gasoline", "distillate") for e in errors[r]])
    relation_unit = assess("utilization_crack", inputs=[inputs["utilization"]], hard_errors=errors["utilization"],
                           depends_on=[crack_unit])
    units: list[Assessment] = [crack_unit, relation_unit]
    unsupported: list[dict[str, str]] = []
    # 研究问题之外的公司：说明为什么没有纳入，不算作受限结论
    limitations = [*study.limitations, *(f"未纳入 {x['name']}：{x['reason']}" for x in method.get("not_covered") or [])]

    complete = weekly.dropna()
    missing_weeks = [d.date().isoformat() for d in weekly.index if d not in complete.index]
    year_complete = {y: not any(w.startswith(str(y)) for w in missing_weeks) for y in years}
    incomplete_years = [str(y) for y, ok in year_complete.items() if not ok]
    if missing_weeks:
        unsupported.append({"item": "缺周年份的年度汇总", "reason": f"{len(missing_weeks)} 周缺少至少一个数值（不插值），"
                            f"涉及 {'、'.join(incomplete_years)} 年：" + "、".join(missing_weeks[:8])
                            + ("等" if len(missing_weeks) > 8 else "")})

    weekly_rows: list[dict[str, Any]] = []
    crack_stats = relation = None
    by_year: list[dict[str, Any]] = []
    if crack_unit.computable:
        c = weekly["crack"].dropna()
        weekly_rows = [{"week_ending": d.date().isoformat(), **{k: (None if pd.isna(v) else float(v))
                        for k, v in r.items()}} for d, r in weekly.iterrows()]
        if len(c):
            crack_stats = {"weeks": int(len(c)), "mean": float(c.mean()), "median": float(c.median()),
                           "min": float(c.min()), "min_week": c.idxmin().date().isoformat(),
                           "max": float(c.max()), "max_week": c.idxmax().date().isoformat(),
                           "weeks_negative": int((c < 0).sum())}
    if relation_unit.computable:
        relation = _corr(weekly["utilization"], weekly["crack"])
        for y in years:
            w = weekly[weekly.index.year == y]
            done = w.dropna()
            row = {"year": y, "weeks": int(len(w)), "complete_weeks": int(len(done)), "complete": year_complete[y]}
            if year_complete[y]:
                row.update(mean_utilization=float(done["utilization"].mean()), mean_crack=float(done["crack"].mean()),
                           **{f"corr_{k}": v for k, v in _corr(done["utilization"], done["crack"]).items() if k != "n"})
            by_year.append(row)
        for i, row in enumerate(by_year):
            prev = by_year[i - 1] if i else None
            row["crack_change"] = (row["mean_crack"] - prev["mean_crack"]
                                   if prev and row.get("mean_crack") is not None and prev.get("mean_crack") is not None
                                   else None)

    tsr_errors: dict[str, list[str]] = {}
    returns: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
    tsr_missing: dict[str, list[str]] = {}
    validation: dict[str, Any] = {}
    for co in companies:
        errs: list[str] = []
        returns[co["id"]], tsr_missing[co["id"]], validation[f"overlap_check:{co['id']}"] = \
            _tsr(inputs[co["role"]], co, years, errs)
        tsr_errors[co["id"]] = errs
    sp_check = _sp500_check(returns)
    validation["sp500_cross_issuer"] = sp_check

    tsr_units: dict[str, Assessment] = {}
    annual: list[dict[str, Any]] = []
    tsr_summary: dict[str, Any] = {}
    comparison: dict[str, Any] = {}
    for co in companies:
        cid = co["id"]
        failed = []
        ov = validation[f"overlap_check:{cid}"]
        if ov["status"] == "fail":
            failed.append(f"{len(ov['failures'])} 个年度收益在申报之间不一致")
        if sp_check["status"] == "fail":
            failed.append(f"标普 500 年度收益在公司申报之间有 {len(sp_check['failures'])} 处不一致")
        if tsr_missing[cid]:
            failed.append(f"主申报未覆盖 {'、'.join(tsr_missing[cid])} 年")
        unit = assess(f"tsr:{cid}", inputs=[inputs[co["role"]]], hard_errors=tsr_errors[cid], failed_checks=failed)
        tsr_units[cid] = unit
        units.append(unit)
        if not unit.computable:
            unsupported.append({"item": f"{co['name']} 年度总收益", "reason": f"输入能力为 {unit.grade}："
                                + "；".join(unit.reasons)})
            continue
        r = returns[cid]
        wealth = {k: float(pd.Series([1 + r[k][y]["return"] for y in years]).prod()) for k in ("company", "sp500")}
        tsr_summary[cid] = {"name": co["name"], "years": len(years),
                            "cumulative": {k: v - 1 for k, v in wealth.items()},
                            "annualized": {k: v ** (1 / len(years)) - 1 for k, v in wealth.items()},
                            "years_beating_sp500": int(sum(r["company"][y]["return"] > r["sp500"][y]["return"]
                                                           for y in years))}
        for y in years:
            annual.append({"company": cid, "year": y, "tsr": r["company"][y]["return"],
                           "tsr_low": r["company"][y]["low"], "tsr_high": r["company"][y]["high"],
                           "sp500": r["sp500"][y]["return"], "excess": r["company"][y]["return"] - r["sp500"][y]["return"],
                           "accession": r["company"][y]["accession"]})

        comp = assess(f"comparison:{cid}", inputs=[inputs[co["role"]], inputs["utilization"], *price_roles],
                      depends_on=[relation_unit, unit])
        units.append(comp)
        if not comp.computable:
            unsupported.append({"item": f"{co['name']} 与价差、利用率的对照", "reason": f"输入能力为 {comp.grade}："
                                + "；".join(comp.reasons)})
            continue
        ys = [b for b in by_year if b["complete"]]
        excess = pd.Series({b["year"]: r["company"][b["year"]]["return"] - r["sp500"][b["year"]]["return"] for b in ys})

        def rank(field: str) -> dict[str, Any]:
            x = pd.Series({b["year"]: b[field] for b in ys if b.get(field) is not None}, dtype="float64")
            j = pd.concat([x, excess], axis=1).dropna()
            return {"n": int(len(j)), "spearman": _spearman(j.iloc[:, 0], j.iloc[:, 1])
                    if len(j) >= 3 else None}
        comparison[cid] = {"name": co["name"], "excess_vs_mean_crack": rank("mean_crack"),
                           "excess_vs_crack_change": rank("crack_change"),
                           "excess_vs_mean_utilization": rank("mean_utilization")}
    if comparison:
        limitations.append(f"年度对照只有 {len(years)} 年（价差变化 {len(years) - 1} 年），Spearman 相关只描述排序关系，不检验显著性")

    cutoff = complete.index.max().date().isoformat() if len(complete) else None
    coverage = {
        "first_week": weekly.index[0].date().isoformat() if len(weekly) else None,
        "last_week": weekly.index[-1].date().isoformat() if len(weekly) else None,
        "expected_weeks": int(len(weekly)), "valid_weeks": int(len(complete)), "missing_weeks": missing_weeks,
        "years": years, "incomplete_years": incomplete_years,
        "tsr_missing_years": {k: v for k, v in tsr_missing.items() if v},
        "completeness": "partial" if missing_weeks or any(tsr_missing.values()) or not len(complete) else "complete",
    }
    return ResearchResult(
        study_id=study.study_id,
        title=study.title,
        question=study.question,
        result_type=study.result_type,
        branch=study.branch,
        scope=study.scope,
        data_cutoff=cutoff,
        methods={
            "description": f"逐周计算 {crack['crude']}-{crack['gasoline']}-{crack['distillate']} 裂解价差 = "
                           f"({crack['gasoline']} × 42 × 汽油 + {crack['distillate']} × 42 × 柴油 − {crack['crude']} × 原油) ÷ "
                           f"{crack['crude']}（美元/桶），缺任一成分的周不计算；利用率与价差取同周水平相关与逐年汇总。"
                           "公司日历年总收益由 10-K 业绩图累计总收益指数相邻年末之比换算，"
                           "重叠申报与跨公司的标普 500 按舍入区间核对；超额收益 = 公司 − 标普 500。",
            "benchmark": study.benchmark,
            "model": MODEL,
            "series_requirements": SERIES_REQUIREMENTS,
            "crack_spread": crack,
            "parameters": method,
            "availability_rule": inputs["crude"].version.quality.get("availability_rule"),
        },
        inputs=[input_record(i) for i in inputs.values()],
        results={
            "feasibility": {u.unit: u.to_dict() for u in units},
            "crack_spread": crack_stats,
            "utilization_crack": relation,
            "by_year": by_year,
            "tsr": tsr_summary,
            "comparison": comparison,
        },
        coverage=coverage,
        unsupported=unsupported,
        limitations=limitations,
        validation=validation,
        tables={"weekly": weekly_rows, "annual_tsr": annual},
    )
