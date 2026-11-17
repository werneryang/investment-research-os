"""Quarterly earnings pages: five quarters, comparability notes, outlooks against actuals, and what is not covered."""
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


def _charts(rows):
    view = [{**r, 'revenue_bn': r['revenue'] / 1e3, 'op_bn': r['op_income'] / 1e3, 'ni_bn': r['consolidated_NI'] / 1e3,
             'cfo_bn': r['cfo'] / 1e3, 'capex_bn': r['cash_ppe'] / 1e3, 'fcf_bn': r['free_cash_flow'] / 1e3,
             'cloud_bn': r['Cloud_revenue'] / 1e3, 'services_bn': r['Services_revenue'] / 1e3} for r in rows]
    return (line_chart(view, [('revenue_bn', L('收入', 'Revenue')), ('op_bn', L('营业利润', 'Operating income')),
                              ('ni_bn', L('合并净利润', 'Consolidated net income'))],
                       L('收入与利润', 'Revenue and profit'), L('十亿美元', 'USD bn'))
            + line_chart(view, [('gross_margin', L('毛利率', 'Gross margin')), ('op_margin', L('营业利润率', 'Operating margin')),
                                ('Services_margin', L('Google Services 利润率', 'Google Services margin')),
                                ('Cloud_margin', L('Google Cloud 利润率', 'Google Cloud margin'))],
                         L('利润率', 'Margins'), '%', digits=0)
            + line_chart(view, [('cfo_bn', L('经营现金流', 'Operating cash flow')), ('capex_bn', L('现金资本开支', 'Cash capex')),
                                ('fcf_bn', L('自由现金流（发行人定义）', 'Free cash flow (issuer definition)'))],
                         L('现金流与资本开支', 'Cash flow and capital expenditure'), L('十亿美元', 'USD bn'))
            + line_chart(view, [('services_bn', 'Google Services'), ('cloud_bn', 'Google Cloud')],
                         L('分部收入', 'Segment revenue'), L('十亿美元', 'USD bn')))


