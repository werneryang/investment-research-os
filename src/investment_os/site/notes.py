"""Chinese-only report pages and metadata-only discovery cards; not study runs."""
from pathlib import Path

from ..notes import load_notes, parser
from .common import e, shell
from .i18n import L, is_en, use


def note_catalog(notes, subjects):
    records = []
    for n in notes:
        eid = subjects['by_cik'].get(str(n['cik']))
        if not eid:
            raise ValueError('研究报告公司尚未登记')
        structure = 'value-chain' in n['id']
        route = {'object':'company', 'subject':'issuer', 'question':'structure' if structure else 'fundamentals',
                 'topic':'relationships' if structure else 'financials', 'target':'research-note',
                 'scope':{'zh':'中文研究报告；公开公司事实、计算与标注的推断；不等于可复现 study',
                          'en':'Chinese research report: company facts, calculations and labelled inferences; not a reproducible study'},
                 'entity_ids':[eid], 'available':True, 'primary':True, 'report':True, 'href':n['href']}
        records.append({'id':n['id'], 'kind':'note', 'title':n['title'], 'company':n['company'], 'date':n['date'],
                        'published':True, 'result_type':'research_note', 'scope':{'start':n['date'],'end':n['date']},
                        'cutoff':n['date'], 'href':n['href'], 'routes':[route], 'entity_ids':[eid]})
    return records


def discovery_cards(records):
    if not records:
        return ''
    import json
    rows = []
    for r in records:
        href = ('../' if is_en() else '') + r['href']
        rows.append(f'<li class="research-record note-record" data-record="{e(json.dumps(r,ensure_ascii=False))}">'
                    f'<div class="result-heading"><h3><a rel="nofollow" lang="zh-CN" href="{e(href)}">{e(r["title"])}</a></h3>'
                    f'<span class="result-status">{L("研究报告（中文）","Research report (Chinese)")}</span></div>'
                    f'<p class="small muted">{e(r["company"])} · {L("报告日期","Report date")} {e(r["date"])}</p>'
                    f'<p>{L("公开可访问；请求搜索引擎不索引。公司数字与标注推断不等于已复现的研究结论。", "Publicly accessible; search engines are requested not to index it. Figures and labelled inferences are not a pinned-input reproduction claim.")}</p></li>')
    return (f'<details class="result-group" id="research-notes"><summary>{L("研究报告","Research reports")} · '
            f'<span class="summary-count">{len(rows)}</span><span class="summary-alerts"></span></summary>'
            f'<ul class="research-list">{"".join(rows)}</ul></details>')


def company_notes(eid, records, prefix='../../'):
    rows = [r for r in records if eid in r['entity_ids']]
    if not rows:
        return ''
    pre = ('../' if is_en() else '') + prefix
    return ('<section class="company-notes"><h2>' + L('研究报告（中文）','Research reports (Chinese)') + '</h2><ul>'
            + ''.join(f'<li><a rel="nofollow" lang="zh-CN" href="{e(pre+r["href"])}">{e(r["title"])}</a> · {e(r["date"])}</li>' for r in rows)
            + '</ul></section>')


def write_pages(out: Path, notes, build):
    def write(page, title, body):
        dest = out / page / 'index.html'
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = (f'<main class="wrap"><nav class="crumbs"><a href="{"../"*page.count("/")}research.html">全部研究</a> › 研究报告</nav>'
                   f'<p class="small muted">中文研究报告 · 公开链接可访问 · 请求不被搜索引擎索引；不是私有存储或访问控制。</p>{body}</main>')
        with use('zh', {}, set()):
            dest.write_text(shell(title, content, build, page=page, noindex=True, chinese_only=True), encoding='utf-8')
    groups = {}
    md = parser()
    for n in notes:
        write(n['href'], n['title'], f'<p>{e(n["company"])} · {e(n["date"])}</p><article class="research-note">{md.render(n["body"])}</article>')
        groups.setdefault(f'notes/companies/{n["company"]}/{n["date"]}/', []).append(n)
        groups.setdefault(f'notes/companies/{n["company"]}/', []).append(n)
    groups['notes/'] = list(notes)
    for page, rows in groups.items():
        rows = sorted(rows, key=lambda n:(n['date'],n['id']), reverse=True)
        depth = page.count('/')
        body = '<h1>研究报告</h1><ul>' + ''.join(f'<li>{e(n["company"])} · {e(n["date"])} · <a href="{"../"*depth}{e(n["href"])}">{e(n["title"])}</a></li>' for n in rows) + '</ul>'
        write(page, '研究报告', body)


def company_directory(records):
    if not records:
        return ''
    pre = '../../../' if is_en() else '../../'
    return ('<section id="company-reports"><h2>' + L('研究报告（中文）','Research reports (Chinese)')
            + '</h2><p><a href="../../research.html?object=company&amp;result_type=research_note">'
            + L('按公司、报告日期与关键词筛选','Filter by company, report date and keywords') + '</a></p><ul>'
            + ''.join(f'<li>{e(r["company"])} · {e(r["date"])} · <a rel="nofollow" lang="zh-CN" href="{e(pre+r["href"])}">{e(r["title"])}</a></li>' for r in records)
            + '</ul></section>')
