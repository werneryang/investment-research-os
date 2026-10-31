"""Publish registered reference metadata; never turn candidate relationships into facts."""
from pathlib import Path
from .common import e
from .i18n import L, te
from .entities import build_index
from .relationships import relationship_view


def reference_page_part(root: Path, index=None, studies=None) -> str:
    index = index if index is not None else build_index(root, {}, {})
    activities=''
    for id,a in index['activities'].items():
        detail=f'<strong>{te(a["name"])}</strong><p>{te(a["definition"])}</p>'
        for field,title in [('includes',L('包含','Includes')),('excludes',L('不包含','Excludes'))]:
            detail+=f'<p>{title}</p><ul>'+''.join('<li>'+te(x)+'</li>' for x in a.get(field,[]))+'</ul>'
        detail+=f'<p>{L("候选 NAICS 对应", "Candidate NAICS mappings")}</p><ul>'+''.join('<li>'+e(str(x['code'])+' ('+x['match_type']+')')+' · '+te(x.get('note',''))+'</li>' for x in a.get('naics',[]))+'</ul>'
        activities+=f'<li id="ref-{e(id)}">{detail}</li>'
    return f'''<section id="references"><h2>{L('数据与参照 · 行业与产业链','Data and references · Industries and supply chains')}</h2>
<p>{L('参照记录不是研究结论。下面核对技术复核记录与当前登记内容的指纹，不在网站构建时重新核对原始申报或分部数值；技术记录不等于人工确认。','Reference records are not research conclusions. This build checks review fingerprints against registered content; it does not recheck original filings or segment values. Technical records are not human confirmation.')}</p>
<p>{L('业务映射不能用于收入分摊。逐条查看对应范围、有效期与复核状态；关系登记不证明采购份额、独家关系或完整历史。','Business mappings do not allocate revenue. Check each record’s scope, validity and review status; registered relationships do not establish procurement shares, exclusivity or full history.')}</p>
<p><a href="https://www.census.gov/naics/">{L('NAICS 官方分类入口','Official NAICS classification')}</a> · {L('本地完整分类表不随网站再分发；以下活动对应不是官方认定。','The full local classification table is not redistributed; the activity mappings below are not official determinations.')}</p>
<details><summary>{L('细分业务定义','Business activity definitions')} · {len(index['activities'])}</summary><ul>{activities}</ul></details>
{relationship_view(index, studies)}
</section>'''


def company_reference_part(result: dict, index: dict, studies=None) -> str:
    companies = result.get('results', {}).get('companies', [])
    if result.get('branch') != 'company' or len(companies) != 1:
        return ''
    eid = index['by_cik'].get(str(int(companies[0]['cik'])))
    if not eid:
        return ''
    return relationship_view(index, studies, prefix='../../', initial_entity=eid, embedded=True)
