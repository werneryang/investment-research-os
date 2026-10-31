"""Two-level browsing: the home page lists objects and their subtypes; each object page lists studies by
subtype and question. Both read the same paired routes as the full filter page (research.html)."""
from __future__ import annotations

from typing import Any

from .catalog import study_view
from .common import e, shell
from .discovery import label
from .i18n import L, is_en, te, tx
from .renderers import get_renderer


def _members(content):
    return {sid for c in content.get('collections', {}).values() for sid in c['members']}


def _primary(rec):
    return next((r for r in rec['routes'] if r.get('primary')), None)


def _end(cutoff: str) -> str:
    return cutoff + '-12-31' if len(cutoff) == 4 else cutoff + '-31' if len(cutoff) == 7 else cutoff


def _shelves(content, model):
    """每个对象子类：主归属在此的研究（direct），以及只有次要入口在此的研究（related）。"""
    members = _members(content)
    direct: dict[tuple[str, str], list[dict]] = {}
    related: dict[tuple[str, str], set[str]] = {}
    for rec in model['studies']:
        if rec['id'] in members:
            continue
        main = _primary(rec)
        if main:
            direct.setdefault((main['object'], main['subject']), []).append(rec)
        for r in rec['routes']:
            if r['available'] and not (main and (r['object'], r['subject']) == (main['object'], main['subject'])):
                related.setdefault((r['object'], r['subject']), set()).add(rec['id'])
    return direct, related


def _cap_state(model, obj):
    states = {c['state'] for c in model['capabilities'] if c['routes'][0]['object'] == obj}
    if 'data' in states:
        return L('已有数据', 'data available')
    if 'registered' in states:
        return L('数据已登记', 'data registered')
    return L('规划中', 'planned') if 'planned' in states else ''


def _company_name(rec):
    title = tx(rec['title'])
    for sep in ('：', ': '):
        if sep in title:
            return title.split(sep, 1)[0]
    return title


