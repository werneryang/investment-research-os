"""Reports-only publication boundary, safe rendering and discovery (offline)."""
from pathlib import Path
import json
import os
import subprocess

import pytest
import yaml

from investment_os.notes import NoteRejected, boundary_issues, clean_report, import_report, load_notes
from investment_os.cli import main
from investment_os.site.notes import note_catalog, write_pages
from investment_os.site.i18n import use
from tests.conftest import PROJECT_ROOT

ID = 'AAPL-20261117-value-chain'
BODY = '# Apple 业务结构\n\n【事实】收入 100。\n\n【推断】该比较需要后续核对。\n\n| 指标 | 数值 |\n| --- | --- |\n| 收入 | 100 |\n'


def source(tmp_path, body=BODY, folder='reports', identifier=ID):
    p = tmp_path/'source'/'companies'/'AAPL'/folder/(identifier+'.md')
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(body)
    return p


def test_import_copies_only_passing_report_with_date_and_no_private_source_path(project,tmp_path):
    src=source(tmp_path)
    result=import_report(project,src)
    assert result['public_boundary']=='pass'
    assert result['path']==f'notes/companies/AAPL/2026-11-17/{ID}.md'
    text=(project/result['path']).read_text()
    assert str(tmp_path) not in text and src.read_text()==BODY
    notes,bad=load_notes(project)
    assert not bad and len(notes)==1 and notes[0]['date']=='2026-11-17'
    assert '【推断】' in notes[0]['body'] and 'source_sha256:' in text


@pytest.mark.parametrize('folder',['results','reports-archive','reports/elsewhere'])
def test_never_import_private_results_or_lookalike_folders(project,tmp_path,folder):
    with pytest.raises(NoteRejected):import_report(project,source(tmp_path,folder=folder))
    assert not (project/'notes').exists()


@pytest.mark.parametrize('bad',[
    ('/'+'Users/')+'someone/private/file.md', ('/'+'home/')+'someone/private.md', 'file:///tmp/private',
    'C:\\private\\file.md', 'name'+chr(64)+'example.test', 'sk-'+'x'*35,
    'github_pat_'+'x'*35, 'API_KEY='+'x'*35, 'Bearer '+'x'*35,
    '你的判断', '当前持仓', '第 10 节', '## 10. 动作', 'my holdings',
    '%2FUsers%2Fsomeone%2Fsecret', 'name%40example.test',
    '<!-- secret hidden here -->', '<script>alert(1)</script>',
    '[private](https://github.com/example/'+'company-dossiers/blob/main/companies/AAPL/results/x.md)',
    '> '+'quoted '*26, '“'+'引文'*51+'”', '![tracking](https://example.test/pixel.png)',
])
def test_reject_entire_copied_text_before_any_write(project,tmp_path,bad):
    src=source(tmp_path,BODY+'\n'+bad)
    with pytest.raises(NoteRejected) as caught:import_report(project,src)
    assert bad not in str(caught.value)  # errors never echo potentially sensitive bytes
    assert not (project/'notes').exists()


def test_quote_splitting_is_not_automatic_publication_bypass(project,tmp_path):
    text=BODY+'\n> '+'first '*15+'\n\n> '+'second '*15
    with pytest.raises(NoteRejected,match='long_quote_review'):import_report(project,source(tmp_path,text))


def test_symlink_and_traversal_sources_and_destination_rejected(project,tmp_path):
    real=source(tmp_path)
    link=real.with_name('AAPL-20261118-value-chain.md');link.symlink_to(real)
    with pytest.raises(NoteRejected):import_report(project,link)
    (project/'notes').symlink_to(tmp_path/'outside')
    with pytest.raises(NoteRejected):import_report(project,real)


def public_git(root):
    rel='methodology/records/public.yaml';p=root/rel;p.parent.mkdir(parents=True);p.write_text('public: true\n')
    subprocess.run(['git','init','-q',str(root)],check=True)
    env={**os.environ,'GIT_AUTHOR_NAME':'Test','GIT_COMMITTER_NAME':'Test',
         'GIT_AUTHOR_EMAIL':'test'+chr(64)+'invalid.test','GIT_COMMITTER_EMAIL':'test'+chr(64)+'invalid.test'}
    subprocess.run(['git','-C',str(root),'add','--',rel],check=True)
    subprocess.run(['git','-C',str(root),'commit','-qm','fixture'],env=env,check=True)
    subprocess.run(['git','-C',str(root),'update-ref','refs/remotes/origin/main','HEAD'],check=True)
    return rel


