"""Relationship-chain pages: layered chain map, per-edge evidence, breakpoints and same-filing revenue."""
from .common import e, stat
from .i18n import L, te

REASON = {'anonymous': ('对手方匿名', 'Counterparty not named'),
          'activity_unknown': ('业务未定', 'Business not stated'),
          'unreviewed': ('未复核', 'Not reviewed'),
          'external_only': ('仅外部来源', 'External source only'),
          'searched_not_disclosed': ('已查原文、未披露', 'Filing read; not disclosed'),
          'not_searched': ('尚未查阅', 'Not yet read'),
          'depth_limit': ('达到层数上限', 'Layer limit reached')}
TYPE = {'supply': ('供应', 'Supply'), 'foundry': ('晶圆代工', 'Foundry'),
        'contract_manufacturing': ('委外制造', 'Contract manufacturing')}
SEGMENTS = {'nvda:ComputeAndNetworkingSegmentMember': ('计算与网络分部', 'Compute & Networking'),
            'nvda:GraphicsSegmentMember': ('图形分部', 'Graphics'),
            'mu:CMBUMember': ('云存储业务单元（CMBU，含全部数据中心客户的 HBM）', 'Cloud Memory BU (CMBU, incl. HBM for all data center customers)'),
            'mu:CDBUMember': ('核心数据中心业务单元（CDBU）', 'Core Data Center BU (CDBU)'),
            'mu:MCBUMember': ('移动与客户端业务单元（MCBU）', 'Mobile and Client BU (MCBU)'),
            'mu:AEBUMember': ('汽车与嵌入式业务单元（AEBU）', 'Automotive and Embedded BU (AEBU)'),
            'us-gaap:AllOtherSegmentsMember': ('其他', 'All other')}


def _reason(key):
    return L(*REASON.get(key, (key, key)))


def _share(s):
    if not s:
        return '—'
    v = f"{s['value'] * 100:.1f}%" if s.get('value') is not None else e(s.get('bound', ''))
    return f"{v}<p class=\"small muted\">{te(s.get('numerator', ''))} / {te(s.get('denominator', ''))} · {te(str(s.get('period', '')))}</p>"


def _kind(edge):
    out = L(*TYPE.get(edge['type'], (edge['type'], edge['type'])))
    business = edge.get('activity_name')
    return out + (' · ' + te(business) if business and business != TYPE.get(edge['type'], ('',))[0] else '')


def _marks(edge, breaks):
    tags = []
    if edge['status'] not in ('reviewed', 'confirmed'):
        tags.append(f'<span class="chain-tag muted">{L("未复核", "Not reviewed")}</span>')
    if edge['evidence_class'] != 'primary' or edge.get('external_path'):
        tags.append(f'<span class="chain-tag">{L("外部来源", "External source")}</span>')
    tags += [f'<span class="chain-tag warn">{_reason(b["reason"])}</span>' for b in breaks]
    return ''.join(tags)


def _breaks(chain):
    by = {}
    for b in chain['breakpoints']:
        by.setdefault((b['node'], b['relation']), []).append(b)
    return by


def _card(edge, chain, side):
    breaks = _breaks(chain).get((edge['to'], edge['relation']), [])
    cls = ['chain-node']
    if edge['counterparty_type'] == 'anonymous':
        cls.append('anon')
    if edge['status'] not in ('reviewed', 'confirmed'):
        cls.append('unreviewed')
    if edge['evidence_class'] != 'primary' or edge.get('external_path'):
        cls.append('external')
    via = '' if edge['layer'] == 1 else f'<p class="small muted">{"→" if side == "up" else "←"} {te(edge["from_name"])}</p>'
    value = (edge.get('share') or {}).get('value')
    share = f'<p class="small">{L("占比", "Share")} {value * 100:.1f}%</p>' if value is not None else ''
    return (f'<li class="{" ".join(cls)}"><strong>{te(edge["to_name"])}</strong><p class="small">{_kind(edge)}</p>'
            f'{via}{share}{_marks(edge, breaks)}</li>')


