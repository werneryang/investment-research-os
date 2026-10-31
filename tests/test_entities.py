"""Subject identity, evidence status and static navigation contract."""
from html.parser import HTMLParser
import json
import shutil
import subprocess

import pytest
import yaml

from investment_os.site.entities import build_index, subject_records
from investment_os.site.discovery import catalog
from investment_os.site.relationships import relationship_view
from investment_os.site.i18n import use, load_phrases
from .conftest import PROJECT_ROOT


@pytest.fixture
def inputs():
    content=yaml.safe_load((PROJECT_ROOT/'site/content.yaml').read_text())
    defs={p.stem:yaml.safe_load(p.read_text()) for p in (PROJECT_ROOT/'config/studies').glob('*.yaml')}
    return content,defs


@pytest.fixture
def index(inputs):
    return build_index(PROJECT_ROOT,*inputs)


def test_identity_and_direct_records(index):
    assert index['by_cik']['1045810']=='co_nvidia'
    assert 'cik_1045810' not in index['entities']
    assert not index['entities']['co_tsmc'].get('cik')
    assert index['study_entities']['company_nvidia']==['co_nvidia']
    assert index['study_entities']['us_industry_dossier']==[]
    nv=subject_records(index,'co_nvidia')
    assert len(nv['mappings'])==2 and len(nv['relations'])==10
    assert len(subject_records(index,'co_micron')['relations'])==8
    assert len(subject_records(index,'co_tsmc')['relations'])==1
    anon=subject_records(index,'anon_nvda_fy2026_direct_1')
    assert len(anon['relations'])==1 and anon['mappings']==[]
    assert subject_records(index,'cik_320193')=={'known':True,'relations':[],'mappings':[]}
    assert subject_records(index,'unknown')['known'] is False
    json.dumps(index)
    # Public metadata must not leak local paths or assert fresh machine checks.
    assert all(c['machine_check']=='not_rerun_in_site_build' for c in index['evidence'].values())
    assert not any('path' in c['document'] for c in index['evidence'].values())


@pytest.mark.parametrize('mutation', ['alias','cik','route','company_route'])
def test_invalid_subject_binding_fails(inputs,mutation):
    content,defs=inputs
    if mutation=='alias':content['entity_aliases']['missing']=['x']
    if mutation=='cik':content['studies']['company_nvidia']['entity_ids']=['co_micron']
    if mutation=='route':content['studies']['company_nvidia']['routes'][0]['entity_ids']=['missing']
    if mutation=='company_route':content['studies']['company_nvidia']['routes'][0]['entity_ids']=['co_micron']
    with pytest.raises(ValueError):build_index(PROJECT_ROOT,content,defs)


def test_route_bindings_do_not_create_company_valuation(index,inputs):
    content,defs=inputs
    ds={d:{} for r in content['classification']['capabilities'] for d in r.get('datasets',[])}
    model=catalog(content,{},defs,ds,True,index)
    for study in model['studies']:
        for route in study['routes']:
            if 'co_nvidia' in route['entity_ids']:
                assert route['question']!='valuation'
    company=next(r for material in model['references'] for r in material['routes'] if r['object']=='company' and r['topic']=='relationships')
    industry=next(r for material in model['references'] for r in material['routes'] if r['object']=='industry' and r['topic']=='relationships')
    assert company['entity_ids']==industry['entity_ids']
    assert 'co_tsmc' in company['entity_ids']
    assert all(not s['published'] for s in model['studies'])


def test_evidence_change_invalidates_dependents(inputs,monkeypatch):
    import investment_os.site.entities as entities
    original=entities.fingerprint
    monkeypatch.setattr(entities,'fingerprint',lambda cat,id:'changed' if id=='clm_nvda26_foundry' else original(cat,id))
    index=build_index(PROJECT_ROOT,*inputs)
    r=index['relations']['rel_tsmc_nvda_foundry']
    assert r['evidence_problem'] and r['technical']=='none'
    assert index['evidence']['clm_nvda26_foundry']['technical']=='stale'
    html=relationship_view(index,initial_entity='co_tsmc',embedded=True)
    assert '所引用证据存在失效' in html and '复核记录已失效' in html


def test_relationship_evidence_and_static_fallback(index):
    html=relationship_view(index,initial_entity='co_nvidia',embedded=True)
    assert html.count('data-relation=')==10 and html.count('data-mapping=')==2
    assert '22%' in html and '14%' in html and '总营收' in html and 'FY2026' in html
    assert '未说明是芯片封装测试还是板卡与系统组装' in html
    assert 'clm_mu25_competitors' not in html
    assert '关系有效期: 未知 — 未知' in html
    assert '未人工确认' in html and '没有重新运行原文或数值机器核验' in html
    assert 'data-relation=' in html and 'data-relation="' in html
    class Tags(HTMLParser):
        def __init__(self):super().__init__();self.ids=[];self.records=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if 'id' in a:self.ids.append(a['id'])
            if 'data-relation' in a or 'data-mapping' in a:self.records.append(a)
    parser=Tags();parser.feed(html)
    assert len(parser.ids)==len(set(parser.ids))
    assert all('hidden' not in a for a in parser.records)
    with use('en',load_phrases(PROJECT_ROOT)):
        en=relationship_view(index)
    assert '<option' in en and '<option value="anon_nvda_fy2026_direct_1">NVIDIA FY2026' in en
    assert 'Source location' in en and 'Filing accepted' in en


def test_shared_browser_predicates(index):
    """Execute the production pure predicates, including missing and invalid states."""
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable; pure browser predicates require Node')
    script=r'''
const assert=require('node:assert/strict'),S=require('./site/assets/subjects.js');
const idx=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
for(const query of ['NVDA','英伟达','nvdia'])assert.equal(S.candidates(idx.entities,query)[0].id,'co_nvidia');
assert.equal(S.candidates(idx.entities,'nvdia')[0].score,2);
const row=idx.relations.rel_micron_nvda_memory;
assert.equal(S.role(row,'co_nvidia'),'upstream');assert.equal(S.role(row,'co_micron'),'downstream');
assert(S.recordMatch(row,{entity:'co_nvidia'}));assert(!S.recordMatch(row,{entity:'unknown'}));
const union=Object.values(idx.relations).filter(r=>S.recordMatch(r,{entity:'co_nvidia',compare:'co_micron'}));
assert.equal(union.length,17);assert.equal(new Set(union.map(r=>r.id)).size,17);
assert.equal(Object.values(idx.relations).filter(r=>S.recordMatch(r,{entity:'co_nvidia',activity:'unknown'})).length,5);
assert(!S.recordMatch(row,{review:'passed'}));assert(S.recordMatch(row,{review:'none'}));
assert(!S.recordMatch({...row,technical:'passed',evidence_problem:true},{review:'passed'}));
assert(S.recordMatch({...row,human:'retracted'},{review:'problem'}));
assert(!S.recordMatch({...row,evidence_date:null},{evidence_before:'2099-01-01'}));
assert(!S.recordMatch(row,{evidence_before:'2020-01-01'}));
assert(!S.recordMatch(row,{activity:'not-registered'}));
assert.equal(idx.relations.rel_nvda_direct_1.share.denominator,'总营收');
assert.equal(idx.relations.rel_mu_top10.share.bound,'> 0.5');
assert(!S.recordMatch(row,{entity:'cik_320193'}));
'''
    subprocess.run([node,'-e',script],cwd=PROJECT_ROOT,input=json.dumps(index),text=True,check=True,capture_output=True)
