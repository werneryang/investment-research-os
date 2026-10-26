import json
from pathlib import Path

import pytest

from investment_os.research.company import analyze, paired_growth, ratio, select_fact
from investment_os.site.company import chart, details
from investment_os.data.ingest import ingest
from investment_os.runs import run_study, verify_run


def fact(v, accession='a', tag='Revenue', at='2025-01-01T00:00:00Z'):
    return {'value':v,'accession':accession,'tag':tag,'available_at':at,
            'form':'10-K','period_start':'2024-01-01','period_end':'2024-12-31',
            'exact_end':True,'alternatives':[],'url':'https://www.sec.gov/Archives/example','reason':None}


def records():
    return [{'id':f'{y}_{m}','cik':1,'date':f'{y}-12-31','metric':m,'value':v,'history':[fact(v)],
             'tags_used':1,'same_tag_changed':False,'missing_reason':None}
            for y,rev in ((2023,100),(2024,120))
            for m,v in [('revenue',rev),('operating_income',12),('net_income',9),('operating_cash_flow',20),('capex',5)]]


def profile(**kw):
    return {'cik':1,'label':'Example','slug':'example','comparison':'Limited peers','note':'Fiscal year',**kw}


def test_ratios_and_cash_flow_require_one_filing_and_positive_denominator():
    assert ratio(fact(10),fact(100)) == .1
    assert ratio(fact(10,'b'),fact(100)) is None
    assert ratio(fact(10),fact(0)) is None
    assert ratio(fact(10),fact(-1)) is None
    r,s=analyze(records(),[profile()])
    assert r[-1]['free_cash_flow']==15
    assert r[-1]['operating_margin']==.1
    data=records();data[-1]['history'][0]['accession']='b'
    r,_=analyze(data,[profile()]);assert r[-1]['free_cash_flow'] is None


def test_missing_is_not_zero_and_financial_cash_ratios_are_suppressed():
    data=[r for r in records() if r['metric']!='capex']
    r,s=analyze(data,[profile(financial=True)])
    assert s[0]['missing']==2
    assert r[-1]['operating_cash_flow']==20
    assert r[-1]['capex'] is None and r[-1]['free_cash_flow'] is None
    assert r[-1]['operating_margin'] is None
    assert r[-1]['cash_margin'] is None


def test_growth_uses_same_tag_same_filing_comparatives_not_unpaired_latest():
    a=[fact(120,'old'),fact(150,'new',at='2026-01-01T00:00:00Z')]
    b=[fact(100,'old'),fact(125,'new',at='2026-01-01T00:00:00Z')]
    assert paired_growth(a,b)['value']==pytest.approx(.2)
    assert paired_growth(a,b)['accession']=='new'
    assert paired_growth(a,[fact(100,'old',tag='Other')]) is None
    assert paired_growth(a,[fact(0,'old')]) is None
    assert select_fact(a)['value']==150


def test_missing_year_not_reported_as_yoy_or_continuous_chart():
    data=records()
    for r in data:
        if r['date']=='2024-12-31':r['date']='2025-12-31'
    rows,s=analyze(data,[profile()])
    assert rows[-1]['growth']=={}
    assert s[0]['missing_end_years']==[2024]
    assert 'L690' not in chart(rows,['revenue'])


def test_duplicate_period_metric_fails_closed():
    data=records()
    with pytest.raises(ValueError,match='Duplicate'):analyze(data+[data[0]],[profile()])


def test_pinned_company_run_reproduces_and_provenance_changes_fingerprint(project,registry,store):
    doc={'schema':'industry-evidence.v1','unit':'USD','records':records(),
         'metadata':{'profiles':[profile()],'snapshot':'2026-10-24','source_partitions':[]}}
    path=project/'facts.json';path.write_text(json.dumps(doc))
    assert ingest(registry,store,'company_sec_facts',{'path':str(path)}).status=='created'
    import yaml
    cfg=yaml.safe_load((project/'config/studies/company_apple.yaml').read_text())
    cfg['method']['cik']=1
    study=project/'config/studies/company_apple.yaml';study.write_text(yaml.safe_dump(cfg))
    manifest=run_study(project,study)
    assert manifest['status']=='partial'
    verification=verify_run(project,manifest['run_id'])
    assert verification['reproduced']
    result=json.loads((project/'runs'/manifest['run_id']/'result.json').read_text())
    html=details(result)
    assert '申报版本' in html
    assert 'https://www.sec.gov/Archives/example' in html
    original=result['results']['detail_fingerprint']
    doc['records'][0]['history'][0]['url']='https://www.sec.gov/Archives/changed'
    path.write_text(json.dumps(doc))
    assert ingest(registry,store,'company_sec_facts',{'path':str(path)}).status=='created'
    manifest=run_study(project,study)
    result=json.loads((project/'runs'/manifest['run_id']/'result.json').read_text())
    assert result['results']['detail_fingerprint']!=original


def test_primary_statement_tag_wins_over_api_disclosure():
    import runpy
    import pandas as pd
    choose = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/prepare_company_research.py'))['choose_tag']
    group = pd.DataFrame([{'source':'companyfacts','full_tag':'us-gaap:Revenues'},
                          {'source':'fsds','full_tag':'us-gaap:SalesRevenueNet'}])
    assert choose(group,['us-gaap:Revenues','us-gaap:SalesRevenueNet']) == 'us-gaap:SalesRevenueNet'
    group.loc[1,'source']='companyfacts'
    assert choose(group,['us-gaap:Revenues','us-gaap:SalesRevenueNet']) == 'us-gaap:Revenues'
