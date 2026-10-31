"""One paired-route catalog for both browsing paths, capabilities and exported metadata."""
from __future__ import annotations
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from .common import e, shell, RESULT_TYPE_LABEL
from .i18n import L, is_en, te, tx
from .catalog import study_view
from .renderers import get_renderer
from .targets import PATHS, REPORT_TARGETS, available


def label(value: dict[str, str]) -> str:
    return value['en' if is_en() else 'zh']


def validate(content: dict[str, Any]) -> None:
    tax = content['classification']
    def route(r):
        obj = tax['objects'].get(r['object'])
        question = tax['questions'].get(r['question'])
        if not obj or r['subject'] not in obj['children'] or not question or r['topic'] not in question['children']:
            raise ValueError(f'Invalid classification route: {r}')
        if not all(r.get('scope', {}).get(k) for k in ('zh','en')):
            raise ValueError('A route needs bilingual scope')
    for sid, meta in content['studies'].items():
        rr = meta.get('routes', [])
        if sum(bool(r.get('primary')) for r in rr) != 1:
            raise ValueError(f'{sid}: exactly one primary route required')
        seen = set()
        for r in rr:
            route(r)
            if r['target'] not in PATHS:
                raise ValueError(f'{sid}: unknown target {r["target"]}')
            key = tuple(r[k] for k in ('object','subject','question','topic','target'))
            if key in seen:
                raise ValueError(f'{sid}: duplicate route')
            seen.add(key)
    for r in [*tax.get('capabilities', []), *tax.get('references', [])]:
        route(r)
    members = set()
    for c in content.get('collections', {}).values():
        for sid in [c['lead'], *c['members']]:
            if sid in members or sid not in content['studies']:
                raise ValueError(f'Invalid or duplicate collection member: {sid}')
            members.add(sid)


def catalog(content, latest, definitions, datasets, references_available=False, subject_index=None):
    """Locale-neutral data. A planned route never proves an output is present."""
    records = []
    for sid in dict.fromkeys([*content.get('study_order', []), *content['studies'], *latest, *definitions]):
        item = latest.get(sid)
        spec = item['result'] if item else definitions.get(sid, {})
        # YAML study definitions can contain native date values; the public model is JSON.
        spec = json.loads(json.dumps(spec, default=str))
        rr = []
        for route in content['studies'].get(sid, {}).get('routes', []):
            live = bool(item) and available(item['result'], route['target'], route['subject'])
            report = route['target'] in REPORT_TARGETS
            href = (f"runs/{item['manifest']['run_id']}/report.html" if report else f"studies/{sid}/#{route['target']}") if live else None
            rr.append({**route, 'available':live, 'report':report, 'href':href, 'entity_ids':route.get('entity_ids', (subject_index or {}).get('study_entities', {}).get(sid, []))})
        records.append({'id':sid,'title':spec.get('title',sid),'routes':rr,
                        'published':bool(item),'result_type':spec.get('result_type',''),
                        'scope':spec.get('scope',{}),'cutoff':spec.get('data_cutoff',''),
                        'limits':spec.get('limitations',[]), 'kind':'study',
                        'collection': next((cid for cid, c in content.get('collections', {}).items() if sid in c['members']), None)})
    capabilities=[]
    for i, route in enumerate(content['classification'].get('capabilities',[])):
        ids=route.get('datasets',[])
        if any(ds not in datasets for ds in ids):
            raise ValueError(f'Unknown capability dataset: {ids}')
        state = 'planned' if route.get('planned') else ('data' if any(datasets[d].get('version_id') for d in ids) else 'registered')
        fetched=[d for d in ids if datasets[d].get('version_id')]
        capabilities.append({'fetched':fetched,'datasets':ids,'id':f'cap-{i}','routes':[route],'state':state,'kind':'capability'})
    references=[{'id':f'reference-{i}', 'routes':[{**r, 'available':True, 'report':False}], 'kind':'reference'} for i,r in enumerate(content['classification'].get('references', []))] if references_available else []
    subjects = (subject_index or {}).get('entities', {})
    for rec in references:
        route = rec['routes'][0]
        if route['topic'] == 'relationships':
            ids = [eid for row in (subject_index or {}).get('relations', {}).values() for eid in row['endpoints']]
        else:
            ids = [row['owner'] for row in (subject_index or {}).get('mappings', {}).values()]
        route['entity_ids'] = sorted(set(ids))
    return {'studies':records,'capabilities':capabilities,'references':references,
            'entities': {k: {'name':v['name'], 'aliases':v['aliases'], 'type':v['type']} for k,v in subjects.items() if v['type'] != 'segment'}}


