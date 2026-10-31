"""Navigation must not invent results, classification pairs or evidence status."""
from copy import deepcopy
from datetime import date
import json

import pytest
import yaml

from investment_os.site.discovery import catalog, validate, verify_targets
from investment_os.site.targets import available
from investment_os.site.references import company_reference_index, company_reference_part, reference_page_part
from .conftest import PROJECT_ROOT


@pytest.fixture
def content():
    return yaml.safe_load((PROJECT_ROOT / 'site/content.yaml').read_text())


def test_every_study_has_one_primary_paired_route(content):
    validate(content)
    ids = {p.stem for p in (PROJECT_ROOT / 'config/studies').glob('*.yaml')}
    assert len(ids) == 30 and ids == set(content['studies'])
    assert 'branches' not in content
    assert all('studies' not in d for b in content['data_groups'] for d in b['directions'])
    assert len(content['classification']['objects']) == 7
    assert len(content['classification']['questions']) == 10
    for sid, meta in content['studies'].items():
        rr = meta['routes']
        assert sum(bool(r.get('primary')) for r in rr) == 1
        assert all(r['scope']['zh'] and r['scope']['en'] for r in rr)
        assert not any(r['question'] == 'valuation' for r in rr) if sid.startswith(('company_', 'us_asset_history')) else True
    # The dossier's company route describes financial samples, never company valuation.
    rr = content['studies']['us_industry_dossier']['routes']
    assert any(r['question'] == 'valuation' for r in rr)
    assert not any(r['object'] == 'company' and r['question'] == 'valuation' for r in rr)
    assert not any(r['object'] == 'portfolio' for s in content['studies'].values() for r in s['routes'])


@pytest.mark.parametrize('field,value', [('target','made-up'), ('subject','unknown'), ('primary',False), ('scope',{'zh':'only'})])
def test_invalid_classification_fails(content, field, value):
    content['studies']['ust_curve_2024']['routes'][0][field] = value
    with pytest.raises(ValueError): validate(content)


def test_optional_outputs_and_zero_observations():
    assert not available({'tables':{'valuation':[]}}, 'industry-valuation')
    assert not available({'tables':{'valuation':[{'metric':'pb','value':2}]}}, 'industry-valuation')
    assert available({'tables':{'valuation':[{'metric':'trailing_pe','value':0}]}}, 'industry-valuation')
    assert not available({'results':{'summary':[{'status':'too_short','cagr':None}]}}, 'industry-market')
    assert not available({'tables':{'regressions':[{'status':'insufficient'}]}}, 'industry-factors')
    assert not available({'results':{'scenarios':[{'grade':'C','weeks_evaluated':0}]}}, 'refining-scenarios')
    assert available({'results':{'utilization_crack':{'pearson':0}}}, 'refining-association')
    result = {'results':{'nominal':{'SP500':{'years':20},'BAA':{'years':0}}}}
    assert available(result, 'asset-returns', 'equity')
    assert not available(result, 'asset-returns', 'credit')
    assert not available({'results':{'characteristics':[{'metric':'bm','value':None}]}}, 'industry-background')


def test_company_summary_does_not_claim_annual_target():
    result = {'results':{'companies':[{},{}]},'tables':{'annual':[{'revenue':1}]}}
    assert not available(result, 'company-annual')
    assert available(result, 'company-overview')
    result['results']['companies'].pop()
    assert available(result, 'company-annual')


def test_publication_state_and_dates_are_not_inferred(content):
    c=deepcopy(content)
    ds={d:{} for r in c['classification']['capabilities'] for d in r.get('datasets',[])}
    defs={'ust_curve_2024':{'scope':{'start':date(2024,1,1)}}}
    model=catalog(c,{},defs,ds)
    rec=next(x for x in model['studies'] if x['id']=='ust_curve_2024')
    assert rec['scope']['start']=='2024-01-01'
    assert not rec['published'] and not rec['routes'][0]['available'] and not rec['routes'][0]['href']
    assert model['references']==[]
    assert {'registered','planned'} == {x['state'] for x in model['capabilities']}
    json.dumps(model)
    for row in ds.values():row['version_id']='local'
    assert {'data','planned'} == {x['state'] for x in catalog(c,{},defs,ds)['capabilities']}