def home_page(content, model, latest, build):
    tax = content['classification']
    members = _members(content)
    leads = {c['lead']: c for c in content.get('collections', {}).values()}
    direct, related = _shelves(content, model)
    published = [r for r in model['studies'] if r['published'] and r['id'] not in members]
    companies = [r for r in model['studies'] if r['published'] and r['id'] in members]
    cutoffs = [str(i['result']['data_cutoff']) for i in latest.values() if i['result'].get('data_cutoff')]
    newest = max(cutoffs, key=_end) if cutoffs else '—'
    counts = L(f'{len(published)} 项研究', f'{len(published)} studies')
    if companies:
        counts += L(f' + {len(companies)} 家公司财报', f' + {len(companies)} company filings')
    meta = L(f'{counts} · 最新数据截至 {e(newest)} · 个人研究记录，不构成投资建议',
             f'{counts} · latest data {e(newest)} · personal research record, not investment advice')

    questions = []
    for q, v in tax['questions'].items():
        n = sum(any(r['available'] and r['question'] == q for r in rec['routes']) for rec in published)
        if n:
            questions.append((n, f'<a class="pill" href="research.html?question={e(q)}">{e(label(v["name"]))} <span>{n}</span></a>'))
    pills = ''.join(p for _, p in sorted(questions, key=lambda x: -x[0]))

    cards, empty = [], []
    for obj, v in tax['objects'].items():
        name = e(label(v['name']))
        own = [r for s in v['children'] for r in direct.get((obj, s), []) if r['published']]
        if not own:
            extra = len({sid for s in v['children'] for sid in related.get((obj, s), set())})
            hint = L('、', ', ').join(x for x in (_cap_state(model, obj), L(f'另见 {extra} 项', f'{extra} related') if extra else '') if x)
            empty.append(f'<a href="browse/{e(obj)}/">{name}</a>'
                         + (f'<span class="muted">{L(f"（{hint}）", f" ({hint})")}</span>' if hint else ''))
            continue
        rows, firms = [], 0
        for s, sv in sorted(v['children'].items(), key=lambda x: not direct.get((obj, x[0]))):
            shelf = direct.get((obj, s), [])
            n = sum(r['published'] and r['id'] not in leads for r in shelf)
            pending = sum(not r['published'] for r in shelf)
            extra = len(related.get((obj, s), set()))
            only_leads = shelf and all(r['id'] in leads for r in shelf)  # 合集另列一行
            if (n or pending or extra) and not only_leads:
                count = str(n) if n else L(f'另见 {extra}', f'{extra} related') if extra else L('未发布', 'unpublished')
                rows.append(f'<li><a href="browse/{e(obj)}/#{e(s)}">{e(label(sv))}</a><span class="muted">{count}</span></li>')
            for rec in shelf:
                c = leads.get(rec['id'])
                listed = [r for r in companies if c and r['id'] in c['members']]
                if not listed:
                    continue
                firms += len(listed)
                links = ' · '.join(f'<a href="studies/{e(r["id"])}/">{e(_company_name(r))}</a>' for r in listed)
                rows.append(f'<li><a href="browse/{e(obj)}/#{e(s)}">{te(c["name"])}</a><span class="muted">{L(f"{len(listed)} 家", f"{len(listed)}")}</span></li>'
                            f'<li class="collection-links"><span class="muted">{L("直达公司", "Go to a company")}</span><p>{links}</p></li>')
        refs = [m for m in model['references'] if any(r['object'] == obj for r in m['routes'])]
        if refs:
            n = sum(m['record_count'] for m in refs)
            rows.append(f'<li><a href="browse/{e(obj)}/#references">{L("参照资料（不计入研究）", "Reference materials (not studies)")}</a>'
                        f'<span class="muted">{L(f"{n} 条", f"{n} records")}</span></li>')
        studies = sum(r['id'] not in leads for r in own)
        count = L(' · ', ' · ').join(x for x in (L(f'{studies} 项', f'{studies} studies') if studies else '',
                                                 L(f'{firms} 家公司', f'{firms} companies') if firms else '') if x)
        cards.append(f'<section class="object-card"><h2><a href="browse/{e(obj)}/">{name} ›</a>'
                     f'<span class="muted">{count}</span></h2><ul>{"".join(rows)}</ul></section>')
    none = (f'<p class="small muted">{L("尚无研究：", "No studies yet: ")}{" · ".join(empty)}</p>') if empty else ''
    loose = sum(not _primary(r) for r in published)
    if loose:
        none += (f'<p class="small"><a href="research.html#object-unclassified">'
                 f'{L(f"{loose} 项研究尚未分类", f"{loose} unclassified studies")}</a></p>')
    search = (f'<form class="home-search" action="research.html" method="get" role="search">'
              f'<input type="search" name="search" aria-label="{L("搜索研究", "Search research")}" '
              f'placeholder="{L("搜索研究、问题或公司，例如 估值、收益率曲线、NVIDIA", "Search studies, questions or companies, e.g. valuation, yield curve, NVIDIA")}">'
              f'<button type="submit">{L("搜索", "Search")}</button><a href="research.html">{L("高级筛选", "Advanced filters")}</a></form>')
    body = (f'<header class="hero"><div class="wrap"><h1>Investment Research OS</h1>'
            f'<p class="tagline">{L("用公开数据做可复现的美国市场研究：利率、资产、行业与公司。每项结果附数据来源、检查与适用范围。", "Reproducible research on US markets from public data: rates, asset classes, industries and companies. Every result carries its sources, checks and scope.")}</p>'
            f'<p class="small muted">{meta}</p></div></header><main class="wrap home">{search}'
            f'<p class="question-pills"><span class="muted">{L("按问题", "By question")}</span>{pills}</p>'
            f'<div class="object-cards">{"".join(cards)}</div>{none}'
            f'<p class="small home-more"><a href="research.html#data-plans">{L("数据与规划", "Data and plans")}</a> · '
            f'<a href="sources.html#references">{L("分类与产业关系资料", "Classifications and business relationships")}</a> · '
            f'<a href="map.html">{L("研究能力地图", "Capability map")}</a></p></main>')
    return shell('Investment Research OS', body, build, page='index.html', active='index.html')


