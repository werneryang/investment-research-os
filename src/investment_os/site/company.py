"""Company pages: evidence, fiscal trends and limited peer comparisons."""
from .common import e, stat
from .i18n import L
from .visuals import dotplot, nice_ticks, scaled
from ..research.company import METRICS, select_fact

LABELS = {'revenue':'营收 / Revenue', 'operating_income':'经营利润 / Operating income',
          'net_income':'净利润 / Net income', 'operating_cash_flow':'经营现金流 / OCF',
          'capex':'现金资本开支 / Cash capex', 'free_cash_flow':'OCF − capex',
          'operating_margin':'经营利润率 / Operating margin', 'net_margin':'净利润率 / Net margin'}


def fmt(value, percent=False):
    return '—' if value is None else f'{value*100:.1f}%' if percent else f'{value/1e9:,.2f}'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def chart(rows, metrics, percent=False):
    """Accessible SVG line chart; absent observations break paths rather than connect gaps.

    Series colours come from the shared tokens (--c1…) in fixed order; labels stay in text ink."""
    values=[r[m] for r in rows for m in metrics if r[m] is not None]
    if not values:
        return '<p>'+L('没有可绘制的同口径数据。','No comparable data to plot.')+'</p>'
    scale=100 if percent else 1e-9
    ticks=nice_ticks(min(0,min(values))*scale,max(0,max(values))*scale,4)
    lo,hi=ticks[0]/scale,ticks[-1]/scale
    x=lambda i: 65+i*625/max(1,len(rows)-1)
    y=lambda v: 205-(v-lo)*165/(hi-lo)
    title=' / '.join(LABELS[m] for m in metrics)
    tick=lambda v: f'{v:.0f}%' if percent else f'{v:,.0f}'
    out=f'<figure class="chart-card"><h4>{e(title)} · {"%" if percent else "USD bn"}</h4><svg class="dotplot" viewBox="0 0 740 250" role="img" aria-label="{e(title)}"><title>{e(title)}</title>'
    for t in ticks:
        out+=f'<line class="grid" x1="65" x2="690" y1="{y(t/scale):.1f}" y2="{y(t/scale):.1f}"/><text class="axis" x="58" y="{y(t/scale)+4:.1f}" text-anchor="end">{tick(t)}</text>'
    for slot,m in enumerate(metrics,1):
        path=''; previous=None
        for i,r in enumerate(rows):
            if r[m] is None:
                previous=None;continue
            consecutive=previous is not None and int(r['date'][:4])-int(rows[previous]['date'][:4])==1
            path+=f'{"L" if consecutive else "M"}{x(i):.1f},{y(r[m]):.1f} '
            out+=f'<circle cx="{x(i):.1f}" cy="{y(r[m]):.1f}" r="3.5" style="fill:var(--c{slot});stroke:var(--panel);stroke-width:1"><title>{e(r["date"])} · {e(LABELS[m])}: {fmt(r[m],percent)}</title></circle>'
            previous=i
        out+=f'<path d="{path}" fill="none" style="stroke:var(--c{slot})" stroke-width="2"/>'
    step=max(1,round(len(rows)/6))
    for i in sorted(set(range(0,len(rows),step))|{len(rows)-1}):
        out+=f'<text class="axis" x="{x(i):.1f}" y="230" text-anchor="middle">{e(rows[i]["date"][:4])}</text>'
    legend=' '.join(f'<span class="legend-item"><i style="background:var(--c{slot})"></i>{e(LABELS[m])}</span>' for slot,m in enumerate(metrics,1))
    out+=f'</svg><p class="chart-note">{legend}</p></figure>'
    return out