def test_content_targets_require_public_file_and_unique_id(tmp_path):
    folder=tmp_path/'studies/s';folder.mkdir(parents=True)
    records=[{'routes':[{'available':True,'report':False,'href':'studies/s/#annual'}]}]
    with pytest.raises(ValueError,match='Missing classification target'):verify_targets(tmp_path,tmp_path,records)
    (folder/'index.html').write_text('<h2 id="annual">Years</h2>')
    verify_targets(tmp_path,tmp_path,records)
    (folder/'index.html').write_text('<h2 id="annual">Years</h2><p id="annual">Duplicate</p>')
    with pytest.raises(ValueError,match='Duplicate content ID'):verify_targets(tmp_path,tmp_path,records)
    (folder/'index.html').write_text('<h2 id="different">Years</h2>')
    with pytest.raises(ValueError,match='Missing content ID'):verify_targets(tmp_path,tmp_path,records)
    records[0]['routes'][0]={'available':True,'report':True,'href':'runs/r/report.html'}
    with pytest.raises(ValueError,match='Missing classification target'):verify_targets(tmp_path,tmp_path,records)


def test_references_keep_candidates_and_stale_reviews_separate(monkeypatch):
    import investment_os.site.references as refs
    html=reference_page_part(PROJECT_ROOT)
    assert '候选公司关系' in html and '不能用于收入分摊' in html and '人工状态' in html
    assert '技术复核记录：pass' in html
    monkeypatch.setattr(refs,'fingerprint',lambda *args:'changed')
    stale=reference_page_part(PROJECT_ROOT)
    assert '复核记录已失效' in stale and '技术复核记录：pass' not in stale
    index=company_reference_index(PROJECT_ROOT)
    assert index['1045810'] and '320193' not in index
    assert '尚未收录' in company_reference_part({'branch':'company','results':{'companies':[{'cik':320193}]}},index)
    assert 'sources.html#ref-' in company_reference_part({'branch':'company','results':{'companies':[{'cik':1045810}]}},index)
    assert company_reference_part({'branch':'company','results':{'companies':[{},{}]}},index)==''


def test_collapsed_group_retains_member_failure_and_limits(content):
    from investment_os.site.discovery import browser
    ds={d:{} for r in content['classification']['capabilities'] for d in r.get('datasets',[])}
    item={'result':{'branch':'unknown','title':'Test issuer','question':'Q','result_type':'descriptive',
                    'scope':{},'data_cutoff':'2025','limitations':[],
                    'validation':{'raw_spot_check':{'status':'fail'}},'unsupported':[]},
          'manifest':{'run_id':'r','status':'complete','inputs':[]},'verification':None,'findings':[]}
    latest={'company_apple':item}
    model=catalog(content,latest,{},ds)
    html=browser(content,model,latest,{})
    section=html[html.index('id="object-company"'):]
    summary=section[:section.index('</summary>')]
    assert '1 项检查失败' in summary
    assert 'data-severity="fail"' in section and '原始快照抽查有不一致' in section
    assert section.count('<tr class="research-record"') == 15


def test_correlation_availability_checks_requested_asset():
    result={'results':{'correlations':{'full':{'matrix':{'SP500':{'SP500':1,'BAA':0.2},'BAA':{'SP500':0.2,'BAA':1}}}}}}
    assert available(result,'asset-correlations','credit')
    assert not available(result,'asset-correlations','property')
    result['results']['correlations']['full']['matrix']['REALESTATE']={'REALESTATE':1,'SP500':None}
    assert not available(result,'asset-correlations','property')