def _badge(view):
    if view is None:
        return ''
    if view.failed:
        cls, text = 'bad', L('检查未通过', 'Failed checks')
    elif view.limited:
        cls, text = 'warn', L('有限制', 'Limited')
    else:
        return ''
    tip = L('；', '; ').join(n.text for n in view.notices if n.level in ('fail', 'warn'))
    return f' <span class="limit-badge {cls}" title="{e(tip)}">{text}</span>'


def _href(route, up):
    return up + ('../' if is_en() and route['report'] else '') + route['href']


def object_page(content, model, latest, build, obj, frequency=None):
    tax = content['classification']
    v = tax['objects'][obj]
    up = '../../'
    members = _members(content)
    direct, related = _shelves(content, model)
    by_id = {r['id']: r for r in model['studies']}
    qnames = {q: label(x['name']) for q, x in tax['questions'].items()}
    views = {sid: study_view(sid, latest[sid], content['studies'].get(sid, {}), frequency) for sid in latest}

    def row(rec, extra=''):
        view = views.get(rec['id'])
        if not view:
            return f'<li class="shelf-row muted">{te(rec["title"])} · {L("尚未发布", "Not published")}</li>'
        return (f'<li class="shelf-row"><div><a href="{up}studies/{e(rec["id"])}/">{view.title}</a>{_badge(view)}'
                f'<p>{view.finding}</p>{extra}</div><span class="small muted nowrap">{L("截至", "Data to")} {e(view.cutoff)}</span></li>')

    def collection(lead):
        out = []
        for c in content.get('collections', {}).values():
            if c['lead'] != lead:
                continue
            heads = [L('公司', 'Company'), L('财年末', 'Fiscal year end'), L('营收（十亿美元）', 'Revenue (USD bn)'), L('同口径同比', 'Comparable YoY')]
            trs = []
            for sid in c['members']:
                item = latest.get(sid)
                if not item:
                    continue
                renderer = get_renderer(item['result']['branch'])
                cells = renderer.summary_row(item['result']) if renderer.summary_row else ['—'] * 3
                trs.append(f'<tr><td><a href="{up}studies/{e(sid)}/">{e(_company_name(by_id[sid]))}</a>{_badge(views[sid])}</td>'
                           + ''.join(f'<td>{x}</td>' for x in cells) + '</tr>')
            if trs:
                out.append(f'<div class="scroll"><table><thead><tr>{"".join(f"<th>{h}</th>" for h in heads)}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>')
        return ''.join(out)

    sections, quiet, shown, total, companies = [], [], [], 0, 0
    leads = {c['lead']: c for c in content.get('collections', {}).values()}
    order = sorted(v['children'], key=lambda s: not direct.get((obj, s)))
    for s in order:
        own = direct.get((obj, s), [])
        shelf: dict[str, list[str]] = {}
        main_q = {}
        for rec in own:
            q = _primary(rec)['question']
            main_q[rec['id']] = q
            shelf.setdefault(q, []).append(row(rec, collection(rec['id'])))
        also: dict[tuple[str, str], list[str]] = {}
        for sid in [r['id'] for r in model['studies']]:
            rec = by_id[sid]
            if sid in members:
                continue
            for r in rec['routes']:
                if r['object'] != obj or r['subject'] != s or not r['available'] or main_q.get(sid) == r['question']:
                    continue
                topic = label(tax['questions'][r['question']]['children'][r['topic']])
                links = also.setdefault((r['question'], sid), [])
                link = f'<a href="{e(_href(r, up))}">{e(topic)}</a>'
                if link not in links:
                    links.append(link)
        for (q, sid), links in also.items():
            shelf.setdefault(q, []).append(f'<li class="shelf-row see-also"><div><span class="muted">{L("另见", "See also")}</span> '
                                           f'{te(by_id[sid]["title"])} › {L("、", ", ").join(links)}</div></li>')
        if not shelf:
            quiet.append(e(label(v['children'][s])))
            continue
        shown.append(s)
        published = sum(r['published'] and r['id'] not in leads for r in own)
        firms = sum(sid in latest for r in own if r['id'] in leads for sid in leads[r['id']]['members'])
        total, companies = total + published, companies + firms
        count = L(' · ', ' · ').join(x for x in (L(f'{published} 项', f'{published}') if published else '',
                                                 L(f'{firms} 家公司', f'{firms} companies') if firms else '') if x) \
            or (L('暂无专门研究', 'No dedicated study') if not own else L('尚未发布', 'Not published'))
        # 本子类研究的主问题在前，只有「另见」入口的问题在后
        ordered = sorted((q for q in tax['questions'] if q in shelf), key=lambda q: q not in main_q.values())
        groups = ''.join(f'<h3>{e(qnames[q])}</h3><ul class="shelf-rows">{"".join(shelf[q])}</ul>' for q in ordered)
        sections.append(f'<section class="subject" id="{e(s)}"><h2>{e(label(v["children"][s]))} <span class="muted">{count}</span></h2>{groups}</section>')

    refs = [m for m in model['references'] if any(r['object'] == obj for r in m['routes'])]
    if refs:
        items = ''.join(f'<li><a href="{up}{e(next(r for r in m["routes"] if r["object"] == obj)["href"])}">{e(label(m["title"]))}</a>'
                        f' · {m["record_count"]} {L("条登记记录", "registered records")}</li>' for m in refs)
        sections.append(f'<section class="subject" id="references"><h2>{L("参照资料", "Reference materials")} <span class="muted">{L("不计入研究", "not counted as studies")}</span></h2><ul>{items}</ul></section>')
    states = {'planned': L('规划中', 'Planned'), 'data': L('已有数据，尚无研究', 'Data available; no study'),
              'registered': L('数据已登记，本次构建未取得', 'Data registered; unavailable in this build')}
    caps = [c for c in model['capabilities'] if c['routes'][0]['object'] == obj]
    if caps:
        items = ''.join(f'<li>{e(label(v["children"][c["routes"][0]["subject"]]))} · {e(qnames[c["routes"][0]["question"]])} · '
                        f'{states[c["state"]]}<span class="small muted"> · {e(label(c["routes"][0]["scope"]))}</span></li>' for c in caps)
        sections.append(f'<section class="subject" id="data-plans"><h2>{L("数据与规划", "Data and plans")}</h2><ul>{items}</ul></section>')

    jump = ''.join(f'<a class="pill" href="#{e(s)}">{e(label(v["children"][s]))}</a>' for s in shown)
    quiet_line = f'<p class="small muted">{L("暂无内容：", "Nothing yet: ")}{L("、", ", ").join(quiet)}</p>' if quiet else ''
    others = ' · '.join(f'<a href="../{e(k)}/">{e(label(x["name"]))}</a>' for k, x in tax['objects'].items() if k != obj)
    name = label(v['name'])
    found = L('、', ', ').join(x for x in (L(f'{total} 项研究', f'{total} studies') if total else '',
                                           L(f'{companies} 家公司', f'{companies} companies') if companies else '') if x)
    intro = L(f'{found}，按子类与研究问题列出。', f'{found}, listed by subtype and research question.') if found else \
        L('尚无以此为主归属的研究；下方列出相关入口、数据与规划。', 'No studies have this as their primary object; related entries, data and plans are listed below.')
    body = (f'<header class="hero"><div class="wrap"><nav class="crumbs small"><a href="{up}index.html">{L("首页", "Home")}</a> › {e(name)}</nav>'
            f'<h1>{e(name)}</h1><p class="tagline">{intro}</p></div></header><main class="wrap object-page">'
            f'<p class="question-pills">{jump}<a href="{up}research.html?object={e(obj)}">{L("按问题、期间与频率筛选", "Filter by question, period and frequency")} ›</a></p>'
            f'{quiet_line}{"".join(sections)}<p class="small home-more">{L("其他对象：", "Other objects: ")}{others}</p></main>')
    return shell(f'{name} · Investment Research OS', body, build, page=f'browse/{obj}/', active='index.html')