class _IDs(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=[]
    def handle_starttag(self, tag, attrs):
        self.ids += [v for k,v in attrs if k=='id']


def verify_targets(base: Path, shared: Path, records):
    pages={}
    for record in records:
        for route in record['routes']:
            if not route['available']: continue
            href=route['href']; path, _, anchor=href.partition('#')
            file=(shared if route['report'] else base)/path
            if not route['report'] and not file.suffix: file=file/'index.html'
            if not file.is_file(): raise ValueError(f'Missing classification target: {href}')
            if anchor:
                if file not in pages:
                    parser=_IDs();parser.feed(file.read_text());pages[file]=parser.ids
                    if len(parser.ids)!=len(set(parser.ids)): raise ValueError(f'Duplicate content ID: {file}')
                if pages[file].count(anchor)!=1: raise ValueError(f'Missing content ID: {href}')


def _attrs(record):
    return e(json.dumps(record,ensure_ascii=False))


def _route_text(r,tax):
    return ' · '.join([label(tax['objects'][r['object']]['children'][r['subject']]),
                       label(tax['questions'][r['question']]['name']),
                       label(tax['questions'][r['question']]['children'][r['topic']])])


def browser(content, model, latest, build, frequency=None):
    tax=content['classification']
    def select(key,title,values):
        opts=''.join(f'<option value="{e(k)}">{e(v)}</option>' for k,v in values)
        return f'<label>{title}<select name="{key}"><option value="">{L("全部","All")}</option>{opts}</select></label>'
    controls=select('object',L('研究对象','Research object'),[(k,label(v['name'])) for k,v in tax['objects'].items()])
    controls+=select('subject',L('对象子类','Object subtype'),[])
    controls+=select('question',L('研究问题','Research question'),[(k,label(v['name'])) for k,v in tax['questions'].items()])
    controls+=select('topic',L('问题子类','Question subtype'),[])
    controls+=select('entity', L('具体公司 / 主体', 'Company / subject'), [(k, tx(v['name'])) for k,v in model.get('entities', {}).items()])
    basic=controls
    controls=''
    controls+=select('result_type',L('成果类型','Result type'),[(k,RESULT_TYPE_LABEL.get(k,k)) for k in sorted({x['result_type'] for x in model['studies'] if x['result_type']})])
    controls+=select('market',L('市场 / 数据范围','Market / data scope'),[(k,k) for k in sorted({str(x['scope'].get('market','')) for x in model['studies']} - {''})])
    controls+=select('frequency',L('频率','Frequency'),[(k,k) for k in sorted({x['scope'].get('frequency','') for x in model['studies']} - {''})])
    for key,title,typ in [('search',L('搜索标题、问题与范围','Search titles, questions and scope'),'search'),('start',L('期间开始（含重叠）','Period from (overlap)'),'date'),('end',L('期间结束','Period to'),'date'),('cutoff',L('数据截止不早于','Data cutoff since'),'date')]:
        field=f'<label>{title}<input name="{key}" type="{typ}"></label>'
        if key=='search': basic+=field+'<div class="entity-suggestions" role="status" aria-live="polite"></div>'
        else: controls+=field
    quick=''
    for key,heading in [('object',L('按对象找','Browse by object')),('question',L('按问题找','Browse by question'))]:
        values=tax['objects' if key=='object' else 'questions']
        quick+=f'<div class="browse-axis"><h2>{heading}</h2><ul>'+''.join(f'<li><a href="#object-{e(k)}" data-filter="{key}" data-value="{e(k)}">{e(label(v["name"]))}</a></li>' if key=='object' else f'<li><a href="#research-results" data-filter="{key}" data-value="{e(k)}">{e(label(v["name"]))}</a></li>' for k,v in values.items())+'</ul></div>'
    groups=[]
    for obj in [*tax['objects'],'unclassified']:
        rows=[]; members={}; views=[]
        for rec in model['studies']:
            main=next((r for r in rec['routes'] if r.get('primary')),None)
            if (main['object'] if main else 'unclassified')!=obj:continue
            sid=rec['id']; item=latest.get(sid)
            view=study_view(sid,item,content['studies'].get(sid,{}),frequency) if item else None
            if view: views.append(view)
            status=L('尚未发布','Not published') if not item else (L('已有结果','Published results') if any(r['available'] for r in rec['routes']) else L('当前结果未提供所登记内容','Registered content unavailable in this run'))
            routes=[]
            for r in rec['routes']:
                title=_route_text(r,tax)
                extra=L(' · 完整报告（中文）',' · Full report (Chinese)') if r.get('report') else ''
                href=('../' if is_en() and r.get('report') else '')+(r.get('href') or '')
                link=f'<a href="{e(href)}">{e(title+extra)}</a>' if r.get('available') else f'<span>{e(title)} — {L("本次无可访问结果","No accessible result in this release")}</span>'
                routes.append(f'<li data-route="{_attrs(r)}">{link}<small>{e(label(r["scope"]))}</small></li>')
            notices=''.join(f'<p class="small {"bad" if n.level=="fail" else "warn" if n.level=="warn" else "muted"}">{e(n.text)}</p>' for n in (view.notices if view else []))
            title=f'<a href="studies/{e(sid)}/">{te(rec["title"])}</a>' if item else te(rec['title'])
            limits='<details class="result-limits"><summary>'+L('研究范围与限制','Scope and limitations')+'</summary><ul>'+''.join(f'<li>{te(x)}</li>' for x in rec['limits'])+'</ul></details>'
            scope=rec['scope']; period=f"{scope.get('start','—')} — {scope.get('end','—')}"
            row = (f'<li class="research-record" data-record="{_attrs(rec)}"><div class="result-heading"><h3>{title}</h3><span class="result-status">{status}</span></div>'
                        f'<p class="small muted">{e(RESULT_TYPE_LABEL.get(rec["result_type"],rec["result_type"]))} · {e(period)} · {L("数据截止","Data cutoff")} {e(rec["cutoff"] or "—")}</p>'
                        f'<p class="general-finding">{view.finding if view else ""}</p><ul class="route-links">{"".join(routes)}</ul>{notices}'
                        f'<p class="small muted">{e(view.checks) if view else ""}</p>{limits}</li>')
            severity='fail' if view and view.failed else 'warn' if view and view.limited else ''
            row=row.replace('data-record=', f'data-severity="{severity}" data-record=', 1)
            cid=rec['collection']
            if cid:
                renderer=get_renderer(item['result']['branch']) if item else None
                cells=renderer.summary_row(item['result']) if renderer and renderer.summary_row else ['—']*3
                detail=f'<details><summary>{L("内容、检查与限制","Content, checks and limits")}</summary><ul class="route-links">{"".join(routes)}</ul>{notices}<p>{e(view.checks) if view else ""}</p>{limits}</details>'
                members.setdefault(cid, []).append(f'<tr class="research-record" data-severity="{severity}" data-record="{_attrs(rec)}"><td>{title}</td>'+''.join(f'<td>{x}</td>' for x in cells)+f'<td><span class="result-status">{status}</span>{detail}</td></tr>')
            else:
                rows.append(row)
        tables=[]
        for cid, member_rows in members.items():
            collection=content['collections'][cid]
            heads=[L('公司','Company'), L('财年末','Fiscal year end'), L('营收（十亿美元）','Revenue (USD bn)'), L('同口径同比','Comparable YoY'), L('内容与状态','Content and status')]
            tables.append(f'<div class="research-collection"><h3>{te(collection["name"])}</h3><div class="scroll"><table><thead><tr>'+''.join(f'<th>{h}</th>' for h in heads)+'</tr></thead><tbody>'+''.join(member_rows)+'</tbody></table></div></div>')
        if rows or tables or obj in tax['objects']:
            name=label(tax['objects'][obj]['name']) if obj in tax['objects'] else L('尚未分类','Not classified')
            failed=sum(v.failed for v in views); limited=sum(v.limited and not v.failed for v in views)
            alerts=(f'<span class="bad"> · {L(f"{failed} 项检查失败", f"{failed} with failed checks")}</span>' if failed else '')
            alerts+=(f'<span class="warn"> · {L(f"{limited} 项有数据或覆盖限制", f"{limited} with data or coverage limits")}</span>' if limited else '')
            total=len(rows)+sum(len(x) for x in members.values())
            empty='' if total else '<p>'+L('尚无以此为主归属的研究。相关数据与规划见下方；启用筛选可查找跨对象入口。','No studies have this as their primary object. See data and plans below; filters include cross-object routes.')+'</p>'
            groups.append(f'<details class="result-group" id="object-{obj}"><summary>{e(name)} · <span class="summary-count">{total}</span><span class="summary-alerts">{alerts}</span></summary>{empty}<ul class="research-list">{"".join(rows)}</ul>{"".join(tables)}</details>')
    caps=[]
    states={'planned':L('规划中','Planned'),'data':L('已有数据，尚无对应研究','Data available; no matching study'),'registered':L('数据已登记，本次构建未取得','Data registered; unavailable in this build')}
    for rec in model['capabilities']:
        r=rec['routes'][0]
        progress=L(f'已取得 {len(rec["fetched"])} / {len(rec["datasets"])} 项登记数据', f'{len(rec["fetched"])} / {len(rec["datasets"])} registered datasets fetched') if rec['datasets'] else ''
        caps.append(f'<li class="capability-record" data-record="{_attrs(rec)}"><strong>{e(_route_text(r,tax))}</strong> · {states[rec["state"]]} · {progress}<p>{e(label(r["scope"]))}</p></li>')
    refs=[]
    for rec in model['references']:
        r=rec['routes'][0]
        refs.append(f'<li class="reference-record" data-record="{_attrs(rec)}"><a href="{e(r["href"])}">{e(_route_text(r,tax))}</a><p>{e(label(r["scope"]))}</p></li>')
    # Localized query vocabulary; values remain stable IDs across languages.
    vocab={axis:{k:{'name':label(v['name']),'children':{x:label(y) for x,y in v['children'].items()}} for k,v in tax[axis].items()} for axis in ('objects','questions')}
    vocab['entities'] = {k: {**v, 'name':tx(v['name'])} for k,v in model.get('entities', {}).items()}
    config=e(json.dumps(vocab,ensure_ascii=False))
    return f'''<div class="discovery" data-vocabulary="{config}">
<div class="browse-paths">{quick}</div>
<form class="research-filters" hidden>{basic}<button type="reset">{L('重置','Reset')}</button><details class="advanced-filters"><summary>{L('更多筛选：成果类型、市场与日期','More filters: result type, market and dates')}</summary><div>{controls}</div></details></form>
<noscript><p>{L('下方目录可直接展开阅读；启用 JavaScript 后可组合筛选。','The catalog below is readable without JavaScript; enable it for combined filters.')}</p></noscript>
<p class="subject-reference" hidden></p>
<section id="research-results"><h2>{L('研究目录','Study catalog')}</h2><p class="query-status" role="status" aria-live="polite"></p>
<p class="empty-state" hidden>{L('当前无已发布的匹配研究。未登记的对象与问题组合尚未评估；已有数据或规划见下方。','No published studies match. Unregistered object–question combinations have not been assessed; see data and plans below.')}</p>
{''.join(groups)}</section>
<section><details class="data-plans"><summary>{L('数据与规划','Data and plans')}</summary><ul class="capability-list">{''.join(caps)}</ul>
<p class="small muted">{L('信号与预测检验有通用规划，尚未分配到具体对象；不代表所有对象均已规划。','Signal and forecast testing has a general plan, not yet assigned to individual objects.')}</p></details></section>
<section class="reference-entry"><h2>{L('数据与参照','Data and references')}</h2>
<p>{L('来源、行业分类、业务定义与候选关系分别标注证据状态，不计入研究数。','Sources, classifications, business definitions and candidate relationships retain separate evidence statuses and are not counted as studies.')}</p>
<ul>{"".join(refs)}</ul>
<a href="sources.html#references">{L('查看分类与产业关系资料','Browse classifications and business relationships')}</a> · <a href="sources.html">{L('数据来源目录','Data source catalog')}</a></section></div>'''


def page(content, model, latest, build, frequency=None, capability=False):
    title=L('研究能力地图','Research capability map') if capability else L('寻找研究','Find research')
    body=f'<header class="hero"><div class="wrap"><h1>{title}</h1><p class="tagline">{L("从研究对象或问题出发，找到结果、依据与边界。","Start with an object or a question. Find results, evidence and limits.")}</p></div></header><main class="wrap">'+browser(content,model,latest,build,frequency)+'</main>'
    return shell(title+' · Investment Research OS',body,build,page='map.html' if capability else 'index.html',active='map.html' if capability else 'index.html')
