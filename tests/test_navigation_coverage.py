"""Reader-task acceptance tests, independent of the configured routes under test."""
from copy import deepcopy
import json
import shutil
import subprocess

import pytest
import yaml

from investment_os.site.discovery import catalog, validate, browser, verify_targets
from investment_os.site.entities import build_index
from investment_os.site.i18n import use, load_phrases
from investment_os.site.navigation_coverage import reference_catalog
from investment_os.site.references import reference_page_part
from .conftest import PROJECT_ROOT


@pytest.fixture
def navigation():
    content=yaml.safe_load((PROJECT_ROOT/'site/content.yaml').read_text())
    definitions={p.stem:yaml.safe_load(p.read_text()) for p in (PROJECT_ROOT/'config/studies').glob('*.yaml')}
    index=build_index(PROJECT_ROOT,content,definitions)
    ds={d:{} for r in content['classification']['capabilities'] for d in r.get('datasets',[])}
    return content,index,catalog(content,{},definitions,ds,True,index)


def test_all_study_families_keep_their_reader_paths(navigation):
    """Audit the 30 definitions against the reviewed research map, not against titles."""
    content,_,_=navigation
    expected={}
    def add(ids,obj,subject,question,topic,target):
        for sid in ids:expected.setdefault(sid,set()).add((obj,subject,question,topic,target))
    add(['ust_curve_2024','ust_curve_last_year'],'assets','rates','prices','curve','curve')
    add(['ust_curve_attribution_2024','ust_curve_attribution_last_year'],'assets','rates','attribution','accounting','attribution')
    add(['ust_par_bond_rate_risk'],'assets','rates','scenario','rates','bond-scenarios')
    for subject in ['multi','equity','rates','credit','property','commodities']:
        for topic,target in [('history','asset-returns'),('risk','asset-returns'),('correlation','asset-correlations')]:
            add(['us_asset_history','us_asset_history_last_25y'],'assets',subject,'returns',topic,target)
    for subject in ['multi','equity']:
        add(['us_asset_history','us_asset_history_last_25y'],'assets',subject,'returns','excess','asset-excess')
    industry=['us_industry_12','us_industry_49','us_industry_dossier']
    for question,topic,target in [('returns','history','industry-market'),('returns','risk','industry-market'),
                                 ('returns','stress','industry-stress'),('exposure','factors','industry-factors'),
                                 ('exposure','regimes','industry-regimes'),('exposure','lags','industry-lags'),
                                 ('valuation','background','industry-background'),('fundamentals','output','industry-economy')]:
        add(industry,'industry','portfolios',question,topic,target)
    for question,topic,target in [('fundamentals','financials','industry-financials'),('valuation','multiples','industry-valuation'),('fundamentals','guidance','industry-guidance')]:
        add(['us_industry_dossier'],'industry','portfolios',question,topic,target)
    add(['us_industry_dossier'],'company','issuer','fundamentals','financials','industry-financials')
    add(['us_refining_utilization_2025'],'industry','refining','fundamentals','capacity','refining-statistics')
    add(['us_refining_utilization_2025'],'industry','refining','data','coverage','evidence')
    add(['us_refining_throughput_scenarios_2025'],'industry','refining','scenario','capacity','refining-scenarios')
    add(['us_refining_investment_2016_2025'],'industry','refining','exposure','association','refining-association')
    add(['us_refining_investment_2016_2025'],'industry','refining','prices','spread','refining-spread')
    add(['us_refining_investment_2016_2025'],'security','stock','returns','excess','refining-tsr')
    add(['chip_operations_p3b'],'industry','chips','fundamentals','segments','chip-segments')
    add(['chip_operations_p3b'],'company','issuer','fundamentals','segments','chip-segments')
    add(['chip_operations_p3b'],'industry','chips','data','feasibility','chip-feasibility')
    companies=yaml.safe_load((PROJECT_ROOT/'config/company-research.yaml').read_text())['companies']
    for sid in ['company_sample', *['company_'+c['slug'] for c in companies]]:
        add([sid],'company','issuer','fundamentals','financials','company-overview' if sid=='company_sample' else 'company-annual')
        add([sid],'company','issuer','data','comparability','company-comparability')
    assert set(expected)==set(content['studies'])
    for sid,routes in expected.items():
        assert routes=={tuple(r[k] for k in ('object','subject','question','topic','target')) for r in content['studies'][sid]['routes']},sid