def chain_map(r):
    res = r['results']
    up, down = res['upstream'], res['downstream']
    depth = res['depth']
    cols = []
    for layer in range(depth, 0, -1):
        edges = up['layers'][layer - 1] if len(up['layers']) >= layer else []
        cols.append((L(f'上游第 {layer} 层', f'Upstream layer {layer}'), ''.join(_card(x, up, 'up') for x in edges)))
    cols.append((L('起点', 'Starting point'), f'<li class="chain-node root"><strong>{te(res["root_name"])}</strong></li>'))
    searched, found = res['summary']['reverse_searched'], res['summary']['reverse_found']
    counts = L(f'{searched} 家样本公司年报，{found} 家点名 {res["root_name"]}',
               f"{found} of {searched} sample companies' filings name {res['root_name']}")
    reverse = (f'<li class="chain-node anon"><a href="#chain-reverse-search">{L("反向检索", "Reverse search")}</a>'
               f'<p class="small">{e(counts)}</p></li>')
    for layer in range(1, depth + 1):
        edges = down['layers'][layer - 1] if len(down['layers']) >= layer else []
        cols.append((L(f'下游第 {layer} 层', f'Downstream layer {layer}'),
                     ''.join(_card(x, down, 'down') for x in edges) + (reverse if layer == 1 and res['reverse_search'] else '')))
    body = ''.join(f'<div class="chain-col"><h4>{h}</h4><ul>{cards or "<li class=chain-empty>—</li>"}</ul></div>' for h, cards in cols)
    legend = L('灰色为未复核；虚线为外部来源；黄色标签为停止展开的原因。关系不表示影响大小，占比只按原文口径列出。',
               'Grey: not reviewed; dashed: external source; yellow tags: why expansion stopped. A link does not measure '
               'impact; shares are shown only as disclosed.')
    return f'<div class="chain-map">{body}</div><p class="small muted">{legend}</p>'


def _evidence(edge):
    items = []
    for x in edge['evidence']:
        if x.get('excerpt'):
            items.append(f'<li><a href="{e(x["url"])}">{e(x["form"] or "")}</a> · {e(x["locator"])}<blockquote>{e(x["excerpt"])}</blockquote></li>')
        else:
            items.append(f'<li>{e(x.get("publisher") or "")} · {e(x.get("title") or "")} · {e(x.get("published_at") or "")}'
                         + (f'<p>{te(x["summary"])}</p>' if x.get('display') == 'summary' and x.get('summary') else '') + '</li>')
    return f'<details><summary>{len(items)} {L("条证据", "evidence items")}</summary><ul>{"".join(items)}</ul></details>'