def test_only_verified_public_record_paths_rewritten_private_results_become_plain_id(project):
    rel=public_git(project)
    text='`'+'/'+'Users/test/projects/investment-research-os/'+rel+'`\n[private](../results/AAPL-20261117-value-chain.md)'
    clean,n=clean_report(project,text)
    assert n==2 and ('/'+'Users/') not in clean and '../results/' not in clean
    assert 'https://github.com/werneryang/investment-research-os/blob/' in clean
    assert '结果 ID：AAPL-20261117-value-chain' in clean and not boundary_issues(clean)
    (project/rel).write_text('unpublished: true\n')
    with pytest.raises(NoteRejected):clean_report(project,text)


def test_unverified_or_private_target_not_made_public(project):
    text='/'+'Users/test/projects/investment-research-os/methodology/records/nonexistent.yaml'
    with pytest.raises(NoteRejected):clean_report(project,text)


def test_build_revalidates_per_note_and_never_publishes_bad_body(project,tmp_path):
    a=import_report(project,source(tmp_path))
    b=import_report(project,source(tmp_path,identifier='AAPL-20261118-value-chain'))
    p=project/b['path'];p.write_text(p.read_text()+'\n你的判断\n')
    notes,rejected=load_notes(project)
    assert len(notes)==1 and notes[0]['id']==ID and len(rejected)==1
    assert rejected[0]['issues']==['user_private']
    assert main(['--root',str(project),'notes','check'])==2


def test_metadata_checks_decoded_values_and_no_extra_hidden_fields(project,tmp_path):
    a=import_report(project,source(tmp_path));p=project/a['path']
    text=p.read_text().replace('language: zh','language: zh\nextra: "name\\u0040example.test"')
    p.write_text(text)
    notes,bad=load_notes(project)
    assert not notes and bad and 'email' in bad[0]['issues']


def test_noindex_chinese_only_markdown_tables_safe_links_and_metadata_catalog(project,tmp_path):
    import_report(project,source(tmp_path))
    notes,bad=load_notes(project);assert not bad
    out=tmp_path/'out';out.mkdir()
    build={'built_at':'2026-11-17T01:00:00+00:00','repo_url':'https://github.com/werneryang/investment-research-os'}
    # Even an English-language caller must not make a nonexistent EN report/redirect.
    with use('en',{},set()):write_pages(out,notes,build)
    page=(out/notes[0]['href']/'index.html').read_text()
    assert '<meta name="robots" content="noindex">' in page and '<table>' in page
    assert '<html lang="zh-CN">' in page and 'localStorage.getItem("lang")' not in page
    assert 'hreflang="en"' not in page and '<img' not in page.replace('<img class="badge"','<badge')
    robots=(out/'robots.txt').read_text();assert 'Disallow: /investment-research-os/notes/' in robots
    assert (out/'notes/companies/AAPL/2026-11-17/index.html').exists()
    records=note_catalog(notes,{'by_cik':{'320193':'cik_320193'}})
    assert records[0]['kind']=='note' and records[0]['entity_ids']==['cik_320193']
    assert 'body' not in json.dumps(records) and 'source_sha256' not in json.dumps(records)


def test_note_query_applies_company_date_and_result_type_without_claiming_a_study():
    script=PROJECT_ROOT/'site/assets/discovery-query.js'
    js='''const Q=require(process.argv[1]);
const r={kind:'note',title:'Apple report',result_type:'research_note',scope:{start:'2026-11-17',end:'2026-11-17'},cutoff:'2026-11-17',routes:[{object:'company',subject:'issuer',question:'fundamentals',topic:'financials',entity_ids:['apple'],scope:{en:'report',zh:'报告'},available:true}]};
const v={objects:{company:{name:'Company',children:{issuer:'Issuer'}}},questions:{fundamentals:{name:'Fundamentals',children:{financials:'Financials'}}},entities:{apple:{name:'Apple',aliases:['AAPL']}}};
console.log(JSON.stringify([Q.match(r,{entity:'apple',search:'AAPL'},v,true).show,Q.match(r,{entity:'other'},v,true).show,Q.match(r,{start:'2026-11-18'},v,true).show,Q.match(r,{result_type:'descriptive'},v,true).show,Q.state({notes:1}, {},v.entities)]));'''
    got=json.loads(subprocess.check_output(['node','-e',js,str(script)],text=True))
    assert got==[True,False,False,False,'results']