def overview_dots(profiles):
    """15 家公司最新财年利润率的点图：按样本顺序排列，不排名；各公司财年截止日不同。"""
    rows=[(p['label'],{'operating_margin':scaled(p['latest'].get('operating_margin')),
                       'net_margin':scaled(p['latest'].get('net_margin'))},p['last'][:7]) for p in profiles]
    return dotplot(rows,[('operating_margin',L('经营利润率','Operating margin'),0),('net_margin',L('净利润率','Net margin'),1)],
                   lambda v: f'{v:.0f}%',title=L('最新财年的利润率','Latest fiscal-year margins'),
                   note=L('按样本顺序排列，不是排名；财年截止日不同（见名称后的年月），商业模式差异见下方可比性说明。',
                          'Listed in sample order, not ranked; fiscal years end on different dates (shown after each name); see comparability notes below.'))


def details(result):
    profiles=result['results']['companies']
    out='<p>'+L('金额为十亿美元；比率为百分比；— 表示缺失、不适用或不能同申报配对。期末为月末匹配键，实际日期见证据。',
                 'Amounts in USD billions, ratios in percent. — means missing, inapplicable or no same-filing pair. Month-end keys align sources; actual dates are in evidence.')+'</p>'
    out+='<p>'+L('最新财年截止日不同，请先看日期；不提供全样本高低排名。',
                 'Latest fiscal ends differ: check dates before comparing. No cross-sample ranking is provided.')+'</p>'
    overview=[]
    for p in profiles:
        r=p['latest']
        overview.append([f'<a href="../company_{e(p["slug"])}/">{e(p["label"])}</a>',p['last'],
                         fmt(r['revenue']),fmt(r['operating_margin'],True),fmt(r['net_margin'],True),
                         fmt(r['operating_cash_flow']),fmt(r['capex']),str(p['missing'])])
    out+='<div id="company-overview"></div>'
    out+=table([L('公司','Company'),L('最新期末','Latest end'),'Revenue','Op margin','Net margin','OCF','Capex',L('缺失项 / 全期间','Missing / all periods')],overview)
    if len(profiles)>1:
        out+=overview_dots(profiles)
        out+='<h3 id="company-comparability">'+L('哪些公司可以比较？','Which companies can be compared?')+'</h3>'
        out+=table([L('公司','Company'),L('比较边界','Comparison boundary')],[[e(p['label']),e(p['comparison'])] for p in profiles])
        return out
    p=profiles[0]; rows=result['tables']['annual']
    out+='<p><a href="../company_sample/">'+L('← 15 家公司总览','← 15-company overview')+'</a></p>'
    out+='<h3 id="company-comparability">'+L('可比性与口径','Comparability and definitions')+'</h3><p>'+e(p['comparison'])+'</p><p>'+e(p['note'])+'</p>'
    out+='<p>'+ ' · '.join(f'<a href="../company_{e(peer["slug"])}/">{e(peer["label"])}</a>' for peer in p.get('peer_links', []))+'</p>'
    out+='<p>'+L('以下公司备注为中文。','Company-specific research notes below are in Chinese.')+'</p>'
    out+=chart(rows,['revenue'])+chart(rows,['operating_margin','net_margin'],True)+chart(rows,['operating_cash_flow','capex','free_cash_flow'])
    out+='<h3 id="company-annual">'+L('年度变化','Annual changes')+'</h3>'
    out+=table(['Period','Revenue','Op margin','Net margin','OCF','Capex','OCF − capex','Revenue YoY','OCF YoY','Capex YoY'],
        [[r['date'],fmt(r['revenue']),fmt(r['operating_margin'],True),fmt(r['net_margin'],True),
          fmt(r['operating_cash_flow']),fmt(r['capex']),fmt(r['free_cash_flow']),
          *[fmt((r['growth'].get(m) or {}).get('value'),True) for m in ('revenue','operating_cash_flow','capex')]] for r in rows])
    out+='<p class="small">'+L('同比来自同一申报、同一科目的相邻财年比较数，可能不同于图上逐年最新值的比值；分母非正或配对失败不计算。',
        'YoY uses adjacent fiscal years with the same tag in one filing; it may differ from ratios of latest values in the chart. Non-positive bases or unmatched pairs are withheld.')+'</p>'
    out+='<h3 id="company-evidence">'+L('逐项证据、缺失与修订候选','Evidence, gaps and revision candidates')+'</h3>'
    out+='<p>'+L('同科目数值改变只标为修订候选；科目切换另列。所有版本可展开，包含实际期末、申报链接和替代科目。',
        'Changed same-tag values are revision candidates, not confirmed restatements. Tag switches are separate. Expand versions for actual ends, filing links and alternative tags.')+'</p>'
    for r in reversed(rows):
        out+=f'<details><summary>{e(r["date"])}</summary>'
        lines=[]
        for m in METRICS:
            ev=r['evidence'][m]; latest=select_fact(ev['history'])
            label=e(LABELS[m]); versions=[]
            for h in ev['history']:
                alts='; '.join(a['tag']+': '+', '.join(fmt(v) for v in a['values']) for a in h['alternatives'])
                versions.append([f'<a href="{e(h["url"])}">{e(h["accession"])}</a>',e(h['form']),e(h['available_at'][:10]),
                    e(h['period_start'] or 'unknown')+' → '+e(h['period_end'])+(' (rounded)' if not h['exact_end'] else ''),
                    e(h['tag']),fmt(h['value']),e(h.get('source','')),e(h['reason'] or ''),e(alts)])
            flags=[]
            if ev.get('same_tag_changed'):flags.append(L('同科目修订候选','Same-tag revision candidate'))
            if ev.get('tags_used',0)>1:flags.append(L('跨申报科目切换','Tag switch across filings'))
            if not latest or latest['value'] is None:flags.append(ev.get('missing_reason') or 'missing')
            history='<details><summary>'+str(len(versions))+' '+L('个申报版本','filing versions')+'</summary>'+table(['Accession','Form','Available','Period','Tag','USD bn','Source','Issue','Alternatives'],versions)+'</details>' if versions else ''
            lines.append([label,fmt(latest['value'] if latest else None),e(' · '.join(flags)),history])
        out+=table(['Metric','Latest USD bn','Flags','Evidence'],lines)+'</details>'
    return out


