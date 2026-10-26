#!/usr/bin/env python3
"""Freeze the existing 15-company sample; no network or source mutation."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

from investment_os.data.fundamentals import EdgarStore, _combined, FACT_KEY, period_key
from investment_os.data.ingest import ingest
from investment_os.data.store import DataStore
from investment_os.registry import Registry
from investment_os.research.company import METRICS

ROOT = Path(__file__).resolve().parents[1]


def choose_tag(group, tags):
    # FSDS is extracted from face financial statements; an API-only tag may
    # describe a disclosure rather than the consolidated statement total.
    primary = group[group.source.eq('fsds')]
    pool = primary if len(primary) else group
    return next(t for t in tags if t in set(pool.full_tag))


def build(root):
    registry, store = Registry.load(root), EdgarStore(root)
    spec = registry.fundamentals
    profiles = yaml.safe_load((root/'config/company-research.yaml').read_text())["companies"]
    if {p['cik'] for p in profiles} != {c.cik for c in spec.companies}:
        raise ValueError('Company profiles must match the registered sample')
    facts, filings = _combined(store, [p['cik'] for p in profiles])
    raw_facts = store.query('facts')
    raw_facts['period_key'] = period_key(raw_facts.period_end)
    counts = raw_facts.groupby(FACT_KEY).value.nunique()
    conflicts = set(counts[counts > 1].index)
    if facts.empty:
        raise ValueError('Run the existing EDGAR sync first')
    # _combined prioritizes FSDS values. Recover the API start/end evidence, where present.
    api = store.query('facts', "source = 'companyfacts'")
    api['period_key'] = period_key(api.period_end)
    starts = api.drop_duplicates(FACT_KEY).set_index(FACT_KEY).period_start.to_dict()
    forms = filings.set_index('accession').form.to_dict()
    filed = filings.set_index('accession').filed.to_dict()
    facts = facts[facts.accession.map(forms).isin(spec.forms_annual) & facts.unit.eq('USD')
                  & facts.duration_quarters.eq(4) & facts.period_key.ge('2009-01-01')].copy()
    facts['start'] = [starts.get(tuple(r[k] for k in FACT_KEY)) for r in facts.to_dict('records')]
    tags = {m: [f'{tx}:{tg}' for tx,tg in spec.metrics[m].tags] for m in METRICS if m != 'operating_income'}
    tags['operating_income'] = ['us-gaap:OperatingIncomeLoss']
    records = []
    facts['full_tag'] = facts.taxonomy + ':' + facts.tag
    wanted = {t for ts in tags.values() for t in ts}
    annual_dates = facts[facts.full_tag.isin(wanted)].groupby(['cik', 'period_key']).size().index
    for cik, d in annual_dates:
        part = facts[(facts.cik == cik) & (facts.period_key == d)]
        for metric in METRICS:
            candidates = part[part.full_tag.isin(tags[metric])].copy()
            history = []
            for accession, group in candidates.groupby('accession'):
                tag = choose_tag(group, tags[metric])
                chosen = group[group.full_tag.eq(tag)].sort_values('available_at')
                x = chosen.iloc[-1]
                values = chosen.value.dropna().unique()
                value = float(values[0]) if len(values) == 1 else None
                start = x['start']
                duration = (x.period_end - start).days + 1 if pd.notna(start) else None
                reason = None
                if tuple(x[k] for k in FACT_KEY) in conflicts:
                    value, reason = None, 'conflicting_source_values'
                elif len(values) != 1:
                    reason = 'conflicting_or_missing_values'
                elif duration is not None and not 350 <= duration <= 380:
                    value, reason = None, 'nonannual_duration'
                elif metric == 'capex' and value < 0:
                    value, reason = None, 'negative_capex_requires_review'
                history.append({'accession': accession, 'tag': tag, 'value': value,
                    'available_at': pd.Timestamp(x.available_at).tz_convert('UTC').isoformat(), 'form': forms[accession],
                    'period_start': str(start.date()) if pd.notna(start) else None,
                    'period_end': str(x.period_end.date()), 'exact_end': bool(x.exact_end),
                    'source': x.source, 'duration_days': duration, 'reason': reason,
                    'alternatives': [{'tag': t, 'values': sorted(map(float,g.value.dropna().unique()))}
                                     for t,g in group.groupby('full_tag')],
                    'url': f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/{accession}-index.html'})
            history.sort(key=lambda x:(x['available_at'],x['accession']))
            latest = history[-1] if history else None
            same = [x for x in history if latest and x['tag']==latest['tag'] and x['value'] is not None]
            changed = len({x['value'] for x in same}) > 1
            records.append({'id': f'{cik}_{d:%Y%m%d}_{metric}', 'cik': int(cik), 'metric': metric,
                'date': str(d.date()), 'value': latest['value'] if latest else None,
                'published_at': str(pd.Timestamp(filed[latest['accession']]).date()) if latest else None,
                'history': history, 'tags_used': len({x['tag'] for x in history}),
                'same_tag_changed': changed, 'missing_reason': None if latest and latest['value'] is not None
                    else (latest['reason'] if latest else 'no_registered_annual_tag')})
    current = {}
    for p in store.partitions():
        current[(p['table'],p['source'],p['key'])] = p
    sources = [{k:p[k] for k in ('table','source','key','version_id','content_hash','created_at')}
               | {'raw':p['raw']} for p in current.values()]
    return {'schema':'industry-evidence.v1', 'unit':'USD', 'records':records,
            'metadata':{'profiles':profiles, 'snapshot': max(p['created_at'] for p in current.values()),
                        'source_partitions': sources, 'metric_tags':tags,
                        'selection_version':'company-selection.v2-primary-statement',
                        'profile_hash':hashlib.sha256((root/'config/company-research.yaml').read_bytes()).hexdigest()}}


if __name__ == '__main__':
    doc = build(ROOT)
    path = ROOT/'data/company-research/evidence.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False))
    result = ingest(Registry.load(ROOT), DataStore(ROOT), 'company_sec_facts', {'path':str(path)})
    print(result.status, result.message, 'records:',len(doc['records']))
    if result.status == 'failed':
        raise SystemExit(1)