@pytest.mark.parametrize('front', ['[', 'null', '- a\n- b'])
def test_bad_yaml_is_scoped_to_one_report_not_a_site_failure(project,tmp_path,front):
    result=import_report(project,source(tmp_path));p=project/result['path']
    p.write_text('---\n'+front+'\n---\n# Report')
    good,bad=load_notes(project)
    assert not good and len(bad)==1


def test_site_integration_lists_notes_without_study_run_or_bad_note_leak(project,tmp_path):
    import shutil
    from investment_os.site import build_site
    from investment_os.site.references import company_reference_part

    shutil.copytree(PROJECT_ROOT/'site',project/'site')
    first=import_report(project,source(tmp_path))
    other=import_report(project,source(tmp_path,identifier='AAPL-20261118-value-chain'))
    bad=project/other['path'];bad.write_text(bad.read_text()+'\n你的判断\n')
    out=tmp_path/'site-out';build_site(project,out)
    model=json.loads((out/'summary.json').read_text())
    assert len(model['classification']['notes'])==1 and len(model['notes_rejected'])==1
    assert ID in (out/'research.html').read_text() and ID in (out/'en/research.html').read_text()
    assert ID in (out/'browse/company/index.html').read_text()
    assert not (out/'notes/companies/AAPL/2026-11-18/AAPL-20261118-value-chain/index.html').exists()
    assert '你的判断' not in (out/'research.html').read_text()
    assert model['runs']==[] and len(model['classification']['studies'])==35
    records=model['classification']['notes']
    index={'by_cik':{'320193':'cik_320193'}}
    section=company_reference_part({'branch':'earnings_quarter','results':{'company':{'cik':320193}}},index,[],records)
    assert ID in section and 'Research report' not in section  # current locale is Chinese
    with pytest.raises(ValueError,match='重叠'):
        build_site(project,project/'notes')


@pytest.mark.parametrize('bad',[
    '/'+'root/secret.md', '/'+'Applications/private.md', '/'+'arbitrary/private.md',
    'api_key:\n  '+'a'*35, '持**仓**', '## **10. 动作**', '你**的**判断',
    '‘'+'quote '*26+'’', '『'+'引文'*51+'』', '`'+'quote '*26+'`',
    'name**'+chr(64)+'**example.test',
])
def test_independent_review_regressions_reject_rendered_markers_multiline_keys_and_quote_styles(project,tmp_path,bad):
    with pytest.raises(NoteRejected):import_report(project,source(tmp_path,BODY+'\n'+bad))


def test_legitimate_title_with_three_hyphens_round_trips(project,tmp_path):
    result=import_report(project,source(tmp_path,'# Apple --- Report\n\n【事实】100。'))
    notes,bad=load_notes(project)
    assert not bad and notes[0]['title']=='Apple --- Report'


@pytest.mark.parametrize('bad',['你的\n判断','持\n仓','我的判断','个人判断','密钥：'+'x'*35])
def test_private_marker_softbreaks_and_chinese_key_labels_are_rejected(project,tmp_path,bad):
    with pytest.raises(NoteRejected):import_report(project,source(tmp_path,BODY+'\n'+bad))


@pytest.mark.parametrize('url',[
    'https://github.com/example/unregistered-repository/blob/main/report.md',
    'https://raw.githubusercontent.com/example/unregistered/main/report.md',
    'https://github.com/werneryang/investment-research-os/../../example/unregistered/blob/main/report.md',
    'https://gist.github.com/example/12345',
])
def test_unverified_repository_urls_fail_closed_even_without_known_private_name(project,tmp_path,url):
    with pytest.raises(NoteRejected,match='unverified_repository'):
        import_report(project,source(tmp_path,BODY+'\n'+url))


def test_bad_title_and_control_characters_reject_before_write(project,tmp_path):
    with pytest.raises(NoteRejected):import_report(project,source(tmp_path,'# '+'x'*301))
    with pytest.raises(NoteRejected):import_report(project,source(tmp_path,BODY+'\x00'))
