"""Content targets and availability checks. No research calculation or inferred capability."""
from __future__ import annotations
from typing import Any

# Explicit result paths, not titles or translated strings. Missing optional outputs stay unavailable.
PATHS = {
    'curve': ('results', 'levels'), 'attribution': ('results', 'long_end'),
    'bond-scenarios': ('results', 'scenarios'), 'asset-returns': ('results', 'nominal'),
    'asset-correlations': ('results', 'correlations', 'full', 'matrix'),
    'asset-excess': ('results', 'equity_risk_premium'),
    'industry-market': ('results', 'summary'), 'industry-stress': ('tables', 'stress'),
    'industry-factors': ('tables', 'regressions'), 'industry-regimes': ('tables', 'regimes'),
    'industry-lags': ('tables', 'lag_correlations'), 'industry-background': ('results', 'characteristics'),
    'industry-economy': ('results', 'economy'), 'industry-financials': ('tables', 'fundamentals'),
    'industry-valuation': ('tables', 'valuation'), 'industry-guidance': ('tables', 'guidance'),
    'refining-statistics': ('results', 'statistics'), 'refining-scenarios': ('results', 'scenarios'),
    'refining-association': ('results', 'utilization_crack', 'pearson'),
    'refining-spread': ('results', 'crack_spread'), 'refining-tsr': ('tables', 'annual_tsr'),
    'company-overview': ('results', 'companies'), 'company-annual': ('tables', 'annual'),
    'company-comparability': ('results', 'companies'), 'evidence': ('validation',),
    'chip-segments': ('tables',), 'chip-feasibility': ('results', 'feasibility'),
}
REPORT_TARGETS = {'chip-segments', 'chip-feasibility'}


def available(result: dict[str, Any], target: str, subject: str | None = None) -> bool:
    value: Any = result
    for key in PATHS[target]:
        value = value.get(key) if isinstance(value, dict) else None
    if target == 'asset-returns':
        assets = {'equity': ['SP500', 'SMALLCAP'], 'rates': ['TBOND10Y', 'TBILL3M'],
                  'credit': ['BAA'], 'property': ['REALESTATE'], 'commodities': ['GOLD']}.get(subject, list(value or {}))
        return any((value or {}).get(k, {}).get('years', 0) > 0 for k in assets)
    if target == 'asset-correlations':
        assets = {'equity': ['SP500', 'SMALLCAP'], 'rates': ['TBOND10Y', 'TBILL3M'],
                  'credit': ['BAA'], 'property': ['REALESTATE'], 'commodities': ['GOLD']}.get(subject, list(value or {}))
        return any(any(other != asset and number is not None for other, number in (value or {}).get(asset, {}).items()) for asset in assets)
    metrics = {'industry-market': 'cagr', 'industry-stress': 'total_return',
               'industry-lags': 'correlation', 'industry-regimes': 'monthly_mean_times_12',
               'industry-economy': 'end_value', 'industry-guidance': 'value'}
    if target in metrics:
        return any(x.get(metrics[target]) is not None for x in value or [])
    if target == 'chip-segments':
        return any(rows for key, rows in (value or {}).items() if key.endswith('segment_financials'))
    if target == 'refining-scenarios':
        return any(x.get('grade') in ('A', 'B') and x.get('weeks_evaluated', 0) > 0 for x in value or [])
    if target == 'industry-valuation':
        return any(x.get('metric') == 'trailing_pe' and x.get('value') is not None for x in value or [])
    if target == 'industry-background':
        return any(x.get('metric') == 'bm' and x.get('value') is not None for x in value or [])
    if target == 'industry-factors':
        return any(x.get('status') == 'ok' for x in value or [])
    if target == 'company-annual' and len(result.get('results', {}).get('companies', [])) != 1:
        return False
    if isinstance(value, (int, float)):
        return True  # zero is an observation, not missing
    return bool(value)
