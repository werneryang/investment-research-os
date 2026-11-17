"""Quarterly earnings pages: the quarters, comparability notes, outlooks against actuals, and what is not covered.

Every company-specific row, label, chart and sentence comes from the registration profile carried in the result (results.profile)."""
from .common import e, stat
from .company import table
from .i18n import L, is_en
from .visuals import nice_ticks

STATUS = {'done': ('已完成', 'Done'), 'data_gap': ('数据不足', 'Data gap'), 'judgment': ('需人工判断', 'Needs judgement')}
RESULT = {'within_range': ('在区间内', 'Within the range'), 'above_range': ('高于区间', 'Above the range'),
          'below_range': ('低于区间', 'Below the range'), 'difference_only': ('只列差值，未定义容差', 'Difference only, no tolerance defined'),
          'pending': ('尚未到期', 'Not yet due'), 'not_comparable': ('口径不同，不逐项对照', 'Different basis, not compared')}


def _lang(d):
    return (d or {}).get('en' if is_en() else 'zh', '')


def tl(x):
    """Bilingual {zh, en} text for the current language; a plain string is returned as is."""
    return _lang(x) if isinstance(x, dict) else str(x)


NUM_EN = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
NUM_ZH = '零一二三四五六七八九十'


def _count(n):
    return (NUM_ZH[n] if n <= 10 else str(n), NUM_EN[n].capitalize() if n <= 10 else str(n))


def _prof(res):
    return res['profile']


def _quarter(res, qid):
    return next(q for q in res['quarters'] if q['period'] == qid)


def _qname(res, qid):
    return tl(next(q for q in _prof(res)['quarters'] if q['id'] == qid)['name'])


def _pct_keys(p):
    return {r['key'] for r in p.get('ratios') or []} | {'gross_margin', 'op_margin'}


def bn(v, digits=2):
    return '—' if v is None else f'{v / 1e3:,.{digits}f}'.replace('-', '−')


def pct(v, digits=1, signed=False):
    return '—' if v is None else (f'{v:+.{digits}f}%' if signed else f'{v:.{digits}f}%').replace('-', '−')


def pp(v):
    return '—' if v is None else f'{v:+.1f} pp'.replace('-', '−')


def _link(doc_id, docs, label=None):
    d = docs.get(doc_id)
    if not d:
        return e(doc_id)
    return f'<a href="{e(d["url"])}">{e(label or d["form"])}</a>'