def _quarter_table(res):
    rows = res['quarters']
    comp = res['comparison']
    heads = [L('指标', 'Metric')] + [r['label'] + ('*' if r['derived'] else '') for r in rows] + [L('同比', 'YoY'), L('环比', 'QoQ')]

    def line(label, key, kind='bn', growth=True):
        cells = []
        for r in rows:
            v = r.get(key)
            cells.append(bn(v) if kind == 'bn' else pct(v) if kind == 'pct' else f'{v:.2f}' if v is not None else '—')
        yoy = comp['yoy']['pct'].get(key) if growth else None
        qoq = comp['qoq']['pct'].get(key) if growth else None
        if kind == 'pct':
            yoy, qoq = comp['yoy']['margin_pp'].get(key), comp['qoq']['margin_pp'].get(key)
            tail = [pp(yoy) if key in comp['yoy']['margin_pp'] else '—', pp(qoq) if key in comp['qoq']['margin_pp'] else '—']
        else:
            tail = [pct(yoy, signed=True) if yoy is not None else '—', pct(qoq, signed=True) if qoq is not None else '—']
        return [e(label), *cells, *tail]

    spec = [
        (L('收入', 'Revenue'), 'revenue'), (L('Google Search & other', 'Google Search & other'), 'Search'),
        (L('YouTube 广告', 'YouTube ads'), 'YouTube_ads'), (L('Google Network', 'Google Network'), 'Network'),
        (L('订阅、平台与设备', 'Subscriptions, platforms and devices'), 'subscriptions_platforms_devices'),
        ('Google Services', 'Services_revenue'), ('Google Cloud', 'Cloud_revenue'), ('Other Bets', 'OtherBets_revenue'),
        (L('营业成本', 'Cost of revenues'), 'cost_of_revenues'), (L('研发', 'Research and development'), 'R_and_D'),
        (L('销售与营销', 'Sales and marketing'), 'sales_marketing'), (L('一般与行政', 'General and administrative'), 'G_and_A'),
        (L('营业利润', 'Operating income'), 'op_income'), (L('其他收支净额', 'Other income (expense), net'), 'other_income', 'bn', False),
        (L('其中：权益证券净损益', '  of which: equity securities gain (loss)'), 'equity_security_gain_loss', 'bn', False),
        (L('税前利润', 'Income before taxes'), 'EBT', 'bn', False),
        (L('所得税', 'Income tax'), 'income_tax', 'bn', False), (L('合并净利润', 'Consolidated net income'), 'consolidated_NI'),
        (L('优先股股息', 'Preferred dividends'), 'preferred_dividends', 'bn', False),
        (L('普通股可得净利润', 'Net income available to common'), 'common_NI'),
        (L('毛利率', 'Gross margin'), 'gross_margin', 'pct'), (L('营业利润率', 'Operating margin'), 'op_margin', 'pct'),
    ]
    html = ('<h3 id="earnings-quarterly">' + L('五个季度的合并利润表', 'Five quarters of consolidated results') + '</h3><p>'
            + L('金额单位为十亿美元，利润率为占同期收入的比例，同比、环比的利润率列为百分点。全部为报告口径（GAAP），含并购并表，不是有机增长。',
                'Amounts in USD billions; margins are percent of same-period revenue, with year-over-year and quarter-over-quarter margin changes in percentage points. '
                'All figures are as reported (GAAP) and include acquired operations; they are not organic growth.') + '</p>')
    related = ' · '.join(f'<a href="../{e(x["study"])}/">{e(_lang(x["label"]))}</a>' for x in res.get('related_studies', []))
    if related:
        html += '<p>' + L('相关研究：', 'Related research: ') + related + '</p>'
    html += table(heads, [line(*s) for s in spec])
    html += '<p class="small muted">' + L(
        '* 2025 年第四季度由 2025 年全年减去 2026 年第三季度 10-Q 中的前三季度比较数推出，不是申报中的直接季度值（与当时新闻稿的直接值收入差 100 万美元，见可比性说明）。'
        '同比对 2025 年第三季度，环比对 2026 年第二季度；—表示不适用。',
        '* Q4 2025 is derived as full-year 2025 less the nine-month comparative in the Q3 2026 10-Q; it is not a directly filed quarter (revenue differs by USD 1 million from the '
        'original release; see comparability notes). Year over year compares with Q3 2025, quarter over quarter with Q2 2026; — means not applicable.') + '</p>'
    return html


def _segment_table(res):
    rows = res['quarters']
    heads = [L('分部', 'Segment')] + [r['label'] + ('*' if r['derived'] else '') for r in rows]
    lines = []
    for label, op, rev, margin in (('Google Services', 'Services_op', 'Services_revenue', 'Services_margin'),
                                   ('Google Cloud', 'Cloud_op', 'Cloud_revenue', 'Cloud_margin'),
                                   ('Other Bets', 'OtherBets_op', 'OtherBets_revenue', 'OtherBets_margin')):
        lines.append([e(label + L(' 营业利润', ' operating income')), *[bn(r[op]) for r in rows]])
        lines.append([e(label + L(' 利润率', ' margin')), *[pct(r[margin], 0) if label == 'Other Bets' else pct(r[margin]) for r in rows]])
    lines.append([e(L('Alphabet 层面活动（未分摊）', 'Alphabet-level activities (unallocated)')), *[bn(r['Alphabet_level_op']) for r in rows]])
    lines.append([e(L('占收入比例 · Google Cloud', 'Share of revenue · Google Cloud')), *[pct(r['Cloud_share']) for r in rows]])
    delta = res['comparison']['segment_op_delta_yoy']
    names = {'Services_op': 'Google Services', 'Cloud_op': 'Google Cloud', 'OtherBets_op': 'Other Bets',
             'Alphabet_level_op': L('Alphabet 层面活动', 'Alphabet-level activities')}
    parts = ' · '.join(f'{e(names[k])} {bn(v)}' for k, v in delta['delta'].items())
    return ('<h3 id="earnings-segments">' + L('分部经营', 'Segment operations') + '</h3>' + table(heads, lines)
            + '<p>' + L('营业利润同比变动', 'Year-over-year change in operating income') + f' {bn(delta["total"])} {L("十亿美元 = ", "USD bn = ")}{parts}'
            + L('（合计' + ('等于' if delta['reconciles'] else '不等于') + '营业利润变动）。', f' (the parts {"sum to" if delta["reconciles"] else "do not sum to"} the change).')
            + '</p><p class="small muted">' + _lang(delta['caliber']) + '</p>')


