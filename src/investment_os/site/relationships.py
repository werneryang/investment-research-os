"""Shared, static-first relationship and evidence view for every registered subject."""
from __future__ import annotations

import json
from urllib.parse import urlencode

from .common import e
from .i18n import L, te, tx

TYPES = {'supply': ('产品供应', 'Product supply'), 'foundry': ('晶圆代工', 'Wafer foundry'),
         'contract_manufacturing': ('合同制造与组装', 'Contract manufacturing / assembly'),
         'competition': ('竞争', 'Competition'), 'partnership': ('合作', 'Partnership'),
         'substitution': ('替代', 'Substitution')}


def attrs(value):
    return e(json.dumps(value, ensure_ascii=False, default=str))


def subject_link(index, eid, prefix=''):
    entity = index['entities'][eid]
    href = prefix + 'sources.html?' + urlencode({'entity': eid}) + '#relationships'
    return f'<a href="{e(href)}">{te(entity["name"])}</a>'


def review_html(row):
    technical = row['technical']
    state = {'none': L('无技术复核记录', 'No technical review record'),
             'stale': L('复核记录已失效', 'Review record is stale')}.get(technical,
             L('技术复核记录：', 'Technical review record: ') + technical)
    human = {'candidate': L('未人工确认', 'Not human-confirmed'), 'confirmed': L('人工确认', 'Human-confirmed'),
             'rejected': L('人工否定', 'Human-rejected'), 'retracted': L('已撤回', 'Retracted')}[row['human']]
    bad = technical in ('failed', 'stale') or row['human'] in ('rejected', 'retracted') or row.get('evidence_problem')
    out = f'<span class="{"bad" if bad else "muted"}">{e(state)} · {L("人工状态", "Human review")}: {human}</span>'
    if row.get('technical_date'):
        out += f'<small>{L("复核日期", "Review date")}: {e(row["technical_date"])}</small>'
    if row.get('evidence_problem'):
        out += '<p class="bad">'+L('所引用证据存在失效、失败、否定或撤回记录。', 'Referenced evidence has stale, failed, rejected or retracted records.')+'</p>'
    return out


def evidence_html(index, row):
    items = []
    for cid in row.get('claims', []):
        claim = index['evidence'][cid]
        doc = claim['document']
        source = index['entities'].get(doc.get('entity'), {}).get('name', L('未登记', 'Unregistered'))
        title = te(source) + e(f' · {doc.get("form") or ""} · {doc.get("accession") or cid}')
        link = f'<a href="{e(doc["url"])}">{title}</a>' if doc.get('url') else title
        text = f'<li>{link}<p>{L("原文位置", "Source location")}: {te(claim.get("locator") or claim.get("tag") or "—")}</p>'
        if claim.get('excerpt'):
            text += f'<blockquote lang="en">{e(claim["excerpt"])}</blockquote>'
        if claim.get('value') is not None:
            text += f'<p>{e(claim["value"])} {e(claim.get("unit", ""))} · {e(claim.get("period_end", ""))}</p>'
        if claim.get('segments'):
            text += '<p>'+e(json.dumps(claim['segments'], ensure_ascii=False))+'</p>'
        text += f'<p>{L("申报报告期末", "Filing period end")}: {e(doc.get("document_period_end") or L("未知", "Unknown"))}</p>'
        text += f'<p>{L("申报接受时间", "Filing accepted")}: {e(doc.get("accepted_at") or L("未知", "Unknown"))}</p>{review_html(claim)}'
        for field in ('note', 'technical_limits'):
            if claim.get(field): text += '<p>'+te(claim[field])+'</p>'
        items.append(text+'</li>')
    return '<details class="relationship-evidence"><summary>'+L('证据及逐条复核状态', 'Evidence and review status')+'</summary><ol>'+''.join(items)+'</ol></details>'


def validity_html(row):
    start, end = row.get('valid_from'), row.get('valid_to')
    return L('关系有效期', 'Relationship validity')+': '+e(f'{start or L("未知", "Unknown")} — {end or L("未知", "Unknown")}')


def share_html(share):
    if not share: return ''
    if share.get('value') is not None:
        amount = f'{share["value"] * 100:g}%'
    elif share.get('bound'):
        amount = str(share['bound'])
    else:
        amount = L('未披露', 'Undisclosed')
    return '<p class="share-scope">'+L('披露占比', 'Disclosed share')+': '+e(amount)+' · '+te(share.get('numerator', ''))+' / '+te(share.get('denominator', ''))+' · '+e(share.get('period', ''))+'</p>'