def test_data_and_planning_paths_are_preserved(navigation):
    _,_,model=navigation
    expected={
        ('macro','inflation','fundamentals','economy'):({'fred_cpiaucsl'},'registered'),
        ('macro','policy','fundamentals','economy'):({'fred_dff','fred_sofr'},'registered'),
        ('macro','growth','fundamentals','economy'):({'fred_gdp','fred_payems','fred_unrate'},'registered'),
        ('assets','credit','prices','spread'):({'fred_baa10y','fred_aaa10y'},'registered'),
        ('assets','equity','prices','levels'):({'fred_vixcls'},'registered'),
        ('assets','multi','returns','history'):({'french_europe3'},'registered'),
        ('fund','product','fundamentals','fees'):(set(),'planned'),
        ('fund','product','structure','holdings'):(set(),'planned'),
        ('security','bond','returns','history'):(set(),'planned'),
        ('fund','bond_fund','returns','history'):(set(),'planned'),
    }
    actual={tuple(r[k] for k in ('object','subject','question','topic')):(set(m['datasets']),m['state'])
            for m in model['capabilities'] for r in m['routes']}
    assert actual==expected


def test_public_materials_cover_the_reader_paths_and_records(navigation):
    _,index,model=navigation
    expected={
        ('industry','chips','structure','composition'):{'activities','mappings'},
        ('company','issuer','structure','composition'):{'mappings'},
        ('industry','chips','structure','relationships'):{'relations'},
        ('company','issuer','structure','relationships'):{'relations'},
    }
    actual={}
    for material in model['references']:
        for r in material['routes']:
            actual.setdefault(tuple(r[k] for k in ('object','subject','question','topic')),set()).add(material['source'])
    assert actual==expected
    for source in ('activities','mappings','relations'):
        assert {rid for m in model['references'] if m['source']==source for rid in m['record_ids']}==set(index[source])
    assert len(model['references'])==3  # Five routes do not become five materials.
    pair=next(p for p in model['coverage']['pairs'] if p['subject']=='chips' and p['topic']=='composition')
    assert len(pair['references'])==2 and pair['available_studies']==[]


@pytest.mark.parametrize('change',['remove_material','remove_record','new_record','unknown_record','duplicate_record'])
def test_reverse_audit_rejects_missing_or_ambiguous_coverage(navigation,change):
    content,index,_=deepcopy(navigation)
    refs=content['classification']['references']
    if change=='remove_material':refs.pop(0)
    if change=='remove_record':refs[0]['records'].pop()
    if change=='new_record':index['activities']['new_activity']={'name':'New'}
    if change=='unknown_record':refs[0]['records'].append('not_registered')
    if change=='duplicate_record':refs[0]['records'].append(refs[0]['records'][0])
    with pytest.raises(ValueError):reference_catalog(content,index)


def test_reference_routes_need_valid_pairs_and_unique_ids(navigation):
    content,_,_=deepcopy(navigation)
    content['classification']['references'][0]['routes'][0]['subject']='refining-not-registered'
    with pytest.raises(ValueError):validate(content)


def test_localized_reference_links_and_deep_sections(navigation,tmp_path):
    content,index,model=navigation
    for language in ('zh','en'):
        base=tmp_path/language;base.mkdir()
        with use(language,load_phrases(PROJECT_ROOT)):
            html=reference_page_part(PROJECT_ROOT,index,model['studies'])
            home=browser(content,model,{}, {})
        (base/'sources.html').write_text(html)
        verify_targets(base,tmp_path,model['references'])
        assert home.count('class="reference-record"')==3
        assert 'sources.html#business-activities' in home
        assert 'id="business-activities"' in html