def make_renderer(Renderer):
    return Renderer(key_stats=lambda r:'<div class="stats">'+stat(L('公司','Companies'),str(r['results']['company_count']))
        +stat(L('缺失指标','Missing metrics'),str(r['results']['missing']))
        +stat(L('修订候选','Revision candidates'),str(r['results']['revision_candidates']))+'</div>',
        method_items=lambda r:['<li>'+e(r['methods']['description'])+'</li>',
            '<li>'+L('净利润率 = 净利润 / 营收；经营利润率 = 经营利润 / 营收。仅正营收且同一申报才计算。',
                    'Net margin = net income / revenue; operating margin = operating income / revenue. Requires positive revenue and one filing.')+'</li>'],
        coverage_title_t=('公司研究与证据','Company research and evidence'),coverage_section=details,
        evidence_rows=lambda r:[(L('数据快照','Data snapshot'),e(r['results']['snapshot'])),
                               (L('人工核对','Manual review'),L('未逐条人工核对全部年报。','No exhaustive manual filing review.'))],
        evidence_summary=lambda r:[L('15 家固定样本；可追溯申报版本。','Fixed 15-company sample with filing versions.')],
        history_columns_t=((("公司数","Companies"),lambda r:str(r['results']['company_count'])),),
        chart_data=lambda r:None,figures_t=(),
        use_note_t=('公司年度描述研究；不作投资建议','Annual descriptive research; no investment recommendation'),
        summary_columns_t=(('最新财年末','Latest fiscal end'),('营收（十亿美元）','Revenue (USD bn)'),('营收同比（同一申报）','Revenue YoY (same filing)')),
        summary_row=lambda r:(lambda p:[e(p['last']),fmt(p['latest'].get('revenue')),
            fmt(((p['latest'].get('growth') or {}).get('revenue') or {}).get('value'),True)])(r['results']['companies'][0]),
        state_description_t=('公司覆盖与数据缺口','Company coverage and data gaps'), inline_visuals=True)
