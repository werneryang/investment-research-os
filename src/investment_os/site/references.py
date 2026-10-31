"""Publish registered reference metadata; never turn candidate relationships into facts."""
from pathlib import Path
from ..supply_chain.catalog import load_catalog, fingerprint
from .common import e
from .i18n import L, te


def reference_page_part(root: Path) -> str:
    if not (root/'config/supply_chain/activities.yaml').exists():
        return '<section id="references"><h2>'+L('数据与参照','Data and references')+'</h2><p>'+L('本次构建没有参照记录。','No reference records in this build.')+'</p></section>'
    cat=load_catalog(root)
    def technical(id):
        record=cat.technical.get(id)
        if not record:return L('无技术复核记录','No technical review record')
        if fingerprint(cat,id)!=record['fingerprint']:return L('复核记录已失效','Review record is stale')
        return L('技术复核记录：','Technical review record: ')+record['result']+' · '+str(record['reviewed_at'])
    def name(id):return cat.entities.get(id,cat.activities.get(id,{})).get('name',id)
    def sources(item):
        links=[]
        for cid in item.get('claims',[]):
            claim=cat.claims[cid]
            doc=cat.documents.get(claim.get('document')) or next((d for d in cat.documents.values() if d['accession']==claim.get('accession')),None)
            link=f'<a href="{e(doc["url"])}">{e(cid)}</a>' if doc else e(cid)
            links.append('<li>'+link+' · '+e(technical(cid))+' · '+e(claim.get('review_status','candidate'))+'</li>')
        return '<ul>'+''.join(links)+'</ul>'
    def record(id,item,label):
        status=technical(id)
        limits=(cat.technical.get(id) or {}).get('limits','')
        validity=f"{item.get('valid_from') or '?'} — {item.get('valid_to') or '?'}"
        body=f'<strong>{label}</strong><p>{e(status)} · {L("人工状态","Human review")}: {e(item.get("review_status","candidate"))}</p>'
        body+=f'<p>{L("有效期","Validity")}: {e(validity)} · {e(item.get("match",item.get("type","")))}</p>'
        for text in (item.get('scope'),item.get('product'),item.get('market'),item.get('note'),limits):
            if text:body+='<p>'+te(text)+'</p>'
        return f'<li id="ref-{e(id)}">{body}<details><summary>{L("证据及逐条复核状态","Evidence and review status")}</summary>{sources(item)}</details></li>'
    activities=''
    for id,a in cat.activities.items():
        detail=f'<strong>{te(a["name"])}</strong><p>{te(a["definition"])}</p>'
        for field,title in [('includes',L('包含','Includes')),('excludes',L('不包含','Excludes'))]:
            detail+=f'<p>{title}</p><ul>'+''.join('<li>'+te(x)+'</li>' for x in a.get(field,[]))+'</ul>'
        detail+=f'<p>{L("候选 NAICS 对应", "Candidate NAICS mappings")}</p><ul>'+''.join('<li>'+e(str(x['code'])+' ('+x['match_type']+')')+' · '+te(x.get('note',''))+'</li>' for x in a.get('naics',[]))+'</ul>'
        activities+=f'<li id="ref-{e(id)}">{detail}</li>'
    links=''.join(record(id,item,te(name(item['entity']))+' → '+te(name(item['activity']))) for id,item in cat.links.items())
    relations=''
    for id,item in cat.relations.items():
        ends=[item['provider'],item['recipient']] if 'provider' in item else item['parties']
        relations+=record(id,item,(' → ' if 'provider' in item else ' ↔ ').join(te(name(x)) for x in ends))
    return f'''<section id="references"><h2>{L('数据与参照 · 行业与产业链','Data and references · Industries and supply chains')}</h2>
<p>{L('参照记录不是研究结论。下面核对技术复核记录与当前登记内容的指纹，不在网站构建时重新核对原始申报或分部数值；技术记录不等于人工确认。','Reference records are not research conclusions. This build checks review fingerprints against registered content; it does not recheck original filings or segment values. Technical records are not human confirmation.')}</p>
<p>{L('业务映射全部只是部分对应，有效期未知，不能用于收入分摊。公司间关系仍为候选，不证明采购份额、独家关系或完整历史。','Business mappings are partial, with unknown validity periods; they do not allocate revenue. Company relationships remain candidates and do not establish procurement shares, exclusivity or full history.')}</p>
<p><a href="https://www.census.gov/naics/">{L('NAICS 官方分类入口','Official NAICS classification')}</a> · {L('本地完整分类表不随网站再分发；以下活动对应不是官方认定。','The full local classification table is not redistributed; the activity mappings below are not official determinations.')}</p>
<details><summary>{L('细分业务定义','Business activity definitions')} · {len(cat.activities)}</summary><ul>{activities}</ul></details>
<details id="business-mappings"><summary>{L('分部与业务映射','Segment-to-business mappings')} · {len(cat.links)}</summary><ul>{links}</ul></details>
<details id="business-relations"><summary>{L('候选公司关系','Candidate company relationships')} · {len(cat.relations)}</summary><ul>{relations}</ul></details>
</section>'''


def company_reference_index(root: Path) -> dict[str, list[str]]:
    """Associate registered segment mappings with their disclosed issuer CIK."""
    if not (root / 'config/supply_chain/activities.yaml').exists():
        return {}
    cat = load_catalog(root)
    out: dict[str, list[str]] = {}
    for identifier, link in cat.links.items():
        entity = cat.entities[link['entity']]
        company = cat.entities.get(entity.get('parent'), entity)
        if company.get('cik'):
            out.setdefault(str(int(company['cik'])), []).append(identifier)
    return out


def company_reference_part(result: dict, index: dict[str, list[str]]) -> str:
    companies = result.get('results', {}).get('companies', [])
    if result.get('branch') != 'company' or len(companies) != 1:
        return ''
    cik = str(int(companies[0]['cik']))
    links = index.get(cik, [])
    body = (L('部分对应；有效期未知，不能分摊收入。技术复核不等于人工确认。',
              'Partial mappings with unknown validity; they cannot allocate revenue. Technical review is not human confirmation.')
            + '<ul>' + ''.join(f'<li><a href="../../sources.html#ref-{e(i)}">{e(i)}</a></li>' for i in links) + '</ul>'
            if links else L('尚未收录该公司的分部与业务映射。', 'Segment-to-business mappings for this company have not been registered.'))
    return f'<section id="company-business"><h2>{L("分部与业务关联", "Segments and business activities")}</h2>{body}</section>'
