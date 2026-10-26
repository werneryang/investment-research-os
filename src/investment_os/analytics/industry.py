"""Industry statistics with explicit calendar and denominator checks."""
from __future__ import annotations

from math import erfc, sqrt

import numpy as np
import pandas as pd


def complete_returns(s: pd.Series, start: str, end: str) -> pd.Series | None:
    index = pd.period_range(start, end, freq="M")
    values = s.reindex(index)
    if values.isna().any() or (values < -1).any():
        return None
    return values


def stats(s: pd.Series, market: pd.Series | None = None) -> dict:
    """Monthly returns, with initial wealth = 1 included in the high-water mark."""
    if s.empty or s.isna().any() or not s.index.equals(pd.period_range(s.index[0], s.index[-1], freq="M")):
        raise ValueError("Return statistics require contiguous, nonmissing months")
    wealth = np.r_[1., (1 + s).cumprod().to_numpy()]
    dd = wealth / np.maximum.accumulate(wealth) - 1
    trough = int(dd.argmin())
    peak = int(wealth[:trough + 1].argmax())
    recovered = np.flatnonzero(wealth[trough + 1:] >= wealth[peak])
    result = {"months": len(s), "first": str(s.index[0]), "last": str(s.index[-1]),
              "cagr": float(wealth[-1] ** (12 / len(s)) - 1),
              "volatility": float(s.std(ddof=1) * sqrt(12)), "max_drawdown": float(dd.min()),
              "peak": str(s.index[peak - 1]) if peak else str(s.index[0] - 1),
              "trough": str(s.index[trough - 1]) if trough else str(s.index[0] - 1),
              "recovery": str(s.index[trough + int(recovered[0])]) if len(recovered) else None,
              "worst_month": float(s.min())}
    if market is not None:
        benchmark = market.reindex(s.index)
        if benchmark.notna().all():
            active = s - benchmark
            result.update(relative_wealth=float(((1+s)/(1+benchmark)).prod() - 1),
                          tracking_error=float(active.std(ddof=1)*sqrt(12)),
                          market_correlation=float(s.corr(benchmark)))
    return result


def hac_ols(y: pd.Series, factors: pd.DataFrame, lags: int = 6) -> dict:
    """OLS with Bartlett Newey-West covariance; asymptotic normal confidence intervals.

    Complete consecutive months are required, so calendar gaps never become adjacent
    residuals. The result is descriptive exposure, not causal attribution.
    """
    d = pd.concat([y.rename("y"), factors], axis=1).dropna()
    if len(d) < max(60, 10 * (len(factors.columns)+1)):
        return {"status": "insufficient", "months": len(d)}
    if not d.index.equals(pd.period_range(d.index[0], d.index[-1], freq="M")):
        return {"status": "calendar_gap", "months": len(d)}
    x = np.column_stack([np.ones(len(d)), d[factors.columns].to_numpy()])
    a = d.y.to_numpy()
    if np.linalg.matrix_rank(x) < x.shape[1]:
        return {"status": "rank_deficient", "months": len(d)}
    b = np.linalg.lstsq(x, a, rcond=None)[0]
    residual = a-x@b
    z = x*residual[:, None]
    meat = z.T@z
    for lag in range(1, min(lags, len(d)-1)+1):
        cross = z[lag:].T@z[:-lag]
        meat += (1-lag/(lags+1))*(cross+cross.T)
    bread = np.linalg.inv(x.T@x)
    covariance = bread@meat@bread * len(d)/(len(d)-x.shape[1])
    se = np.sqrt(np.maximum(0, np.diag(covariance)))
    t = np.divide(b, se, out=np.zeros_like(b), where=se>0)
    names = ["alpha", *factors.columns]
    return {"status": "ok", "months": len(d), "first": str(d.index[0]), "last": str(d.index[-1]),
            "hac_lags": lags, "r_squared": float(1-residual@residual/((a-a.mean())@(a-a.mean()))),
            "coefficients": {n: {"estimate": float(v), "se": float(s),
                                  "ci_low": float(v-1.96*s), "ci_high": float(v+1.96*s),
                                  "p_normal": erfc(abs(float(ti))/sqrt(2))}
                             for n, v, s, ti in zip(names, b, se, t)}}


def bh_adjust(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg, within the explicitly declared family of comparisons."""
    if not pvalues:
        return []
    p = np.asarray(pvalues)
    order = np.argsort(p)
    ranked = p[order]*len(p)/np.arange(1, len(p)+1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1].clip(0, 1)
    out = np.empty(len(p)); out[order] = adjusted
    return out.tolist()


def quarterly_returns(s: pd.Series) -> pd.Series:
    full = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"))
    groups = full.groupby(full.index.asfreq("Q"))
    return groups.apply(lambda x: float((1+x).prod()-1) if len(x)==3 and x.notna().all() else np.nan)


def lag_correlations(returns: pd.Series, level: pd.Series, start: str, end: str) -> list[dict]:
    """Corr(return[t], economic growth[t+k]); k>0 means returns lead activity.

    Growth is quarter-on-quarter (not overlapping year-on-year); full calendar is
    restored before shifts. No winner selection, significance or causal claims.
    """
    index = pd.period_range(start, end, freq="Q")
    r, x = returns.reindex(index), level.reindex(index)
    growth = x.pct_change(fill_method=None)
    rows = []
    for k in range(-4, 5):
        pair = pd.concat([r, growth.shift(-k)], axis=1).dropna()
        rows.append({"lag_quarters": k, "pairs": len(pair),
                     "correlation": float(pair.iloc[:, 0].corr(pair.iloc[:, 1])) if len(pair)>=20 else None})
    return rows