def _cash_table(res):
    rows = res['quarters']
    heads = [L('指标', 'Metric')] + [r['label'] + ('*' if r['derived'] else '') for r in rows]
    cash = res['cash']
    lines = [[e(L('经营活动现金流', 'Operating cash flow')), *[bn(r['cfo']) for r in rows]],
             [e(L('现金资本开支（购置固定资产）', 'Cash capital expenditure (purchases of property and equipment)')), *[bn(r['cash_ppe']) for r in rows]],
             [e(L('自由现金流（发行人定义）', 'Free cash flow (issuer definition)')), *[bn(r['free_cash_flow']) for r in rows]],
             [e(L('现金资本开支 / 收入', 'Cash capex / revenue')), *[pct(r['capex_to_sales']) for r in rows]],
             [e(L('经营现金流 / 合并净利润', 'Operating cash flow / consolidated net income')), *[f"{r['cfo_to_consolidated_ni']:.2f}×" if r['cfo_to_consolidated_ni'] is not None else '—' for r in rows]]]
    nine = cash['nine_months']
    html = ('<h3 id="earnings-cash">' + L('现金流与资本开支', 'Cash flow and capital expenditure') + '</h3>' + table(heads, lines)
            + '<p>' + L(f'2026 年前三季度：经营现金流 {bn(nine["cfo"])}、现金资本开支 {bn(nine["cash_ppe"])} 十亿美元，经营现金流 / 现金资本开支 {nine["cfo_to_cash_ppe"]:.2f}×；'
                        f'经营现金流 / 合并净利润 {nine["cfo_to_consolidated_ni"]:.2f}×。近四个季度自由现金流 {bn(cash["ttm"]["free_cash_flow"])} 十亿美元。',
                        f'First nine months of 2026: operating cash flow USD {bn(nine["cfo"])} bn, cash capex USD {bn(nine["cash_ppe"])} bn, operating cash flow / cash capex '
                        f'{nine["cfo_to_cash_ppe"]:.2f}×; operating cash flow / consolidated net income {nine["cfo_to_consolidated_ni"]:.2f}×. Free cash flow over the last four quarters: '
                        f'USD {bn(cash["ttm"]["free_cash_flow"])} bn.') + '</p><p class="small muted">' + _lang(cash['caliber']) + '</p>')
    bal = res['balance']
    heads2 = [L('资产负债表时点', 'Balance sheet date'), L('现金与有价证券', 'Cash and marketable securities'), L('长期债务', 'Long-term debt'),
              L('固定资产净额', 'Net property and equipment'), L('总资产', 'Total assets'), L('总权益', 'Total equity')]
    html += table(heads2, [[e(b['date']), bn(b['cash_and_securities']), bn(b['longterm_debt']), bn(b['PPE_net']), bn(b['total_assets']), bn(b['total_equity'])] for b in bal])
    html += '<p class="small muted">' + L('十亿美元；总权益含优先股，没有对未调整的总权益计算 2026 年回报率。', 'USD billions; total equity includes preferred stock, and no 2026 return on unadjusted total equity is computed.') + '</p>'
    return html