def test_production_filter_exhaustive_pairs_and_empty_states(navigation):
    content,_,model=navigation
    node=shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    payload={'model':model,'taxonomy':content['classification']}
    # This runs the exact production predicate; no browser-only reimplementation.
    script=r'''
const assert=require('node:assert/strict'),Q=require('./site/assets/discovery-query.js');
const {model,taxonomy}=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const all=[...model.studies,...model.references,...model.capabilities];
for(const en of [false,true]) {
 const lang=en?'en':'zh',vocab={entities:model.entities};
 for(const axis of ['objects','questions'])vocab[axis]=Object.fromEntries(Object.entries(taxonomy[axis]).map(([id,x])=>[id,{name:x.name[lang],children:Object.fromEntries(Object.entries(x.children).map(([k,v])=>[k,v[lang]]))}]));
 for(const [object,o] of Object.entries(taxonomy.objects))for(const subject of Object.keys(o.children))
 for(const [question,x] of Object.entries(taxonomy.questions))for(const topic of Object.keys(x.children)) {
   const query={object,subject,question,topic};
   const expected=all.filter(rec=>rec.routes.some(r=>r.object===object&&r.subject===subject&&r.question===question&&r.topic===topic)).map(r=>r.id).sort();
   assert.deepEqual(all.filter(rec=>Q.match(rec,query,vocab,en).show).map(r=>r.id).sort(),expected);
 }
 for(const rec of all)for(const r of rec.routes) {
   for(const q of [{object:r.object},{question:r.question},{object:r.object,subject:r.subject,question:r.question,topic:r.topic}])assert(Q.match(rec,q,vocab,en).show);
   for(const entity of r.entity_ids||[])assert(Q.match(rec,{object:r.object,subject:r.subject,question:r.question,topic:r.topic,entity},vocab,en).show);
 }
 const screenshot={object:'industry',subject:'chips',question:'structure',topic:'composition'};
 assert.equal(model.references.filter(r=>Q.match(r,screenshot,vocab,en).show).length,2);
 assert.equal(model.references.filter(r=>Q.match(r,{...screenshot,entity:'co_nvidia'},vocab,en).show).length,2);
 assert.equal(model.references.filter(r=>Q.match(r,{...screenshot,entity:'co_tsmc'},vocab,en).show).length,1);
 assert.equal(model.references.filter(r=>Q.match(r,{...screenshot,entity:'cik_320193'},vocab,en).show).length,0);
 assert.equal(model.references.filter(r=>Q.match(r,{...screenshot,result_type:'descriptive',cutoff:'2099-01-01'},vocab,en).show).length,2);
 assert.equal(all.filter(r=>Q.match(r,{object:'company',question:'valuation'},vocab,en).show).length,0);
 assert.equal(all.filter(r=>Q.match(r,{object:'industry',subject:'refining',question:'structure',topic:'relationships'},vocab,en).show).length,0);
 assert.equal(all.filter(r=>Q.match(r,{entity:'unknown'},vocab,en).show).length,0);
 const dossier=model.studies.find(s=>s.id==='us_industry_dossier');
 assert(!Q.match(dossier,{object:'company',question:'valuation'},vocab,en).show);
 const industry=model.studies.find(s=>s.id==='us_industry_12');
 assert(!Q.match(industry,{search:'PE'},vocab,en).show);
 assert(Q.match(dossier,{search:'PE'},vocab,en).show);
}
for(const [key,counts] of Object.entries({results:{published:1},unavailable:{missing:1},references:{references:2},capabilities:{capabilities:1},filtered:{base:1},unassessed:{}})) {
 assert.equal(Q.state(counts,{},model.entities),key);
 for(const en of [false,true])assert.equal(typeof Q.emptyText(key,en),'string');
}
assert.equal(Q.state({},{entity:'unknown'},model.entities),'unknown_subject');
'''
    subprocess.run([node,'-e',script],cwd=PROJECT_ROOT,input=json.dumps(payload),text=True,capture_output=True,check=True)