def _edge_table(chain, hid, title):
    rows = []
    for layer in chain['layers']:
        for x in layer:
            ends = f'{te(x["to_name"])} → {te(x["from_name"])}' if chain['direction'] == 'upstream' else f'{te(x["from_name"])} → {te(x["to_name"])}'
            review = (L('已复核（技术复核）', 'Reviewed (technical)') if x['status'] == 'reviewed' else
                      L('人工确认', 'Confirmed') if x['status'] == 'confirmed' else L('未复核', 'Not reviewed'))
            disclosed = ', '.join(te(n) for n in x['disclosed_by_names']) or '—'
            rows.append(f'<tr><td>{x["layer"]}</td><td>{ends}</td><td>{_kind(x)}<p class="small muted">{te(x.get("product") or "")}</p></td>'
                        f'<td>{_share(x.get("share"))}</td><td>{disclosed}</td><td>{review}<p class="small muted">{te(x.get("limits") or "")}</p></td>'
                        f'<td>{_evidence(x)}</td></tr>')
    heads = [L('层', 'Layer'), L('提供方 → 接收方', 'Provider → recipient'), L('关系与业务', 'Relationship and business'),
             L('占比（原文口径）', 'Share (as disclosed)'), L('披露方', 'Disclosed by'), L('复核与结论边界', 'Review and limits'),
             L('证据', 'Evidence')]
    return (f'<h3 id="{hid}">{title}</h3><div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in heads)
            + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def _breakpoints(res):
    rows = []
    for direction, chain in ((L('上游', 'Upstream'), res['upstream']), (L('下游', 'Downstream'), res['downstream'])):
        for b in chain['breakpoints']:
            detail = te(b.get('detail') or '') if b['reason'] != 'searched_not_disclosed' else '; '.join(
                f'<a href="{e(q["url"])}">{e(q["id"])}</a>' + (f' — {te(q["note"])}' if q.get('note') else '') for q in b.get('searches', []))
            rows.append(f'<tr><td>{direction}</td><td>{b["layer"]}</td><td>{te(b["node_name"])}</td><td>{_reason(b["reason"])}</td><td>{detail}</td></tr>')
    heads = [L('方向', 'Direction'), L('层', 'Layer'), L('主体', 'Subject'), L('原因', 'Reason'), L('说明', 'Detail')]
    intro = L('「已查原文、未披露」是读过对方年报、原文没有点名的结论；「尚未查阅」只说明这一步还没做，不等于没有关系。',
              '"Filing read; not disclosed" means the filing was read and names no counterparty; "Not yet read" only means the '
              'step has not been done, not that no relationship exists.')
    return (f'<h3 id="chain-breakpoints">{L("链在哪里断开", "Where the chain stops")}</h3><p>{intro}</p><div class="scroll"><table><thead><tr>'
            + ''.join(f'<th>{h}</th>' for h in heads) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def _downstream(res):
    notes = ''.join(f'<li><a href="{e(n["url"])}">10-K</a> · {e(n["locator"])}<blockquote>{e(n["excerpt"])}</blockquote>'
                    f'<p class="small muted">{te(n.get("limits") or "")}</p></li>' for n in res['downstream_notes'])
    rows = ''.join(f'<tr><td>{te(q["subject"])}</td><td><a href="{e(q["url"])}">{e(q["form"])}</a> · {e(q["period_end"])}</td>'
                   f'<td>{L("点名", "Named") if q["result"] == "found" else L("未点名", "Not named")}</td><td>{te(q["method"])}</td></tr>'
                   for q in res['reverse_search'])
    heads = [L('公司', 'Company'), L('年报（财年末）', 'Annual report (fiscal year end)'), L('是否点名 NVIDIA', 'Names NVIDIA?'),
             L('方法', 'Method')]
    return (_edge_table(res['downstream'], 'chain-downstream', L('下游：NVIDIA 的客户', 'Downstream: NVIDIA customers'))
            + f'<h4>{L("NVIDIA 原文中的客户类型（不生成具名关系）", "Customer types in NVIDIA filing (no named relationships)")}</h4><ul>{notes}</ul>'
            + f'<h4 id="chain-reverse-search">{L("反向检索：客户自己的年报是否点名 NVIDIA", "Reverse search: do customers name NVIDIA in their own filings?")}</h4>'
            + '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in heads) + f'</tr></thead><tbody>{rows}</tbody></table></div>')


def _bn(v):
    return f'{v / 1e9:,.2f}'


def _revenue(res):
    position = {res['root']: L('起点', 'Starting point')}
    for x in res['upstream']['layers'][0] if res['upstream']['layers'] else []:
        position.setdefault(x['to'], L('上游第 1 层', 'Upstream layer 1') + ' · ' + _kind(x))
    rows = []
    for ent, rev in res['revenue'].items():
        name = next((x['to_name'] for x in sum(res['upstream']['layers'], []) if x['to'] == ent), res['root_name'])

        def line(label, series, strong=False):
            cells = ''.join(f'<td>{e(x["period_end"])}<br><strong>{_bn(x["value"])}</strong>'
                            + (f'<br><span class="small">{x["growth"] * 100:+.1f}%</span>' if 'growth' in x else '') + '</td>'
                            for x in series)
            return f'<tr{" class=chain-total" if strong else ""}><td>{label}</td><td>{e(rev["unit"])} bn</td>{cells}</tr>'
        rows.append(line(f'<strong>{te(name)}</strong><p class="small muted">{position.get(ent, "")}</p>', rev['consolidated'], True))
        if len(rev['segments']) > 1:
            for seg, series in rev['segments'].items():
                rows.append(line('&nbsp;&nbsp;' + L(*SEGMENTS.get(seg, (seg, seg))), series))
    missing = ', '.join(te(x['name']) for x in res['revenue_missing'])
    heads = [L('公司与链上位置', 'Company and position'), L('单位', 'Unit'), L('财年 1', 'Fiscal year 1'),
             L('财年 2', 'Fiscal year 2'), L('财年 3', 'Fiscal year 3')]
    note = L('每家公司只用自己的一份年报（三个财年），同比只在同一申报、同一币种内计算；财年截止月不同，不按日历年对齐；不计算相关系数，'
             '同期变化不说明由 NVIDIA 带动。', 'Each company uses one of its own annual reports (three fiscal years); growth is computed '
             'within one filing and currency only. Fiscal years end in different months and are not aligned to calendar years; no '
             'correlations are computed, and co-movement does not show that NVIDIA drove it.')
    return (f'<h3 id="chain-revenue">{L("同期营收：NVIDIA 与上游第 1 层", "Same-period revenue: NVIDIA and upstream layer 1")}</h3><p>{note}</p>'
            '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in heads) + '</tr></thead><tbody>' + ''.join(rows)
            + '</tbody></table></div>' + (f'<p class="small muted">{L("尚未取得年报：", "Annual reports not yet obtained: ")}{missing}</p>' if missing else ''))


def _side(res):
    items = ''.join(f'<li>{" ↔ ".join(te(n) for n in s["party_names"])} · {te(s.get("market") or "")}</li>'
                    for s in res['upstream']['side_relations'] + res['downstream']['side_relations'])
    return (f'<details><summary>{L("竞争关系（旁注，不当作传导路径）", "Competition (side note; not a transmission path)")}</summary><ul>{items}</ul></details>'
            if items else '')


def details(r):
    res = r['results']
    return (chain_map(r)
            + _edge_table(res['upstream'], 'chain-upstream', L('上游：逐条关系与证据', 'Upstream: relationships and evidence'))
            + _breakpoints(res) + _downstream(res) + _revenue(res) + _side(res))


def _stats(r):
    s = r['results']['summary']
    stops = sum(s['breakpoints']['upstream'].values())
    return ('<div class="stats">' + stat(L('上游点名供应方', 'Named upstream suppliers'), str(s['upstream_named']))
            + stat(L('上游断点', 'Upstream breakpoints'), str(stops))
            + stat(L('下游具名客户', 'Named downstream customers'), str(s['downstream_named']))
            + stat(L('反向检索点名', 'Reverse search hits'), f"{s['reverse_found']} / {s['reverse_searched']}") + '</div>')


def _summary(r):
    s = r['results']['summary']
    b = s['breakpoints']['upstream']
    return L(f"上游第 1 层点名 {s['upstream_named']} 家供应方，其中 {b.get('activity_unknown', 0)} 家业务未定、"
             f"{b.get('not_searched', 0)} 处尚未查阅；第 2 层只得到未点名的投入类别；下游客户匿名，"
             f"{s['reverse_searched']} 家样本公司年报有 {s['reverse_found']} 家点名 NVIDIA",
             f"Upstream layer 1 names {s['upstream_named']} suppliers ({b.get('activity_unknown', 0)} with business not stated, "
             f"{b.get('not_searched', 0)} not yet read); layer 2 yields only unnamed input categories; customers are anonymous, "
             f"and {s['reverse_found']} of {s['reverse_searched']} sample companies' filings name NVIDIA")


def make_renderer(Renderer):
    return Renderer(
        key_stats=_stats,
        method_items=lambda r: ['<li>' + te(r['methods']['description']) + '</li>',
                                '<li>' + L('关系的技术复核由模型完成（事实核对与语义复核），不等于人工签认。',
                                           'Relationships were technically reviewed by a model (fact and semantic checks); this is not human sign-off.') + '</li>'],
        coverage_title_t=('关系链、断点与同期营收', 'Relationship chain, breakpoints and same-period revenue'),
        coverage_section=details,
        evidence_rows=lambda r: [(L('登记版本', 'Catalog version'), e(r['methods'].get('catalog_version') or '')),
                                 (L('人工复核', 'Manual review'), L('没有人工签认；关系与证据为技术复核。', 'No human sign-off; relationships and evidence are technically reviewed.'))],
        evidence_summary=lambda r: [L('关系来自登记的年报原文；营收取自各公司自己的年报。', 'Relationships come from registered filing text; revenue from each company’s own annual report.')],
        history_columns_t=((('上游点名', 'Named upstream'), lambda r: str(r['results']['summary']['upstream_named'])),),
        chart_data=lambda r: None, figures_t=(),
        use_note_t=('描述登记关系的结构与同期营收；不衡量影响大小，不作投资建议', 'Describes registered relationships and same-period revenue; does not measure impact; not investment advice'),
        state_description_t=('关系链断点与同期营收', 'chain breakpoints and same-period revenue'),
        inline_visuals=True,
        home_summary=lambda r: _summary(r))
