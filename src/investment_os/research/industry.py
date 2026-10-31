"""Four-layer descriptive industry research. No investment or causal claims."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from ..analytics.industry import bh_adjust, complete_returns, hac_ols, lag_correlations, quarterly_returns, stats
from ..contracts import ResultType
from ..quality import ok_rows
from .base import ResearchResult, input_record, register_branch


def wide(inp, freq="M"):
    f = ok_rows(inp.frame)
    w = f.pivot(index="observation_at", columns="series_id", values="value").sort_index()
    w.index = w.index.to_period(freq)
    w.columns = [inp.version.series.get(c, {}).get("column", c) for c in w.columns]
    return w


def bundle_records(inp):
    meta = inp.version.series
    fingerprint = meta["_bundle"]["hash"]
    values = ok_rows(inp.frame).set_index("series_id").value.to_dict()
    return [{**v, "value": float(values[k])} for k, v in meta.items()
            if k in values and v.get("bundle_hash") == fingerprint]


def aggregate_fundamentals(records, start=2010, end=2025, membership=None):
    """Matched denominators and matched prior-year samples; do not sum missing as zero."""
    f = pd.DataFrame(records)
    f["year"] = f.fiscal_end.str[:4].astype(int)
    # Fiscal-year changes can create two annual ends in a calendar year. Keep the
    # later end but count those company-years; never double count one issuer.
    ends = f[["cik", "year", "fiscal_end"]].drop_duplicates()
    multiple = int(ends.duplicated(["cik", "year"]).sum())
    latest = ends.groupby(["cik", "year"]).fiscal_end.max().reset_index()
    f = f.merge(latest, on=["cik", "year", "fiscal_end"], validate="many_to_one")
    p = f.pivot(index=["topic", "year", "cik"], columns="metric", values="value")
    if membership:
        eligible = pd.DataFrame(membership)
        eligible["year"] = eligible.period.str[:4].astype(int)
        eligible["cik"] = eligible.cik.astype(int)
        eligible = eligible.sort_values("period").drop_duplicates(["cik", "year"], keep="last")
        p = p.reindex(pd.MultiIndex.from_frame(eligible[["topic", "year", "cik"]])).sort_index()
    rows = []
    metrics = sorted(set(f.metric))
    ratios = {"net_margin": ("net_income", "revenue"), "operating_margin": ("operating_income", "revenue"),
              "cash_conversion": ("operating_cash_flow", "net_income"), "capex_to_sales": ("capex", "revenue"),
              "repurchases_to_sales": ("repurchases", "revenue"), "dividends_to_sales": ("dividends", "revenue")}
    for topic in sorted(set(p.index.get_level_values("topic"))):
        table = p.loc[topic]
        for year in range(start, end+1):
            if year not in table.index.get_level_values("year"):
                continue
            current = table.loc[year]
            previous = table.loc[year-1] if year-1 in table.index.get_level_values("year") else current.iloc[:0]
            c, prev = set(current.index), set(previous.index)
            record = {"topic": topic, "year": year, "companies": len(c),
                      "entrants": len(c-prev), "exits": len(prev-c), "continuing": len(c&prev),
                      "metrics": {}, "ratios": {}}
            for metric in metrics:
                s = current[metric].dropna()
                common = pd.concat([current[metric], previous[metric].rename(metric+"_prior")], axis=1, join="inner").dropna()
                prior_sum = common[metric+"_prior"].sum()
                growth = float(common[metric].sum()/prior_sum-1) if len(common) and prior_sum>0 else None
                record["metrics"][metric] = {"count": len(s), "missing": len(c)-len(s),
                                              "sum": float(s.sum()) if len(s) else None,
                                              "matched_count": len(common), "matched_growth": growth}
            for name, (num, den) in ratios.items():
                if num not in current or den not in current:
                    continue
                both = current[[num, den]].dropna()
                denominator = float(both[den].sum())
                record["ratios"][name] = {"count": len(both), "denominator": denominator,
                                          "value": float(both[num].sum()/denominator) if len(both) and denominator>0 else None}
            if {"operating_cash_flow", "capex"} <= set(current.columns):
                pair = current[["operating_cash_flow", "capex"]].dropna()
                record["free_cash_flow"] = {"count": len(pair), "sum": float((pair.iloc[:, 0]-pair.iloc[:, 1]).sum()) if len(pair) else None}
            # This is concentration of the sampled issuers' reported revenue,
            # explicitly not stock index weights or US industry market share.
            sales = current.revenue.dropna()
            record["sample_top5_revenue_share"] = float(sales.nlargest(5).sum()/sales.sum()) if len(sales) and sales.ge(0).all() and sales.sum()>0 else None
            rows.append(record)
    return rows, {"selected_companies": int(p.index.get_level_values("cik").nunique()), "companies_with_facts": int(f.cik.nunique()), "facts": len(f),
                  "fiscal_year_changes": multiple, "first": int(f.year.min()), "last": int(f.year.max()),
                  "amended_values": int((f.value != f.first_value).sum())}


def guidance_cases(records):
    """Only compare an actual announced later, for the exact same target and basis."""
    rows = []
    by_id = {r["id"]: r for r in records if "id" in r}
    for r in records:
        if not r.get("forecast_date") or not r.get("actual_date"):
            raise ValueError("Guidance requires both announcement dates")
        if pd.Timestamp(r["forecast_date"]) >= pd.Timestamp(r["actual_date"]):
            raise ValueError("Guidance must predate results")
        if r["forecast_target"] != r["actual_target"] or r["forecast_basis"] != r["actual_basis"]:
            raise ValueError("Guidance target/basis mismatch")
        lo, hi, actual = r["low"], r["high"], r["value"]
        if lo > hi or lo <= 0:
            raise ValueError("Invalid revenue guidance range")
        midpoint = (lo+hi)/2
        revision = None
        if r.get("revises"):
            prior = by_id.get(r["revises"])
            if prior is None or any(prior[k] != r[k] for k in ("company", "forecast_target", "forecast_basis")) or prior["forecast_date"] >= r["forecast_date"]:
                raise ValueError("Invalid guidance revision link")
            revision = midpoint/((prior["low"]+prior["high"])/2)-1
        rows.append({**r, "midpoint": midpoint, "vs_midpoint": actual/midpoint-1, "revision_midpoint_change": revision,
                     "outcome": "above_range" if actual>hi else "below_range" if actual<lo else "within_range"})
    return rows


def _economy(inputs, market, mappings):
    rows, correlations, paths = [], [], []
    for topic, mapping in mappings.items():
        for measure, series in mapping.get("economy", {}).items():
            role = "econ_"+series.lower()
            if role not in inputs:
                continue
            f = ok_rows(inputs[role].frame).set_index("observation_at").value.sort_index()
            monthly = inputs[role].frame.frequency.iloc[0] == "monthly"
            f.index = f.index.to_period("M" if monthly else "Q")
            if monthly:
                cal = f.reindex(pd.period_range("2005-01", "2025-12", freq="M"))
                q = cal.groupby(cal.index.asfreq("Q")).apply(lambda s: float(s.mean()) if len(s)==3 and s.notna().all() else np.nan)
            else:
                q = f.reindex(pd.period_range("2005Q1", "2025Q4", freq="Q"))
            # Common 2006Q2 boundary includes the all-employee hours/wages series.
            start, end = pd.Period("2006Q2"), pd.Period("2025Q4")
            initial, final = q.get(start), q.get(end)
            valid = pd.notna(initial) and pd.notna(final) and initial>0
            rows.append({"topic": topic, "measure": measure, "series": series,
                         "first": str(start), "last": str(end), "start_value": float(initial) if pd.notna(initial) else None,
                         "end_value": float(final) if pd.notna(final) else None,
                         "change": float(final/initial-1) if valid else None,
                         "cagr": float((final/initial)**(4/(end.ordinal-start.ordinal))-1) if valid else None,
                         "quarters": int(q.notna().sum()), "missing_quarters": int(q.isna().sum()),
                         "correspondence": mapping["correspondence"], "mapping_note": mapping["reason"]})
            for date, value in q.dropna().items():
                paths.append({"topic": topic, "measure": measure, "quarter": str(date), "value": float(value)})
            sector = mapping["market12"]
            if measure in ("rva", "output") and sector in market:
                r = quarterly_returns(market[sector])
                for left, right in (("2005Q1", "2025Q4"), ("2005Q1", "2014Q4"), ("2015Q1", "2025Q4")):
                    for item in lag_correlations(r, q, left, right):
                        correlations.append({"topic": topic, "series": series, "sector": sector,
                                             "period": f"{left}–{right}", **item})
    return rows, correlations, paths


def macro_regimes(inputs, raw, cpi):
    """Ex-post descriptive conditioning, never a tradable historical signal."""
    index = pd.period_range("2001-01", "2025-12", freq="M")
    state = pd.DataFrame(index=index)
    if "recession" in inputs:
        recession = wide(inputs["recession"]).iloc[:,0].reindex(index)
        state["recession"] = recession.map({0:"expansion",1:"recession"})
    inflation = cpi.reindex(pd.period_range("1999-01", "2025-12",freq="M")).pct_change(12,fill_method=None)
    change = inflation.diff()
    state["inflation"] = change.reindex(index).map(lambda x: None if pd.isna(x) or x==0 else "rising" if x>0 else "falling")
    if "policy_rate" in inputs:
        f = ok_rows(inputs["policy_rate"].frame).set_index("observation_at").value
        month = f.groupby(f.index.to_period("M")).agg(["mean","count"])
        rate = month["mean"].where(month["count"]>=20).reindex(pd.period_range("2000-01","2025-12",freq="M"))
        change = rate.diff(6)
        state["policy_rate"] = change.reindex(index).map(lambda x: None if pd.isna(x) or abs(x)<.25 else "rising" if x>0 else "falling")
    rows=[]
    for variable in state:
        for label in sorted(state[variable].dropna().unique()):
            for sector in raw:
                s=raw[sector].reindex(index)[state[variable].eq(label)].dropna()
                if len(s)>=24:
                    rows.append({"variable":variable,"regime":label,"sector":sector,"months":len(s),
                                 "monthly_mean_times_12":float(s.mean()*12),"monthly_std_times_sqrt12":float(s.std()*np.sqrt(12))})
    return rows


@register_branch("industry", result_types=(ResultType.DESCRIPTIVE,))
def run(study, inputs, registry):
    m = study.method
    raw = wide(inputs["returns"])/100
    ff3 = wide(inputs["ff3"])/100
    market = ff3["Mkt-RF"]+ff3["RF"]
    ff5, mom = wide(inputs["ff5"])/100, wide(inputs["momentum"])/100
    cpi = wide(inputs["cpi"]).iloc[:, 0]
    windows = m["windows"]
    summaries, regressions, rolling, corr, wealth = [], [], [], [], []
    failures, unsupported = [], []
    for label, start, end in windows:
        for sector in [*raw.columns, "Market"]:
            series = market if sector == "Market" else raw[sector]
            s = complete_returns(series, start, end)
            if s is None:
                summaries.append({"window": label, "sector": sector, "status": "incomplete",
                                  "valid_months": int(series.reindex(pd.period_range(start, end, freq="M")).notna().sum())})
                continue
            item = {"window": label, "sector": sector, "status": "ok", **stats(s, market)}
            first_cpi, last_cpi = cpi.get(s.index[0]-1), cpi.get(s.index[-1])
            item["real_cagr"] = float((((1+s).prod())/(last_cpi/first_cpi))**(12/len(s))-1) if pd.notna(first_cpi) and pd.notna(last_cpi) and first_cpi>0 else None
            item["real_method"] = "CPI endpoint deflation; missing interior CPI months do not affect endpoint CAGR; no interpolated real monthly risk"
            summaries.append(item)
            if label == "2001–2025":
                w = (1+s).cumprod()
                wealth.extend({"sector": sector, "month": str(t), "wealth": float(v)} for t, v in w.items() if t.month==12)
        # Only complete-window sectors participate, explicitly identified.
        idx = pd.period_range(start, end, freq="M")
        w = raw.reindex(idx).dropna(axis=1)
        if not w.empty:
            c = w.corr()
            corr.extend({"window": label, "a": a, "b": b, "correlation": float(c.loc[a,b])} for a in c for b in c)

    for label, start, end in windows[1:]:
        for model, factors, rf in (("CAPM", ff3[["Mkt-RF"]], ff3.RF),
                                  ("FF3", ff3[["Mkt-RF", "SMB", "HML"]], ff3.RF),
                                  ("FF5+MOM", ff5[["Mkt-RF", "SMB", "HML", "RMW", "CMA"]].join(mom), ff5.RF)):
            family = []
            for sector in raw:
                y = (raw[sector]-rf).loc[start:end]
                fit = hac_ols(y, factors.loc[start:end], lags=6)
                row = {"window": label, "sector": sector, "model": model, **fit}
                regressions.append(row)
                if fit["status"] == "ok":
                    family.append(row)
            qvalues = bh_adjust([r["coefficients"]["alpha"]["p_normal"] for r in family])
            for r, q in zip(family, qvalues):
                r["alpha_bh_q"] = q
                r["alpha_annual_arithmetic"] = r["coefficients"]["alpha"]["estimate"]*12
    for sector in raw:
        s = raw[sector].reindex(pd.period_range(raw.index.min(), "2025-12", freq="M"))
        for years in (5, 10, 20):
            for year in range(s.index[0].year+years, 2026):
                x = complete_returns(s, f"{year-years+1}-01", f"{year}-12")
                if x is not None:
                    rolling.append({"sector": sector, "years": years, "end_year": year,
                                    "cagr": float((1+x).prod()**(1/years)-1)})
    # Rolling factor exposure, fixed 10-year windows ending every fifth year.
    rolling_exposure = []
    for year in (1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025):
        for sector in raw:
            start, end = f"{year-9}-01", f"{year}-12"
            fit = hac_ols((raw[sector]-ff5.RF).loc[start:end], ff5[["Mkt-RF", "SMB", "HML", "RMW", "CMA"]].join(mom).loc[start:end])
            if fit["status"] == "ok":
                rolling_exposure.append({"sector": sector, "end_year": year, **fit})

    characteristics = []
    for role in ("firms", "size", "bm"):
        w = wide(inputs[role], "Y" if role=="bm" else "M")
        target = pd.Period("2025", freq="Y") if role=="bm" else pd.Period("2025-12", freq="M")
        for sector in raw:
            s = w[sector].loc[:target].dropna()
            if len(s):
                characteristics.append({"sector": sector, "metric": role, "period": str(s.index[-1]), "value": float(s.iloc[-1])})
    ew = wide(inputs["equal_weight"])/100
    weight_effect = []
    for sector in raw:
        a, b = complete_returns(raw[sector], "2001-01", "2025-12"), complete_returns(ew[sector], "2001-01", "2025-12")
        if a is not None and b is not None:
            weight_effect.append({"sector": sector, "vw_cagr": stats(a)["cagr"], "ew_cagr": stats(b)["cagr"],
                                  "difference": stats(b)["cagr"]-stats(a)["cagr"]})
    # Independent published annual table checks the monthly compounding/units.
    annual = wide(inputs["annual_check"], "Y")
    max_diff, checked, rounding_failures = 0., 0, []
    for sector in raw:
        for year in range(1927, 2026):
            s = complete_returns(raw[sector], f"{year}-01", f"{year}-12")
            expected = annual[sector].get(pd.Period(year, freq="Y"))
            if s is not None and pd.notna(expected):
                calculated = ((1+s).prod()-1)*100
                # Each monthly return and the published annual return are rounded
                # to .01 percentage point. Propagate those input intervals rather
                # than imposing one fixed absolute tolerance on compound returns.
                lower = ((1+s-.00005).prod()-1)*100-.005
                upper = ((1+s+.00005).prod()-1)*100+.005
                max_diff = max(max_diff, abs(calculated-expected)); checked += 1
                if not lower-1e-9 <= expected <= upper+1e-9:
                    rounding_failures.append({"sector":sector,"year":year,"published":float(expected),"lower":float(lower),"upper":float(upper)})
    if checked == 0 or rounding_failures:
        failures.append("Published annual vs compounded monthly returns differ beyond rounding")
    economy, lagged, economy_paths = _economy(inputs, raw, m.get("topics", {}))
    commodity=[]
    if "oil_price" in inputs:
        oil=ok_rows(inputs["oil_price"].frame).set_index("observation_at").value
        for year in (2014,2015,2016,2019,2020,2021,2022,2025):
            s=oil[oil.index.year==year]
            if len(s)>=200:
                commodity.append({"year":year,"observations":len(s),"mean_usd_per_barrel":float(s.mean()),"minimum":float(s.min())})
    regimes = macro_regimes(inputs, raw, cpi)
    stress=[]
    for label,start,end in (("Dotcom","2000-01","2002-12"),("GFC","2007-10","2009-02"),("Oil slump","2014-07","2016-01"),("COVID","2020-02","2020-03"),("Inflation 2022","2022-01","2022-12")):
        for sector in raw:
            s=complete_returns(raw[sector],start,end)
            if s is not None:
                stress.append({"episode":label,"first":start,"last":end,"sector":sector,"total_return":float((1+s).prod()-1)})
    fundamental, fundamental_coverage, guidance, valuation = [], {}, [], []
    if "fundamentals" in inputs:
        fundamental, fundamental_coverage = aggregate_fundamentals(bundle_records(inputs["fundamentals"]),
            membership=inputs["fundamentals"].version.series["_bundle"].get("membership"))
    if "guidance" in inputs:
        guidance = guidance_cases(bundle_records(inputs["guidance"]))
    if "valuation" in inputs:
        selected = {"Semiconductor", "Software (System & Application)", "Oil/Gas (Integrated)",
                    "Oil/Gas (Production and Exploration)", "Retail (General)", "Retail (Grocery and Food)"}
        valuation = [r for r in bundle_records(inputs["valuation"]) if r["industry"] in selected
                     and r["snapshot_year"] in (2015, 2020, 2025, 2026)
                     and r["metric"] in ("trailing_pe", "net_margin")]
    # Current partial year is a separate YTD observation, never a full-year rank.
    updates = []
    for sector in raw:
        ytd = raw[sector].loc["2026-01":].dropna()
        if len(ytd) and ytd.index[0] == pd.Period("2026-01", freq="M") and len(ytd)<12:
            s = complete_returns(ytd, "2026-01", str(ytd.index[-1]))
            if s is not None:
                updates.append({"sector": sector, "through": str(s.index[-1]), "months": len(s), "total_return": float((1+s).prod()-1)})
    if failures:
        raise ValueError("; ".join(failures))
    unsupported = [
        {"item": "精确的行业盈利—估值回报分解", "kind": "scope", "reason": "缺少对应各期 CRSP 成分、权重、价格与公司行动；BE/ME 只作估值背景"},
        {"item": "历史一致预期与公告日超额回报", "kind": "scope", "reason": "只有选定管理层指引案例和月度收益；不能替代分析师一致预期或日度事件研究"},
        {"item": "因果关系", "kind": "scope", "reason": "因子暴露、同步和领先滞后相关均为事后描述；宏观数据为当前修订版本"},
    ]
    tables = {"regressions": regressions, "rolling": rolling, "rolling_exposure": rolling_exposure,
              "correlations": corr, "wealth": wealth, "lag_correlations": lagged,
              "economy_paths": economy_paths, "fundamentals": fundamental,
              "guidance": guidance, "valuation": valuation, "regimes": regimes, "stress": stress}
    # Archiving compares results, not arbitrary branch tables. A revised fact or
    # guidance value must trigger an archive even when all coverage counts agree.
    detail_hash = hashlib.sha256(json.dumps(tables, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    results = {"industry_count": len(raw.columns), "windows": windows, "summary": summaries,
               "detail_fingerprint": detail_hash,
               "characteristics": characteristics, "weight_effect": weight_effect,
               "economy": economy, "fundamental_coverage": fundamental_coverage,
               "guidance_companies": len({r["company"] for r in guidance}), "guidance_events": len(guidance),
               "valuation_snapshots": sorted({r["date"] for r in valuation}),
               "updates": updates, "mapping": m.get("topics", {}), "oil_price": commodity}
    return ResearchResult(study.study_id, study.title, study.question, ResultType.DESCRIPTIVE, "industry",
                          study.scope, str(raw.index.max()), m, [input_record(i) for i in inputs.values()],
                          results, {"completeness": "partial", "period_complete": True,
                                    "industries": len(raw.columns), "months": len(raw),
                                    "missing_long_windows": sum(s["status"] != "ok" for s in summaries),
                                    "fundamentals": fundamental_coverage}, unsupported, list(study.limitations),
                          {"annual_compounding": {"status": "pass", "checked": checked,
                                                  "max_abs_difference_pp": max_diff, "rounding_failures": rounding_failures,
                                                  "tolerance": "Propagated +/-0.005 percentage point per monthly and annual reported value"},
                           "guidance_timing": {"status": "pass" if guidance else "skipped", "checked": len(guidance)},
                           "calendar_integrity": {"status": "pass", "reason": "Incomplete return windows are withheld; no gap concatenation"}},
                          tables)