def relationship_view(index, studies=None, prefix='', initial_entity='', embedded=False):
    entities, activities = index['entities'], index['activities']
    selectable = entities
    choices = ''.join(f'<option value="{e(k)}"{" selected" if k == initial_entity else ""}>{e(tx(v["name"]))}</option>' for k,v in selectable.items())
    activity_choices = ''.join(f'<option value="{e(k)}">{e(tx(v["name"]))}</option>' for k,v in activities.items())
    types = {k: L(*v) for k,v in TYPES.items()}
    config = {'entities': {k: {'name': tx(v['name']), 'aliases': v['aliases'], 'type': v['type']} for k,v in entities.items()},
              'activities': {k: tx(a['name']) for k,a in activities.items()}, 'prefix': prefix,
              'initial': initial_entity, 'embedded': embedded, 'types': types}
    controls = f'''<form class="relationship-controls" hidden>
<label>{L('查找公司或主体', 'Find a company or subject')}<input type="search" name="entity_search" autocomplete="off"></label>
<div class="entity-suggestions" role="status" aria-live="polite"></div>
<label>{L('查看主体', 'Subject')}<select name="entity"><option value="">{L('全部已登记关系', 'All registered relationships')}</option>{choices}</select></label>
<label>{L('对照主体', 'Compare with')}<select name="compare"><option value="">{L('不对照', 'No comparison')}</option>{choices}</select></label>
<label>{L('业务环节', 'Business activity')}<select name="activity"><option value="">{L('全部', 'All')}</option><option value="unknown">{L('环节尚未确定', 'Activity undetermined')}</option>{activity_choices}</select></label>
<label>{L('关系类型', 'Relationship type')}<select name="relation_type"><option value="">{L('全部', 'All')}</option>{''.join(f'<option value="{k}">{e(v)}</option>' for k,v in types.items())}</select></label>
<label>{L('关系技术复核', 'Relationship technical review')}<select name="review"><option value="">{L('全部（含候选与失效）', 'All (including candidates and stale records)')}</option><option value="passed">{L('通过且证据记录无已知问题', 'Passed, with no known evidence-record problems')}</option><option value="none">{L('暂无记录', 'No record')}</option><option value="problem">{L('失败、失效、否定或撤回', 'Failed, stale, rejected or retracted')}</option></select></label>
<label>{L('证据申报日期不晚于', 'Evidence filing date through')}<input name="evidence_before" type="date"></label>
<button type="reset">{L('重置', 'Reset')}</button>
</form>'''
    maps = []
    for row in index['mappings'].values():
        if embedded and initial_entity not in (row['owner'], row['entity']): continue
        activity = activities[row['activity']]
        body = f'{subject_link(index, row["owner"], prefix)} · {te(entities[row["entity"]]["name"])} → {te(activity["name"])}'
        notes = ''.join('<p>'+te(row[field])+'</p>' for field in ('note', 'technical_limits') if row.get(field))
        maps.append(f'<li id="ref-{e(row["id"])}" data-mapping="{attrs(row)}"><strong>{body}</strong><p>{e(row["match"])} · {validity_html(row)}</p><p>{te(row.get("scope", ""))}</p>{notes}{review_html(row)}{evidence_html(index,row)}</li>')
    rows = []
    for row in index['relations'].values():
        if embedded and initial_entity not in row['endpoints']: continue
        direction = ' → ' if 'provider' in row else ' ↔ '
        endpoints = direction.join(subject_link(index, eid, prefix) for eid in row['endpoints'])
        name = te(activities[row['activity']]['name']) if row.get('activity') else L('环节尚未确定', 'Activity undetermined')
        content = '<p>'+te(row.get('product') or row.get('market') or '')+'</p><p>'+name+'</p>'
        for field in ('activity_gap', 'note', 'technical_limits'):
            if row.get(field): content += '<p>'+te(row[field])+'</p>'
        content += share_html(row.get('share'))
        dates = ' / '.join(row['evidence_dates']) or L('未知', 'Unknown')
        rows.append(f'<tr id="ref-{e(row["id"])}" data-relation="{attrs(row)}"><td>{endpoints}<p>{e(types[row["type"]])}</p><p class="relative-role"></p></td><td>{content}</td><td>{e(dates)}<p>{validity_html(row)}</p></td><td>{review_html(row)}{evidence_html(index,row)}</td></tr>')
    related = []
    for record in studies or []:
        ids = list(dict.fromkeys(eid for r in record['routes'] for eid in r.get('entity_ids', [])))
        if not ids or (embedded and initial_entity not in ids): continue
        link = f'<a href="{prefix}index.html?entity={e(initial_entity)}#research-results">{te(record["title"])}</a>' if embedded else te(record['title'])
        if record['published']:
            link = f'<a href="{prefix}studies/{e(record["id"])}/">{te(record["title"])}</a>'
        related.append(f'<li data-related="{attrs({"entities": ids})}">{link} · {L("已有公开结果", "Published results") if record["published"] else L("尚未发布", "Not published")}</li>')
    intro = L('仅展示登记的直接关系，尚未收录不等于确认不存在。业务映射不能用于收入分摊，关系记录不证明采购份额或完整产业链。',
              'Only registered direct relationships are shown. Not registered does not mean absent. Business mappings cannot allocate revenue; relationship records do not establish procurement shares or a complete supply chain.')
    checks = L('本次构建仅核对技术记录与当前内容的指纹，没有重新运行原文或数值机器核验；技术复核不等于人工确认。证据申报日期不代表关系有效期或当时可交易性。',
               'This build checks review fingerprints against current records; it does not rerun source-text or numeric checks. Technical review is not human confirmation. Filing dates do not establish relationship validity or historical tradability.')
    more = f'<p><a href="{prefix}sources.html?entity={e(initial_entity)}#relationships">{L("在通用关系视图中筛选、对照与查看示意", "Filter, compare and explore in the shared relationship view")}</a></p>' if embedded else ''
    heads = L('<th>主体、方向与类型</th><th>产品、业务与范围</th><th>证据申报日期与有效期</th><th>复核与证据</th>',
              '<th>Subjects, direction and type</th><th>Product, activity and scope</th><th>Filing dates and validity</th><th>Review and evidence</th>')
    return f'''<section id="{'company-business' if embedded else 'relationships'}" class="relationship-view" data-relationship-index="{attrs(config)}">
<h2>{L('分部、业务与产业关系', 'Segments, business activities and relationships')}</h2><p>{intro}</p><p class="small muted">{checks}</p>
{'' if embedded else controls}{more}
<noscript><p>{L('以下是已登记记录，可直接阅读；启用脚本后可按主体筛选。', 'Registered records remain readable below; enable scripts to filter by subject.')}</p></noscript>
<p class="relationship-status" role="status" aria-live="polite"></p>
<div class="relationship-comparison" hidden></div>
<details id="business-mappings" {'open' if embedded else ''}><summary>{L('分部与业务映射', 'Segment-to-business mappings')} · {len(maps)}</summary><p class="mapping-empty"{'' if not maps else ' hidden'}>{L('尚未收录匹配的业务映射。', 'No matching business mappings have been registered.')}</p><ul>{''.join(maps)}</ul></details>
<details id="business-relations" {'open' if embedded else ''}><summary>{L('直接公司关系（含候选）', 'Direct company relationships (including candidates)')} · {len(rows)}</summary>
<p class="relation-empty"{'' if not rows else ' hidden'}>{L('尚未收录匹配关系；不能据此判定不存在。', 'No matching relationships have been registered; this does not establish absence.')}</p>
<div class="scroll"><table class="relationship-table"><thead><tr>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>
{'' if embedded else '<details class="relationship-diagram"><summary>'+L('一跳关系示意（与当前表格一致）', 'One-hop relationship diagram (same records as the table)')+'</summary><p>'+L('箭头表示登记的提供方 → 接收方；↔ 表示无向关系。每条保留复核状态，不表示规模或依赖强度。', 'Arrows show registered provider → recipient; ↔ is undirected. Review states remain explicit; layout does not represent size or dependency strength.')+'</p><div class="diagram-content"></div></details>'}
<details class="related-studies"><summary>{L('相关研究', 'Related studies')}</summary><p class="related-empty" hidden>{L('尚无登记的相关研究。', 'No related studies are registered.')}</p><ul>{''.join(related)}</ul></details>
</section>'''
