"""研究分支：美国主要资产的长期回报与风险（描述与比较，设计见 docs/study-long-run-assets.md）。

全部是可以手算核对的统计量：年度回报的算术与几何平均、波动率、最差年份、亏损年数、最大回撤，
扣除 CPI 通胀后的实际回报，股票风险溢价，全期与事先固定时期的相关系数，滚动几何平均回报。
股票另用月度数据计算最大回撤，并与年度数据交叉核对。只描述历史，不推断未来，不给配置建议。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contracts import ResultType
from ..quality import ok_rows
from ..registry import Registry, StudySpec
from .base import ResearchResult, StudyInput, input_record, register_branch

ASSETS = ("SP500", "SMALLCAP", "TBOND10Y", "BAA", "TBILL3M", "REALESTATE", "GOLD")
ASSET_NAMES = {"SP500": "标普 500", "SMALLCAP": "小盘股", "TBOND10Y": "10 年期国债", "BAA": "Baa 公司债",
               "TBILL3M": "3 个月国库券", "REALESTATE": "房地产", "GOLD": "黄金"}


def _annual(inp: StudyInput, prefix: str = "DAM_") -> pd.DataFrame:
    f = ok_rows(inp.frame)
    w = f.pivot(index="observation_at", columns="series_id", values="value").sort_index()
    w.index = w.index.year
    w.columns = [c.removeprefix(prefix) for c in w.columns]
    return w


def _series(inp: StudyInput, series_id: str | None = None) -> pd.Series:
    f = ok_rows(inp.frame)
    if series_id is not None:
        f = f[f["series_id"] == series_id]
    return f.set_index("observation_at")["value"].sort_index()


def _geo(x: pd.Series) -> float:
    return float((1 + x).prod() ** (1 / len(x)) - 1)


def _max_drawdown(x: pd.Series) -> dict[str, Any]:
    wealth = (1 + x).cumprod()
    dd = wealth / wealth.cummax() - 1
    trough = dd.idxmin()
    peak = wealth.loc[:trough].idxmax()
    return {"max_drawdown": float(dd.min()), "peak": peak, "trough": trough}


def _stats(x: pd.Series) -> dict[str, Any]:
    x = x.dropna()
    dd = _max_drawdown(x)
    return {"years": int(len(x)), "first_year": int(x.index.min()), "last_year": int(x.index.max()),
            "arithmetic": float(x.mean()), "geometric": _geo(x), "volatility": float(x.std(ddof=1)),
            "worst": float(x.min()), "worst_year": int(x.idxmin()), "best": float(x.max()), "best_year": int(x.idxmax()),
            "negative_years": int((x < 0).sum()), "max_drawdown": dd["max_drawdown"],
            "drawdown_peak_year": int(dd["peak"]), "drawdown_trough_year": int(dd["trough"])}


def _corr(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    c = frame.corr()
    return {a: {b: float(c.loc[a, b]) for b in c.columns} for a in c.index}


def _cpi_inflation(inp: StudyInput) -> pd.Series:
    """CPI 12 月对 12 月的年通胀；只在相邻两年都有 12 月数据时计算。"""
    cpi = _series(inp)
    dec = cpi[cpi.index.month == 12]
    dec.index = dec.index.year
    infl = dec / dec.shift(1) - 1
    return infl[dec.index.to_series().diff() == 1].dropna()


@register_branch("asset_history", result_types=(ResultType.DESCRIPTIVE,))
def run(study: StudySpec, inputs: dict[str, StudyInput], registry: Registry) -> ResearchResult:
    if study.result_type is not ResultType.DESCRIPTIVE:
        raise ValueError("asset_history 分支只产出描述与比较成果")
    m = study.method
    annual = _annual(inputs["annual"])
    assets = [a for a in m.get("assets", ASSETS) if a in annual.columns]
    start, end = pd.Timestamp(study.scope["start"]), pd.Timestamp(study.scope["end"])
    # 只用完整年度：观测年份在研究范围内，且所有资产都有值
    years = annual[assets].dropna().loc[start.year:end.year]
    last_n = m.get("last_n_years")
    if last_n:
        years = years.iloc[-int(last_n):]
    if len(years) < 2:
        raise ValueError(f"研究范围 {start.date()} 至 {end.date()} 内完整年度不足 2 年")
    first_year, last_year = int(years.index.min()), int(years.index.max())

    nominal = {a: _stats(years[a]) for a in assets}
    unsupported: list[dict[str, str]] = []
    limitations = list(study.limitations)

    # 实际回报：(1 + 名义) / (1 + 当年 CPI 通胀) − 1，从 real_start_year 起
    real: dict[str, Any] = {}
    inflation: dict[str, Any] = {}
    real_frame = pd.DataFrame()
    if "cpi" in inputs:
        infl = _cpi_inflation(inputs["cpi"])
        span = years.loc[max(first_year, int(m.get("real_start_year", 1948))):]
        span = span[span.index.isin(infl.index)]
        if len(span) >= 2:
            r = (1 + span).div(1 + infl.loc[span.index], axis=0) - 1
            real_frame = r
            real = {a: {"years": int(len(r)), "first_year": int(r.index.min()), "last_year": int(r.index.max()),
                        "geometric": _geo(r[a]), "arithmetic": float(r[a].mean()), "volatility": float(r[a].std(ddof=1))}
                    for a in assets}
            i = infl.loc[span.index]
            inflation = {"years": int(len(i)), "mean": float(i.mean()), "geometric": _geo(i),
                         "max": float(i.max()), "max_year": int(i.idxmax())}
        else:
            unsupported.append({"item": "实际回报", "kind": "data", "reason": "研究范围内没有可用的 CPI 年通胀"})

    erp: dict[str, Any] = {}
    if "SP500" in assets:
        for base in ("TBILL3M", "TBOND10Y"):
            if base in assets:
                erp[base] = nominal["SP500"]["geometric"] - nominal[base]["geometric"]

    # 相关系数：全期与事先固定的时期（与研究范围相交，至少 10 年）
    correlations = {"full": {"first_year": first_year, "last_year": last_year, "matrix": _corr(years[assets])}}
    periods_out = []
    for lo, hi in m.get("periods", []):
        part = years.loc[max(lo, first_year):min(hi, last_year)]
        if len(part) >= 10:
            periods_out.append({"first_year": int(part.index.min()), "last_year": int(part.index.max()),
                                "years": int(len(part)), "matrix": _corr(part[assets])})
    correlations["periods"] = periods_out

    # 时期边界敏感性：股票与长期国债的相关系数，边界前后移动 shift 年
    sensitivity: dict[str, Any] = {}
    shift = int(m.get("period_shift_years", 5))
    if periods_out and {"SP500", "TBOND10Y"} <= set(assets):
        bounds = [p for p in m.get("periods", [])]
        out = []
        for k, (lo, hi) in enumerate(bounds):
            values = []
            for dlo in (-shift, 0, shift):
                for dhi in (-shift, 0, shift):
                    a = max(first_year, lo + (dlo if k > 0 else 0))
                    b = min(last_year, hi + (dhi if k < len(bounds) - 1 else 0))
                    part = years.loc[a:b]
                    if len(part) >= 10:
                        values.append(float(part["SP500"].corr(part["TBOND10Y"])))
            if values:
                out.append({"period": [lo, hi], "min": min(values), "max": max(values),
                            "sign_stable": min(values) > 0 or max(values) < 0})
        sensitivity = {"shift_years": shift, "stock_bond_correlation": out}

    rolling: dict[str, Any] = {}
    window = int(m.get("rolling_years", 20))
    if "SP500" in assets and len(years) >= window:
        roll = (1 + years["SP500"]).rolling(window).apply(np.prod, raw=True) ** (1 / window) - 1
        roll = roll.dropna()
        rolling = {"window_years": window, "asset": "SP500", "windows": int(len(roll)),
                   "min": float(roll.min()), "min_end_year": int(roll.idxmin()),
                   "max": float(roll.max()), "max_end_year": int(roll.idxmax())}

    validation: dict[str, Any] = {}
    monthly: dict[str, Any] = {}
    if "monthly_market" in inputs:
        ff = inputs["monthly_market"]
        mret = (_series(ff, "FF3_Mkt-RF") + _series(ff, "FF3_RF")) / 100
        mret = mret[(mret.index.year >= first_year) & (mret.index.year <= last_year)]
        if len(mret) >= 12:
            dd = _max_drawdown(mret)
            monthly = {"months": int(len(mret)), "max_drawdown": dd["max_drawdown"],
                       "peak": dd["peak"].strftime("%Y-%m"), "trough": dd["trough"].strftime("%Y-%m"),
                       "worst_month": float(mret.min()), "worst_month_at": mret.idxmin().strftime("%Y-%m"),
                       "annualized_volatility": float(mret.std(ddof=1) * np.sqrt(12))}
            annual_ff = (1 + mret).groupby(mret.index.year).prod() - 1
            j = pd.concat([years["SP500"], annual_ff], axis=1, join="inner").dropna() if "SP500" in assets else None
            if j is not None and len(j) >= 5:
                corr = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
                validation["cross_check_equity"] = {
                    "status": "pass" if corr >= 0.98 else "fail", "against": ff.dataset_id, "years": int(len(j)),
                    "correlation": corr, "threshold": 0.98,
                    "median_abs_diff_pp": float((j.iloc[:, 0] - j.iloc[:, 1]).abs().median() * 100),
                    "note": "标普 500（Damodaran）与 CRSP 全市场（French）指数不同，只核对年度回报高度一致"}
            validation["monthly_drawdown"] = {
                "status": "pass" if dd["max_drawdown"] <= nominal.get("SP500", {}).get("max_drawdown", 0) + 1e-12
                else "fail",
                "monthly": dd["max_drawdown"], "annual": nominal.get("SP500", {}).get("max_drawdown"),
                "note": "月度数据的最大回撤应不浅于年度数据（年度数据会低估年内跌幅）"}
    if "tbill_check" in inputs and "TBILL3M" in assets:
        tb = _series(inputs["tbill_check"])
        tb_annual = tb.groupby(tb.index.year).mean() / 100
        j = pd.concat([years["TBILL3M"], tb_annual], axis=1, join="inner").dropna()
        if len(j):
            diff = (j.iloc[:, 0] - j.iloc[:, 1]).abs() * 100
            validation["cross_check_tbill"] = {
                "status": "pass" if diff.max() <= 0.5 else "fail", "against": inputs["tbill_check"].dataset_id,
                "years": int(len(j)), "max_abs_diff_pp": float(diff.max()), "tolerance_pp": 0.5}
    if "long_real" in inputs and "SP500" in real_frame:
        sr = _series(inputs["long_real"], "SHILLER_REAL_TR_PRICE")
        dec = sr[sr.index.month == 12]
        dec.index = dec.index.year
        sh = (dec / dec.shift(1) - 1).dropna()
        j = pd.concat([real_frame["SP500"], sh], axis=1, join="inner").dropna()
        if len(j) >= 5:
            same_sign = float((j.iloc[:, 0] * j.iloc[:, 1] > 0).mean())
            validation["cross_check_real"] = {
                "status": "pass" if same_sign >= 0.8 else "fail", "against": inputs["long_real"].dataset_id,
                "years": int(len(j)), "same_direction_share": same_sign,
                "correlation": float(j.iloc[:, 0].corr(j.iloc[:, 1])), "threshold": 0.8,
                "note": "Damodaran 标普 500 实际回报与 Shiller 实际总收益（12 月平均到 12 月平均）的方向一致比例；"
                        "口径不同（年末与月均、CPI 取法），只核对方向"}

    coverage = {"requested_start": start.date().isoformat(), "requested_end": end.date().isoformat(),
                "first_year": first_year, "last_year": last_year, "years": int(len(years)), "assets": assets,
                "real_years": real.get("SP500", {}).get("years", 0)}
    tables = {
        "annual_returns": [{"year": int(y), **{a: float(v) for a, v in row.items()}} for y, row in years[assets].iterrows()],
        "wealth_index": [{"year": int(y), **{a: float(v) for a, v in row.items()}}
                         for y, row in (1 + years[assets]).cumprod().iterrows()],
    }
    if rolling:
        roll_all = (1 + years["SP500"]).rolling(window).apply(np.prod, raw=True) ** (1 / window) - 1
        tables["rolling"] = [{"end_year": int(y), "SP500": float(v)} for y, v in roll_all.dropna().items()]

    return ResearchResult(
        study_id=study.study_id,
        title=study.title,
        question=study.question,
        result_type=study.result_type,
        branch=study.branch,
        scope=study.scope,
        data_cutoff=f"{last_year}-12-31",
        methods={
            "description": "年度回报的算术平均、几何平均（期末财富的年化）、波动率（标准差）、最差年份、亏损年数与最大回撤；"
                           "实际回报 = (1 + 名义) / (1 + 当年 CPI 通胀) − 1；股票风险溢价为几何平均之差；相关系数按全期与"
                           "事先固定的时期计算。只用所有资产都有值的完整年度；只描述历史，不估计模型。",
            "benchmark": "3 个月国库券（风险溢价的基准）",
            "parameters": m,
            "availability_rule": inputs["annual"].version.quality.get("availability_rule"),
        },
        inputs=[input_record(i) for i in inputs.values()],
        results={"first_year": first_year, "last_year": last_year, "assets": assets, "nominal": nominal, "real": real,
                 "inflation": inflation, "equity_risk_premium": erp, "correlations": correlations,
                 "period_sensitivity": sensitivity, "rolling": rolling, "monthly_equity": monthly},
        coverage=coverage,
        unsupported=unsupported,
        limitations=limitations,
        validation=validation,
        tables=tables,
    )