def _bridges(res):
    b = res['bridges']
    rows = res['quarters']
    heads = [L('示意算术（税前）', 'Illustrative arithmetic (pretax)')] + [r['label'] for r in rows]
    lines = [[e(L('税前利润（报告）', 'Income before taxes (reported)')), *[bn(r['EBT']) for r in rows]],
             [e(L('权益证券净损益', 'Equity securities gain (loss)')), *[bn(r['equity_security_gain_loss']) for r in rows]],
             [e(L('税前利润剔除权益证券损益', 'Income before taxes excluding equity securities')), *[bn(b['ebt_ex_equity_securities'][r['period']]) for r in rows]]]
    html = table(heads, lines)
    if b.get('prior_year_charge_usd_m'):
        html += ('<p>' + L(f'去年同期营业利润 {bn(res["quarters"][0]["op_income"])} 加回约 {b["prior_year_charge_usd_m"] / 1e3:.1f} 十亿美元的欧盟相关费用为 {bn(b["prior_op_income_plus_charge"])}'
                            f'（利润率 {pct(b["prior_op_margin_plus_charge"])}）；本期营业利润较之 {pct(b["current_op_income_vs_prior_plus_charge_pct"], signed=True)}，利润率 {pp(b["current_vs_prior_margin_pp"])}。',
                            f'Prior-year operating income of USD {bn(res["quarters"][0]["op_income"])} bn plus the roughly USD {b["prior_year_charge_usd_m"] / 1e3:.1f} bn EU-related charge is USD {bn(b["prior_op_income_plus_charge"])} bn '
                            f'(margin {pct(b["prior_op_margin_plus_charge"])}); current operating income is {pct(b["current_op_income_vs_prior_plus_charge_pct"], signed=True)} against that, with the margin {pp(b["current_vs_prior_margin_pp"])}.') + '</p>')
    return html + '<p class="small muted">' + _lang(b['caliber']) + '</p>'


def _notes(res):
    docs = {d['id']: d for d in res['documents']}
    out = '<h3 id="earnings-comparability">' + L('可比性与口径', 'Comparability and definitions') + '</h3><p>' + L(
        '下列事项决定哪些比较可以直接做、哪些不能。每条列出原文事实、本页的处理与限制；摘录逐字取自所引申报。',
        'These items decide which comparisons can be made directly and which cannot. Each gives the filing fact, how this page treats it and its limit; excerpts are verbatim from the cited filing.') + '</p>'
    for n in res['notes']:
        quotes = ''.join(f'<blockquote>{e(x)}</blockquote>' for x in n.get('excerpts') or [])
        src = f'<p class="small muted">{L("出处：", "Source: ")}{_link(n["document"], docs)}</p>'
        out += (f'<details open><summary>{e(_lang(n["title"]))}</summary><p>{e(_lang(n["fact"]))}</p>'
                f'<p><strong>{L("限制：", "Limit: ")}</strong>{e(_lang(n["limit"]))}</p>'
                + (f'<details><summary>{L("原文摘录", "Excerpts")}</summary>{quotes}</details>' if quotes else '') + src + '</details>')
    out += '<h4>' + L('示意性的税前算术', 'Illustrative pretax arithmetic') + '</h4>' + _bridges(res)
    fx, ps = res['fx'], res['per_share']
    out += ('<h4>' + L('恒定汇率与每股收益', 'Constant currency and earnings per share') + '</h4>'
            + table([L('项目', 'Item'), L('十亿美元', 'USD bn')],
                    [[e(L('2026 年第三季度报告收入', 'Q3 2026 reported revenue')), bn(fx['reported_revenue'])],
                     [e(L('同比恒定汇率收入（发行人约 ' + str(fx['yoy_constant_currency_growth_pct_rounded']) + '% 同比）', f'Year-over-year constant-currency revenue (issuer: about {fx["yoy_constant_currency_growth_pct_rounded"]}% growth)')), bn(fx['yoy_constant_currency_revenue'])],
                     [e(L('环比恒定汇率收入（发行人约 ' + str(fx['qoq_constant_currency_growth_pct_rounded']) + '% 环比）', f'Quarter-over-quarter constant-currency revenue (issuer: about {fx["qoq_constant_currency_growth_pct_rounded"]}% growth)')), bn(fx['qoq_constant_currency_revenue'])]])
            + '<p>' + L(f'稀释后每股收益（普通股）：2026 年第三季度 {ps["diluted_eps_q3_2026"]:.2f} 美元，去年同期 {ps["diluted_eps_q3_2025"]:.2f} 美元（发行人披露）。',
                        f'Diluted EPS (common): USD {ps["diluted_eps_q3_2026"]:.2f} in Q3 2026 versus USD {ps["diluted_eps_q3_2025"]:.2f} a year earlier (issuer disclosure).') + '</p>')
    return out