def line_chart(rows, series, title, unit, signed=False, digits=0):
    """Accessible SVG line chart over the five quarters; colours from the shared tokens in fixed order."""
    values = [r[m] for r in rows for m, _ in series if r.get(m) is not None]
    if not values:
        return ''
    ticks = nice_ticks(min(0, min(values)), max(0, max(values)), 4)
    lo, hi = ticks[0], ticks[-1]
    x = lambda i: 65 + i * 625 / max(1, len(rows) - 1)
    y = lambda v: 205 - (v - lo) * 165 / (hi - lo)
    fmt = lambda v: (f'{v:,.{digits}f}' + ('%' if unit == '%' else '')).replace('-', '−')
    out = (f'<figure class="chart-card"><h4>{e(title)} · {e(unit)}</h4><svg class="dotplot" viewBox="0 0 740 250" role="img" '
           f'aria-label="{e(title)}"><title>{e(title)}</title>')
    for t in ticks:
        out += (f'<line class="grid" x1="65" x2="690" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                f'<text class="axis" x="58" y="{y(t) + 4:.1f}" text-anchor="end">{fmt(t)}</text>')
    for slot, (m, label) in enumerate(series, 1):
        path = ''
        for i, r in enumerate(rows):
            v = r.get(m)
            if v is None:
                continue
            path += f'{"L" if path else "M"}{x(i):.1f},{y(v):.1f} '
            out += (f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3.5" style="fill:var(--c{slot});stroke:var(--panel);stroke-width:1">'
                    f'<title>{e(r["label"])} · {e(label)}: {fmt(v)}</title></circle>')
        out += f'<path d="{path}" fill="none" style="stroke:var(--c{slot})" stroke-width="2"/>'
    for i, r in enumerate(rows):
        out += f'<text class="axis" x="{x(i):.1f}" y="230" text-anchor="middle">{e(r["label"])}</text>'
    legend = ' '.join(f'<span class="legend-item"><i style="background:var(--c{slot})"></i>{e(label)}</span>' for slot, (_, label) in enumerate(series, 1))
    return out + f'</svg><p class="chart-note">{legend}</p></figure>'


def _charts(res):
    rows, out = res['quarters'], ''
    for c in _prof(res)['charts']:
        usd = c['unit'] == 'usd_bn'
        view = [{**r, **{f'{sr["key"]}__v': (r[sr['key']] / 1e3 if usd and r.get(sr['key']) is not None else r.get(sr['key']))
                         for sr in c['series']}} for r in rows]
        out += line_chart(view, [(f'{sr["key"]}__v', tl(sr['label'])) for sr in c['series']], tl(c['title']),
                          L('十亿美元', 'USD bn') if usd else '%', digits=0)
    return out


def _quarter_table(res):
    rows = res['quarters']
    comp = res['comparison']
    p = _prof(res)
    heads = [L('指标', 'Metric')] + [r['label'] + ('*' if r['derived'] else '') for r in rows] + [L('同比', 'YoY'), L('环比', 'QoQ')]
    pct_keys = _pct_keys(p)

    def line(key, growth):
        kind = 'pct' if key in pct_keys else 'bn'
        cells = [bn(r.get(key)) if kind == 'bn' else pct(r.get(key)) for r in rows]
        if kind == 'pct':
            yoy, qoq = comp['yoy']['margin_pp'].get(key), comp['qoq']['margin_pp'].get(key)
            tail = [pp(yoy) if key in comp['yoy']['margin_pp'] else '—', pp(qoq) if key in comp['qoq']['margin_pp'] else '—']
        else:
            yoy = comp['yoy']['pct'].get(key) if growth else None
            qoq = comp['qoq']['pct'].get(key) if growth else None
            tail = [pct(yoy, signed=True) if yoy is not None else '—', pct(qoq, signed=True) if qoq is not None else '—']
        return [e(tl(p['metrics'][key])), *cells, *tail]

    n_zh, n_en = _count(len(rows))
    html = ('<h3 id="earnings-quarterly">' + L(f'{n_zh}个季度的合并利润表', f'{n_en} quarters of consolidated results') + '</h3><p>'
            + L('金额单位为十亿美元，利润率为占同期收入的比例，同比、环比的利润率列为百分点。全部为报告口径（GAAP），含并购并表，不是有机增长。',
                'Amounts in USD billions; margins are percent of same-period revenue, with year-over-year and quarter-over-quarter margin changes in percentage points. '
                'All figures are as reported (GAAP) and include acquired operations; they are not organic growth.') + '</p>')
    related = ' · '.join(f'<a href="../{e(x["study"])}/">{e(_lang(x["label"]))}</a>' for x in res.get('related_studies', []))
    if related:
        html += '<p>' + L('相关研究：', 'Related research: ') + related + '</p>'
    html += table(heads, [line(t, True) if isinstance(t, str) else line(t['key'], t.get('growth', True)) for t in p['table']])
    derived = [q for q in p['quarters'] if q.get('derive')]
    base = L(f'同比对 {_qname(res, p["yoy_base"])}，环比对 {_qname(res, p["qoq_base"])}；—表示不适用。',
             f'Year over year compares with {_qname(res, p["yoy_base"])}, quarter over quarter with {_qname(res, p["qoq_base"])}; — means not applicable.')
    html += '<p class="small muted">' + ('* ' + ' '.join(tl(q['derive']['note']) for q in derived) + L('', ' ') if derived else '') + base + '</p>'
    return html


def _segment_table(res):
    rows = res['quarters']
    p = _prof(res)
    heads = [L('分部', 'Segment')] + [r['label'] + ('*' if r['derived'] else '') for r in rows]
    lines, names = [], {}
    for sg in p['segments']:
        name = tl(sg['name'])
        names[sg['op']] = name
        lines.append([e(name + L(' 营业利润', ' operating income')), *[bn(r[sg['op']]) for r in rows]])
        lines.append([e(name + L(' 利润率', ' margin')), *[pct(r[sg['margin']], sg.get('digits', 1)) for r in rows]])
    if p.get('unallocated'):
        names[p['unallocated']['key']] = tl(p['unallocated'].get('short') or p['unallocated']['label'])
        lines.append([e(tl(p['unallocated']['label'])), *[bn(r[p['unallocated']['key']]) for r in rows]])
    if p.get('share'):
        lines.append([e(tl(p['share']['label'])), *[pct(r[p['share']['key']]) for r in rows]])
    html = '<h3 id="earnings-segments">' + L('分部经营', 'Segment operations') + '</h3>' + table(heads, lines)
    delta = res['comparison'].get('segment_op_delta_yoy')
    if delta:
        parts = ' · '.join(f'{e(names.get(k, k))} {bn(v)}' for k, v in delta['delta'].items())
        html += ('<p>' + L('营业利润同比变动', 'Year-over-year change in operating income') + f' {bn(delta["total"])} {L("十亿美元 = ", "USD bn = ")}{parts}'
                 + L('（合计' + ('等于' if delta['reconciles'] else '不等于') + '营业利润变动）。', f' (the parts {"sum to" if delta["reconciles"] else "do not sum to"} the change).')
                 + '</p><p class="small muted">' + _lang(delta['caliber']) + '</p>')
    return html


def _times(v):
    return f'{v:.2f}×' if v is not None else '—'


def _cash_table(res):
    rows = res['quarters']
    p = _prof(res)
    heads = [L('指标', 'Metric')] + [r['label'] + ('*' if r['derived'] else '') for r in rows]
    cash = res['cash']
    lines = [[e(L('经营活动现金流', 'Operating cash flow')), *[bn(r['cfo']) for r in rows]],
             [e(L('现金资本开支（购置固定资产）', 'Cash capital expenditure (purchases of property and equipment)')), *[bn(r['cash_ppe']) for r in rows]],
             [e(L('自由现金流（发行人定义）', 'Free cash flow (issuer definition)')), *[bn(r['free_cash_flow']) for r in rows]],
             [e(L('现金资本开支 / 收入', 'Cash capex / revenue')), *[pct(r['capex_to_sales']) for r in rows]],
             [e(L('经营现金流 / 合并净利润', 'Operating cash flow / consolidated net income')), *[_times(r['cfo_to_consolidated_ni']) for r in rows]]]
    html = '<h3 id="earnings-cash">' + L('现金流与资本开支', 'Cash flow and capital expenditure') + '</h3>' + table(heads, lines)
    ytd, ttm = cash.get('year_to_date'), cash.get('trailing')
    zh = en = ''
    if ytd:
        lab = tl(ytd['label'])
        zh += (f'{lab}：经营现金流 {bn(ytd["cfo"])}、现金资本开支 {bn(ytd["cash_ppe"])} 十亿美元，经营现金流 / 现金资本开支 {_times(ytd["cfo_to_cash_ppe"])}；'
               f'经营现金流 / 合并净利润 {_times(ytd["cfo_to_consolidated_ni"])}。')
        en += (f'{lab}: operating cash flow USD {bn(ytd["cfo"])} bn, cash capex USD {bn(ytd["cash_ppe"])} bn, operating cash flow / cash capex '
               f'{_times(ytd["cfo_to_cash_ppe"])}; operating cash flow / consolidated net income {_times(ytd["cfo_to_consolidated_ni"])}. ')
    if ttm:
        zh += f'近四个季度自由现金流 {bn(ttm["free_cash_flow"])} 十亿美元。'
        en += f'Free cash flow over the last four quarters: USD {bn(ttm["free_cash_flow"])} bn.'
    if zh:
        html += '<p>' + L(zh, en.strip()) + '</p>'
    html += '<p class="small muted">' + _lang(cash['caliber']) + '</p>'
    bal = res['balance']
    heads2 = [L('资产负债表时点', 'Balance sheet date'), L('现金与有价证券', 'Cash and marketable securities'), L('长期债务', 'Long-term debt'),
              L('固定资产净额', 'Net property and equipment'), L('总资产', 'Total assets'), L('总权益', 'Total equity')]
    html += table(heads2, [[e(b['date']), bn(b['cash_and_securities']), bn(b['longterm_debt']), bn(b['PPE_net']), bn(b['total_assets']), bn(b['total_equity'])] for b in bal])
    html += '<p class="small muted">' + L('十亿美元', 'USD billions') + ('；' if not is_en() else '; ') * bool(p.get('balance_note')) + tl(p.get('balance_note') or '') + ('。' if not is_en() else '.') + '</p>'
    return html


def _bridges(res):
    b = res.get('bridges')
    if not b:
        return ''
    p = _prof(res)
    rows = res['quarters']
    no, ch = p.get('non_operating'), p.get('prior_year_charge')
    heads = [L('示意算术（税前）', 'Illustrative arithmetic (pretax)')] + [r['label'] for r in rows]
    lines = []
    if no:
        lab = tl(no['label'])
        lines = [[e(L('税前利润（报告）', 'Income before taxes (reported)')), *[bn(r['EBT']) for r in rows]],
                 [e(L(f'{lab}净损益', f'{lab[:1].upper()}{lab[1:]} gain (loss)')), *[bn(r[no['key']]) for r in rows]],
                 [e(L(f'税前利润剔除{lab}损益', f'Income before taxes excluding {lab}')), *[bn(b['ebt_ex_equity_securities'][r['period']]) for r in rows]]]
    html = table(heads, lines) if lines else ''
    if b.get('prior_year_charge_usd_m'):
        prior = _quarter(res, p['yoy_base'])
        lab = tl(ch['label'])
        html += ('<p>' + L(f'去年同期营业利润 {bn(prior["op_income"])} 加回约 {b["prior_year_charge_usd_m"] / 1e3:.1f} 十亿美元的{lab}为 {bn(b["prior_op_income_plus_charge"])}'
                            f'（利润率 {pct(b["prior_op_margin_plus_charge"])}）；本期营业利润较之 {pct(b["current_op_income_vs_prior_plus_charge_pct"], signed=True)}，利润率 {pp(b["current_vs_prior_margin_pp"])}。',
                            f'Prior-year operating income of USD {bn(prior["op_income"])} bn plus the roughly USD {b["prior_year_charge_usd_m"] / 1e3:.1f} bn {lab} is USD {bn(b["prior_op_income_plus_charge"])} bn '
                            f'(margin {pct(b["prior_op_margin_plus_charge"])}); current operating income is {pct(b["current_op_income_vs_prior_plus_charge_pct"], signed=True)} against that, with the margin {pp(b["current_vs_prior_margin_pp"])}.') + '</p>')
    return html + '<p class="small muted">' + _lang(b['caliber']) + '</p>'


def _notes(res):
    docs = {d['id']: d for d in res['documents']}
    p = _prof(res)
    out = '<h3 id="earnings-comparability">' + L('可比性与口径', 'Comparability and definitions') + '</h3><p>' + L(
        '下列事项决定哪些比较可以直接做、哪些不能。每条列出原文事实、本页的处理与限制；摘录逐字取自所引申报。',
        'These items decide which comparisons can be made directly and which cannot. Each gives the filing fact, how this page treats it and its limit; excerpts are verbatim from the cited filing.') + '</p>'
    for n in res['notes']:
        quotes = ''.join(f'<blockquote>{e(x)}</blockquote>' for x in n.get('excerpts') or [])
        src = f'<p class="small muted">{L("出处：", "Source: ")}{_link(n["document"], docs)}</p>'
        out += (f'<details open><summary>{e(_lang(n["title"]))}</summary><p>{e(_lang(n["fact"]))}</p>'
                f'<p><strong>{L("限制：", "Limit: ")}</strong>{e(_lang(n["limit"]))}</p>'
                + (f'<details><summary>{L("原文摘录", "Excerpts")}</summary>{quotes}</details>' if quotes else '') + src + '</details>')
    if res.get('bridges'):
        out += '<h4>' + L('示意性的税前算术', 'Illustrative pretax arithmetic') + '</h4>' + _bridges(res)
    fx, ps = res.get('fx'), res.get('per_share')
    cur = p['current']
    if fx or ps:
        title = (L('恒定汇率与每股收益', 'Constant currency and earnings per share') if fx and ps
                 else L('恒定汇率', 'Constant currency') if fx else L('每股收益', 'Earnings per share'))
        out += '<h4>' + title + '</h4>'
    if fx:
        out += table([L('项目', 'Item'), L('十亿美元', 'USD bn')],
                     [[e(L(f'{_qname(res, cur)}报告收入', f'{_qname(res, cur)} reported revenue')), bn(fx['reported_revenue'])],
                      [e(L('同比恒定汇率收入（发行人约 ' + str(fx['yoy_constant_currency_growth_pct_rounded']) + '% 同比）', f'Year-over-year constant-currency revenue (issuer: about {fx["yoy_constant_currency_growth_pct_rounded"]}% growth)')), bn(fx['yoy_constant_currency_revenue'])],
                      [e(L('环比恒定汇率收入（发行人约 ' + str(fx['qoq_constant_currency_growth_pct_rounded']) + '% 环比）', f'Quarter-over-quarter constant-currency revenue (issuer: about {fx["qoq_constant_currency_growth_pct_rounded"]}% growth)')), bn(fx['qoq_constant_currency_revenue'])]])
    if ps:
        now, before = ps[p['per_share']['current']], ps[p['per_share']['prior']]
        out += ('<p>' + L(f'稀释后每股收益（普通股）：{_qname(res, cur)} {now:.2f} 美元，去年同期 {before:.2f} 美元（发行人披露）。',
                          f'Diluted EPS (common): USD {now:.2f} in {_qname(res, cur)} versus USD {before:.2f} a year earlier (issuer disclosure).') + '</p>')
    return out


def _outlooks(res):
    docs = {d['id']: d for d in res['documents']}
    g = res.get('guidance')
    if not g:
        html = ('<h3 id="earnings-outlook">' + L('资本开支展望与实际', 'Capital expenditure outlooks versus actuals') + '</h3><p>'
                + L('没有登记资本开支展望。', 'No capital expenditure outlook is registered.') + '</p>')
    else:
        rows = []
        for o in g['observations']:
            target = (f'{o["low_usd_bn"]:,.0f}–{o["high_usd_bn"]:,.0f}' if o['kind'] == 'range' else f'≈{o["point_usd_bn"]:,.0f}' if o['kind'] == 'point' else '—')
            diff = '—' if o.get('difference_usd_bn') is None else f'{o["difference_usd_bn"]:+,.2f}'.replace('-', '−')
            rows.append([e(o['announced']), e(str(o['target_year'])), e(_lang(o['statement'])), target, L(*RESULT[o['result']]),
                         diff, f'{_link(o["document"], docs)}<details><summary>{L("摘录", "Excerpt")}</summary><blockquote>{e(o["excerpt"])}</blockquote></details>'])
        heads = [L('公布日', 'Announced'), L('目标年', 'Year'), L('发行人原文表述', 'Issuer statement'), L('区间 / 点值（十亿美元）', 'Range / point (USD bn)'),
                 L('与实际对照', 'Versus actual'), L('差值（十亿美元）', 'Difference (USD bn)'), L('出处', 'Source')]
        act = g['actual']
        html = ('<h3 id="earnings-outlook">' + L('资本开支展望与实际', 'Capital expenditure outlooks versus actuals') + '</h3><p>'
                + L(f'{act["year"]} 年现金资本开支实际为 {act["value"] / 1e3:,.2f} 十亿美元（年报现金流量表）。差值对区间为实际减区间中点，对点值为实际减点值。',
                    f'Actual {act["year"]} cash capital expenditure was USD {act["value"] / 1e3:,.2f} bn (annual-report cash-flow statement). The difference is actual minus the range midpoint, or minus the point value.') + '</p>'
                + table(heads, rows) + '<p class="small muted">' + _lang(g['tolerance_note']) + '</p>')
        rem = g.get('remaining_arithmetic')
        if rem:
            gr = _prof(res)['guidance_remaining']
            ytd = _prof(res)['year_to_date']['short']
            html += ('<p>' + L(f'同口径剩余额算术：{tl(gr["label"])}减去{tl(ytd)}现金资本开支 {rem["year_to_date_cash_ppe_usd_bn"]:,.2f}，为 {rem["low_usd_bn"]:,.2f}–{rem["high_usd_bn"]:,.2f} 十亿美元。',
                               f'Same-definition residual arithmetic: {tl(gr["label"])} less {tl(ytd)} cash capital expenditure of {rem["year_to_date_cash_ppe_usd_bn"]:,.2f} gives USD {rem["low_usd_bn"]:,.2f}–{rem["high_usd_bn"]:,.2f} bn.')
                     + ' ' + _lang(rem['caliber']) + '</p>')
    r = res.get('rpo')
    html += '<h3 id="earnings-backlog">' + L('收入积压订单', 'Revenue backlog') + '</h3>'
    if not r:
        return html + '<p>' + L('没有登记收入积压订单。', 'No revenue backlog is registered.') + '</p>'
    series = _prof(res)['rpo']['series']
    k0 = series[0]['key']
    heads2 = [L('日期', 'Date')] + [tl(sr['label']) for sr in series] + [tl(_prof(res)['rpo'].get('qoq_label') or L('环比', 'QoQ')), L('出处', 'Source')]
    rows2 = [[e(pt['date']), *[f'{pt[sr["key"]]:,.1f}' for sr in series],
              pct(pt[f'{k0}_qoq_pct'], signed=True) if pt[f'{k0}_qoq_pct'] is not None else '—', _link(pt['document'], docs)] for pt in r['points']]
    rec = r.get('recognition')
    return (html + table(heads2, rows2) + '<p>' + (tl(rec['statement']) + ' ' if rec and rec.get('statement') else '') + _lang(r['scope_change'])
            + '</p><p class="small muted">' + L('汇总余额不能按平均分摊成季度收入、利润或现金；合同级的时点、选择权和照付不议条款没有披露。',
                                                 'The aggregate balance cannot be spread evenly into quarterly revenue, profit or cash; contract-level timing, options and take-or-pay terms are not disclosed.') + '</p>')


def _coverage(res):
    heads = [L('类别', 'Status'), L('内容', 'Item')]
    order = ('done', 'data_gap', 'judgment')
    items = sorted(res['coverage'], key=lambda c: order.index(c['status']))
    intro = L('三类：已完成（本页已有结果）、数据不足（发行人没有披露或没有可核验的数据）、需人工判断（算术之外的判断或本研究未处理的外部材料）。数据不足和需判断的项目不给出结论。',
              'Three statuses: done (results are on this page), data gap (the issuer does not disclose it or no verifiable data was obtained) and needs judgement (judgement beyond arithmetic or external material this study did not handle). No conclusion is given for data-gap or judgement items.')
    return ('<h3 id="earnings-coverage">' + L('已覆盖与未覆盖', 'Covered and not covered') + '</h3><p>' + intro + '</p>'
            + table(heads, [[e(L(*STATUS[c['status']])), e(_lang(c['item']))] for c in items]))


def _sources(res):
    heads = [L('文件', 'Document'), L('期末', 'Period end'), 'Accession', L('EDGAR 接受时间', 'EDGAR accepted'), 'SHA256']
    rel, p = res['release'], _prof(res)
    form = rel.get('periodic_form', '10-Q')
    short, cur = p['short_name'], _qname(res, p['current'])
    note = L(f'{short} 于 {rel["ir_date"]} 发布{cur}业绩，{form} 于 {rel["form_10q_filed"]} 申报。',
             f'{short} released {cur} results on {rel["ir_date"]}; the {form} was filed on {rel["form_10q_filed"]}.')
    return ('<h3 id="earnings-sources">' + L('来源文件', 'Source documents') + '</h3><p>' + note + ' '
            + L('原文只保存在本机（不入库），登记里的 SHA256 固定了版本；数值核对在生成证据包时完成。',
                'The originals are kept only on the maintainer’s machine (not in the repository); the registered SHA256 pins each version and the checks run when the evidence bundle is built.') + '</p>'
            + table(heads, [[f'<a href="{e(d["url"])}">{e(d["form"])}</a>', e(d.get('period_end') or '—'), e(d['accession']), e(str(d['accepted_at'])), f'<code>{e(d["sha256"][:12])}…</code>'] for d in res['documents']]))


def _old_run_note():
    return ('<p class="small muted">' + L('这次运行早于财报研究的配置化（结果里没有 profile），不能用当前页面渲染；请见较新的运行。',
                                          'This run predates the configurable earnings profile (its result has no profile) and cannot be rendered by the current page; see a newer run.') + '</p>')


def details(r):
    res = r['results']
    if 'profile' not in res:
        return _old_run_note()
    return (_quarter_table(res) + _charts(res) + _segment_table(res) + _cash_table(res)
            + _notes(res) + _outlooks(res) + _coverage(res) + _sources(res))


def _stats(r):
    res = r['results']
    if 'profile' not in res:
        return ''
    p = _prof(res)
    cur = _quarter(res, p['current'])
    yoy = res['comparison']['yoy']
    return ('<div class="stats">' + stat(L(f'{cur["label"]} 收入（十亿美元）', f'{_qname(res, p["current"])} revenue (USD bn)'), bn(cur['revenue']), L(f'同比 {pct(yoy["pct"]["revenue"], signed=True)}（报告口径）', f'{pct(yoy["pct"]["revenue"], signed=True)} YoY (reported)'))
            + stat(L('营业利润率', 'Operating margin'), pct(cur['op_margin']), L(f'较去年同期 {pp(yoy["margin_pp"]["op_margin"])}', f'{pp(yoy["margin_pp"]["op_margin"])} YoY'))
            + stat(L('自由现金流（十亿美元）', 'Free cash flow (USD bn)'), bn(cur['free_cash_flow']), L('发行人定义', 'issuer definition'))
            + stat(L('未覆盖项', 'Not covered'), str(res['summary']['coverage']['data_gap'] + res['summary']['coverage']['judgment']),
                   L('数据不足或需人工判断', 'data gap or needs judgement')) + '</div>')


def _summary(r):
    res = r['results']
    if 'profile' not in res:
        return None
    cur = _quarter(res, _prof(res)['current'])
    yoy = res['comparison']['yoy']
    return L(f"{cur['label']} 收入 {bn(cur['revenue'])} 十亿美元（同比 {pct(yoy['pct']['revenue'], signed=True)}，报告口径），营业利润率 {pct(cur['op_margin'])}，自由现金流 {bn(cur['free_cash_flow'])} 十亿美元",
             f"{cur['label']} revenue USD {bn(cur['revenue'])} bn ({pct(yoy['pct']['revenue'], signed=True)} YoY, reported), operating margin {pct(cur['op_margin'])}, free cash flow USD {bn(cur['free_cash_flow'])} bn")


def _method_items(r):
    if 'profile' not in r['results']:
        return ['<li>' + e(r['methods']['description']) + '</li>']
    from ..research.earnings_quarter import method_text
    text = method_text(r['results']['profile'], len(r['results']['quarters']))
    return ['<li>' + e(text['en' if is_en() else 'zh']) + '</li>',
            '<li>' + L('登记数值在生成证据包时逐项出现在所引原文中，并通过会计恒等式核对；这是存在性检查，不证明取自正确的行列。',
                       'When the evidence bundle is built each registered value appears in the cited filing and satisfies the accounting identities; this is an existence check and does not prove the value comes from the right row and column.') + '</li>']


def make_renderer(Renderer):
    return Renderer(
        key_stats=_stats,
        method_items=_method_items,
        coverage_title_t=('季度财报与证据', 'Quarterly results and evidence'),
        coverage_section=details,
        evidence_rows=lambda r: [(L('核对', 'Checks'), L('原文 SHA256、数值出现在原文中、会计恒等式、文字摘录均在生成证据包前核对。',
                                                          'Filing SHA256, values appearing in the filings, accounting identities and text excerpts were checked before the bundle was built.')),
                                 (L('人工复核', 'Manual review'), L('没有人工签认；数值与恒等式为技术复核，没有逐条人工审阅原文。', 'No human sign-off; values and identities are technically reviewed and filings were not read line by line by a person.'))],
        evidence_summary=lambda r: [L('数值只来自公司申报原文；不使用媒体报道、电话会或行情。', 'Values come only from company filings; no media reports, call transcripts or market data.')],
        history_columns_t=((('最新季度收入（十亿美元）', 'Latest-quarter revenue (USD bn)'), lambda r: bn(r['results']['quarters'][-1]['revenue'])),),
        chart_data=lambda r: None, figures_t=(),
        use_note_t=('财报季度描述研究；不判断经营质量，不估值、不预测，不作投资建议', 'Quarterly earnings description; no judgement of quality, valuation or forecast; not investment advice'),
        state_description_t=('财报季度、现金流符号与覆盖分类', 'earnings quarter, cash-flow sign and coverage classification'),
        inline_visuals=True, home_summary=_summary)
