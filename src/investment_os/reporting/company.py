"""Portable report tables; site pages add inline trend charts and full provenance."""
def fmt(value, percent=False):
    return "—" if value is None else f"{value*100:.1f}%" if percent else f"{value/1e9:,.2f}"


def sections(r):
    summaries=r['results']['companies']
    body=[]
    for p in summaries:
        body += [p['label']+'：'+p['comparison'],p['note']]
    rows=r['tables']['annual']
    body.append(('table',['公司','期末匹配键','营收 USD bn','经营利润率','净利润率','OCF USD bn','Capex USD bn'],
        [[x['label'],x['date'],fmt(x['revenue']),fmt(x['operating_margin'],True),fmt(x['net_margin'],True),
          fmt(x['operating_cash_flow']),fmt(x['capex'])] for x in rows]))
    return body,'口径与缺失',[*r['limitations'],
        '完整申报版本、缺失原因与科目选择见研究网页及本运行 result.json 的 tables.annual.evidence。',
        ('table',['公司','年度期数','缺失项','同科目修订候选','科目切换'],
         [[str(p[k]) for k in ('label','periods','missing','revision_candidates','tag_switches')] for p in summaries])]