def _outlooks(res):
    docs = {d['id']: d for d in res['documents']}
    g = res['guidance']
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
            + L(f'2025 年现金资本开支实际为 {act["value"] / 1e3:,.2f} 十亿美元（年报现金流量表）。差值对区间为实际减区间中点，对点值为实际减点值。',
                f'Actual 2025 cash capital expenditure was USD {act["value"] / 1e3:,.2f} bn (annual-report cash-flow statement). The difference is actual minus the range midpoint, or minus the point value.') + '</p>'
            + table(heads, rows) + '<p class="small muted">' + _lang(g['tolerance_note']) + '</p>')
    rem = g.get('remaining_2026_arithmetic')
    if rem:
        html += ('<p>' + L(f'同口径剩余额算术：2026 年二月区间减去前三季度现金资本开支 {rem["nine_months_cash_ppe_usd_bn"]:,.2f}，为 {rem["low_usd_bn"]:,.2f}–{rem["high_usd_bn"]:,.2f} 十亿美元。',
                           f'Same-definition residual arithmetic: the February 2026 range less nine-month cash capital expenditure of {rem["nine_months_cash_ppe_usd_bn"]:,.2f} gives USD {rem["low_usd_bn"]:,.2f}–{rem["high_usd_bn"]:,.2f} bn.')
                 + ' ' + _lang(rem['caliber']) + '</p>')
    r = res['rpo']
    heads2 = [L('日期', 'Date'), L('积压订单合计（十亿美元）', 'Backlog total (USD bn)'), L('其中 Google Cloud', 'of which Google Cloud'), L('合计环比', 'Total QoQ'), L('出处', 'Source')]
    html += ('<h3 id="earnings-backlog">' + L('收入积压订单', 'Revenue backlog') + '</h3>'
             + table(heads2, [[e(p['date']), f'{p["total"]:,.1f}', f'{p["cloud"]:,.1f}', pct(p['total_qoq_pct'], signed=True) if p['total_qoq_pct'] is not None else '—', _link(p['document'], docs)] for p in r['points']])
             + '<p>' + L(f'发行人称预计在未来 {r["recognition"]["months"]} 个月内确认积压订单的略高于 55%，其余在之后确认。', f'The issuer expects to recognise just over 55% of the backlog over the next {r["recognition"]["months"]} months, the remainder thereafter.')
             + ' ' + _lang(r['scope_change']) + '</p><p class="small muted">' + L('汇总余额不能按平均分摊成季度收入、利润或现金；合同级的时点、选择权和照付不议条款没有披露。',
                                                                                  'The aggregate balance cannot be spread evenly into quarterly revenue, profit or cash; contract-level timing, options and take-or-pay terms are not disclosed.') + '</p>')
    return html


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
    rel = res['release']
    note = L(f'Alphabet 于 {rel["ir_date"]} 发布第三季度业绩，10-Q 于 {rel["form_10q_filed"]} 申报。', f'Alphabet released Q3 results on {rel["ir_date"]}; the 10-Q was filed on {rel["form_10q_filed"]}.')
    return ('<h3 id="earnings-sources">' + L('来源文件', 'Source documents') + '</h3><p>' + note + ' '
            + L('原文只保存在本机（不入库），登记里的 SHA256 固定了版本；数值核对在生成证据包时完成。',
                'The originals are kept only on the maintainer’s machine (not in the repository); the registered SHA256 pins each version and the checks run when the evidence bundle is built.') + '</p>'
            + table(heads, [[f'<a href="{e(d["url"])}">{e(d["form"])}</a>', e(d.get('period_end') or '—'), e(d['accession']), e(str(d['accepted_at'])), f'<code>{e(d["sha256"][:12])}…</code>'] for d in res['documents']]))


def details(r):
    res = r['results']
    return (_quarter_table(res) + _charts(res['quarters']) + _segment_table(res) + _cash_table(res)
            + _notes(res) + _outlooks(res) + _coverage(res) + _sources(res))


def _stats(r):
    res = r['results']
    cur = next(q for q in res['quarters'] if q['period'] == 'q3_2026')
    yoy = res['comparison']['yoy']
    return ('<div class="stats">' + stat(L('2026 Q3 收入（十亿美元）', 'Q3 2026 revenue (USD bn)'), bn(cur['revenue']), L(f'同比 {pct(yoy["pct"]["revenue"], signed=True)}（报告口径）', f'{pct(yoy["pct"]["revenue"], signed=True)} YoY (reported)'))
            + stat(L('营业利润率', 'Operating margin'), pct(cur['op_margin']), L(f'较去年同期 {pp(yoy["margin_pp"]["op_margin"])}', f'{pp(yoy["margin_pp"]["op_margin"])} YoY'))
            + stat(L('自由现金流（十亿美元）', 'Free cash flow (USD bn)'), bn(cur['free_cash_flow']), L('发行人定义', 'issuer definition'))
            + stat(L('未覆盖项', 'Not covered'), str(res['summary']['coverage']['data_gap'] + res['summary']['coverage']['judgment']),
                   L('数据不足或需人工判断', 'data gap or needs judgement')) + '</div>')


def _summary(r):
    res = r['results']
    cur = next(q for q in res['quarters'] if q['period'] == 'q3_2026')
    yoy = res['comparison']['yoy']
    return L(f"{cur['label']} 收入 {bn(cur['revenue'])} 十亿美元（同比 {pct(yoy['pct']['revenue'], signed=True)}，报告口径），营业利润率 {pct(cur['op_margin'])}，自由现金流 {bn(cur['free_cash_flow'])} 十亿美元",
             f"{cur['label']} revenue USD {bn(cur['revenue'])} bn ({pct(yoy['pct']['revenue'], signed=True)} YoY, reported), operating margin {pct(cur['op_margin'])}, free cash flow USD {bn(cur['free_cash_flow'])} bn")


def make_renderer(Renderer):
    return Renderer(
        key_stats=_stats,
        method_items=lambda r: ['<li>' + (e(r['methods']['description']) if not is_en() else
                                           'Five quarters of consolidated results, segments and cash flow are read from a fixed evidence bundle (reported basis, USD millions); Q4 2025 is derived as full year '
                                           'less nine months. Margins are percent of same-period revenue; year over year compares with Q3 2025 and quarter over quarter with Q2 2026; free cash flow follows the issuer definition. '
                                           'Excluding equity-security gains and the prior-year charge is illustrative pretax arithmetic only. No organic growth, valuation or forecast is stated.') + '</li>',
                                '<li>' + L('登记数值在生成证据包时逐项出现在所引原文中，并通过会计恒等式核对；这是存在性检查，不证明取自正确的行列。',
                                           'When the evidence bundle is built each registered value appears in the cited filing and satisfies the accounting identities; this is an existence check and does not prove the value comes from the right row and column.') + '</li>'],
        coverage_title_t=('季度财报与证据', 'Quarterly results and evidence'),
        coverage_section=details,
        evidence_rows=lambda r: [(L('核对', 'Checks'), L('原文 SHA256、数值出现在原文中、会计恒等式、文字摘录均在生成证据包前核对。',
                                                          'Filing SHA256, values appearing in the filings, accounting identities and text excerpts were checked before the bundle was built.')),
                                 (L('人工复核', 'Manual review'), L('没有人工签认；数值与恒等式为技术复核，没有逐条人工审阅原文。', 'No human sign-off; values and identities are technically reviewed and filings were not read line by line by a person.'))],
        evidence_summary=lambda r: [L('数值只来自公司申报原文；不使用媒体报道、电话会或行情。', 'Values come only from company filings; no media reports, call transcripts or market data.')],
        history_columns_t=((('最新季度收入（十亿美元）', 'Latest-quarter revenue (USD bn)'), lambda r: bn(next(q for q in r['results']['quarters'] if q['period'] == 'q3_2026')['revenue'])),),
        chart_data=lambda r: None, figures_t=(),
        use_note_t=('财报季度描述研究；不判断经营质量，不估值、不预测，不作投资建议', 'Quarterly earnings description; no judgement of quality, valuation or forecast; not investment advice'),
        state_description_t=('财报季度、现金流符号与覆盖分类', 'earnings quarter, cash-flow sign and coverage classification'),
        inline_visuals=True, home_summary=_summary)
