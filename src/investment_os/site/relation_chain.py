"""Relationship-chain pages: layered chain graph (SVG), per-edge evidence, breakpoints and same-filing revenue."""
import re

from .common import e, stat
from .i18n import L, has_cjk, te, tx
from .visuals import zh_mark

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


def _short(name):
    """起点公司的简称（去掉公司类型后缀），用于页面标题与说明：NVIDIA Corporation → NVIDIA。"""
    return re.sub(r'(,? (Corporation|Inc\.|Corp\.|Limited|Ltd\.|N\.V\.|Holding))+$', '', name or '') or name


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


def _breaks(chain):
    by = {}
    for b in chain['breakpoints']:
        by.setdefault((b['node'], b['relation']), []).append(b)
    return by


# 关系链图：Python 直接生成 SVG，不依赖脚本；逐条证据仍在下方表格。连线方向为供货方向（提供方 → 接收方）。
COL_W, COL_GAP, PAD, HEAD = 200, 64, 9, 26
NAME, META = (13, 17), (11.5, 15)  # (字号, 行高)


def _plain_kind(edge):
    """同 _kind，但返回纯文本（SVG 文字不能含 HTML 标签）。"""
    out = L(*TYPE.get(edge['type'], (edge['type'], edge['type'])))
    business = edge.get('activity_name')
    return out + (' · ' + tx(business) if business and business != TYPE.get(edge['type'], ('',))[0] else '')


def _wrap(text, size, lines):
    """按估计字宽换行：汉字约一个字号宽，其他字符约 0.56 个字号；超出行数时截断并加省略号。"""
    width = COL_W - 2 * PAD
    tokens, word = [], ''
    for ch in text:
        if has_cjk(ch):
            tokens += [word, ch] if word else [ch]
            word = ''
        elif ch == ' ':
            tokens += [word, ' '] if word else [' ']
            word = ''
        else:
            word += ch
    if word:
        tokens.append(word)
    measure = lambda t: sum(size if has_cjk(c) else size * .56 for c in t)
    out, cur = [], ''
    for t in tokens:
        if cur and measure(cur + t) > width:
            out.append(cur.rstrip())
            cur = '' if t == ' ' else t
        else:
            cur += t
    if cur.strip():
        out.append(cur.rstrip())
    if len(out) > lines:
        out = out[:lines]
        while out[-1] and measure(out[-1] + '…') > width:
            out[-1] = out[-1][:-1]
        out[-1] += '…'
    return out


def _node(key, title, rows, cls, href=None):
    """rows: [(文字, 样式类, 字号与行高, 最多行数)]"""
    lines = [(t, c, f) for text, c, f, n in rows for t in _wrap(text, f[0], n)]
    height = 2 * PAD + sum(f[1] for _, _, f in lines)
    return {'key': key, 'title': title, 'lines': lines, 'cls': cls, 'href': href, 'h': height}


def _graph_nodes(res):
    up, down = res['upstream'], res['downstream']
    breaks = {'up': _breaks(up), 'down': _breaks(down)}

    def side_nodes(chain, side):
        layers, order = [], {res['root']: 0}
        for i, edges in enumerate(chain['layers'], 1):
            groups = {}
            for x in edges:
                groups.setdefault(x['to'], []).append(x)
            ids = sorted(groups, key=lambda t: order.get(groups[t][0]['from'], 0))  # 跟随上一层的顺序，减少交叉
            order = {t: n for n, t in enumerate(ids)}
            nodes = []
            for t in ids:
                edges_in = groups[t]
                first = edges_in[0]
                rows = [(tx(first['to_name']), 'cg-name', NAME, 3)]
                for x in edges_in:
                    value = (x.get('share') or {}).get('value')
                    rows.append((_plain_kind(x) + (f' · {L("占比", "Share")} {value * 100:.1f}%' if value is not None else ''),
                                 'cg-meta', META, 2))
                tags = []
                if any(x['status'] not in ('reviewed', 'confirmed') for x in edges_in):
                    tags.append(L('未复核', 'Not reviewed'))
                if any(x['evidence_class'] != 'primary' or x.get('external_path') for x in edges_in):
                    tags.append(L('外部来源', 'External source'))
                if tags:
                    rows.append((' · '.join(tags), 'cg-meta', META, 1))
                reasons = list(dict.fromkeys(_reason(b['reason']) for x in edges_in
                                             for b in breaks[side].get((t, x['relation']), [])))
                if reasons:
                    rows.append((L('停止：', 'Stops: ') + ' · '.join(reasons), 'cg-warn', META, 2))
                cls = ['cg-node']
                if first['counterparty_type'] == 'anonymous':
                    cls.append('anon')
                if all(x['status'] not in ('reviewed', 'confirmed') for x in edges_in):
                    cls.append('unreviewed')
                if any(x['evidence_class'] != 'primary' or x.get('external_path') for x in edges_in):
                    cls.append('external')
                title = '\n'.join([tx(first['to_name'])] + [r[0] for r in rows[1:]])
                nodes.append(_node((side, i, t), title, rows, cls))
            layers.append((nodes, edges))
        return layers

    up_layers, down_layers = side_nodes(up, 'up'), side_nodes(down, 'down')
    cols = []
    for i in range(len(up_layers), 0, -1):
        cols.append((L(f'上游第 {i} 层', f'Upstream layer {i}'), up_layers[i - 1][0]))
    root = _node(('root',), tx(res['root_name']),
                 [(tx(res['root_name']), 'cg-name', NAME, 3), (L('起点', 'Starting point'), 'cg-meta', META, 1)], ['cg-node', 'root'])
    cols.append((L('起点', 'Starting point'), [root]))
    for i, (nodes, _) in enumerate(down_layers, 1):
        cols.append((L(f'下游第 {i} 层', f'Downstream layer {i}'), list(nodes)))
    if res['reverse_search']:
        searched, found = res['summary']['reverse_searched'], res['summary']['reverse_found']
        counts = L(f'{searched} 家样本公司年报，{found} 家点名 {tx(_short(res["root_name"]))}',
                   f"{found} of {searched} sample companies' filings name {_short(res['root_name'])}")
        rev = _node(('reverse',), counts, [(L('反向检索', 'Reverse search'), 'cg-link', NAME, 1), (counts, 'cg-meta', META, 3)],
                    ['cg-node', 'anon'], href='#chain-reverse-search')
        if len(cols) == len(up_layers) + 1:
            cols.append((L('下游第 1 层', 'Downstream layer 1'), []))
        cols[len(up_layers) + 1][1].append(rev)
    cols = [c for c in cols if c[1]]
    edges = []
    for side, layers in (('up', up_layers), ('down', down_layers)):
        for i, (_, layer_edges) in enumerate(layers, 1):
            for x in layer_edges:
                near = ('root',) if i == 1 else (side, i - 1, x['from'])
                far = (side, i, x['to'])
                edges.append((far, near, x) if side == 'up' else (near, far, x))
    return cols, edges


def chain_graph(r):
    """分层关系图（SVG）：上游在左、起点居中、下游在右；同一对主体的多条关系并排画出。"""
    res = r['results']
    cols, edges = _graph_nodes(res)
    gap = 12
    height = max(sum(n['h'] for n in nodes) + gap * (len(nodes) - 1) for _, nodes in cols)
    width = len(cols) * COL_W + (len(cols) - 1) * COL_GAP
    pos, parts = {}, []
    for c, (label, nodes) in enumerate(cols):
        x = c * (COL_W + COL_GAP)
        parts.append(f'<text class="cg-col" x="{x}" y="14">{e(label)}</text>')
        y = HEAD + (height - sum(n['h'] for n in nodes) - gap * (len(nodes) - 1)) / 2
        for n in nodes:
            pos[n['key']] = (x, y, n['h'])
            body = [f'<rect class="cg-box" x="{x}" y="{y:.1f}" width="{COL_W}" height="{n["h"]:.1f}" rx="7"/>']
            ty = y + PAD
            for text, cls, (size, lh) in n['lines']:
                ty += lh
                body.append(f'<text class="{cls}" x="{x + PAD}" y="{ty - (lh - size) / 2 - 2:.1f}">{e(text)}</text>')
            g = f'<g class="{" ".join(n["cls"])}"{zh_mark(n["title"])}><title>{e(n["title"])}</title>{"".join(body)}</g>'
            parts.append(f'<a href="{e(n["href"])}">{g}</a>' if n['href'] else g)
            y += n['h'] + gap
    pairs = {}
    for a, b, _ in edges:
        pairs[(a, b)] = pairs.get((a, b), 0) + 1
    seen, lines = {}, []
    for a, b, x in edges:
        if a not in pos or b not in pos:
            continue
        k = seen[(a, b)] = seen.get((a, b), -1) + 1
        off = (k - (pairs[(a, b)] - 1) / 2) * 6
        ax, ay, ah = pos[a]
        bx, by, bh = pos[b]
        x1, y1, x2, y2 = ax + COL_W, ay + ah / 2 + off, bx - 5, by + bh / 2 + off
        mid = (x1 + x2) / 2
        cls = ['cg-edge']
        if x['status'] not in ('reviewed', 'confirmed'):
            cls.append('unreviewed')
        if x['evidence_class'] != 'primary' or x.get('external_path'):
            cls.append('external')
        value = (x.get('share') or {}).get('value')
        tip = f'{tx(x["to_name"] if a[0] == "up" else x["from_name"])} → {tx(x["from_name"] if a[0] == "up" else x["to_name"])} · {_plain_kind(x)}'
        tip += f' · {L("占比", "Share")} {value * 100:.1f}%' if value is not None else ''
        lines.append(f'<path class="{" ".join(cls)}" d="M{x1:.1f},{y1:.1f} C{mid:.1f},{y1:.1f} {mid:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"'
                     f' marker-end="url(#cg-arrow)"{zh_mark(tip)}><title>{e(tip)}</title></path>')
    label = L(f'{tx(res["root_name"])} 的上下游关系图', f'Upstream and downstream relationships of {res["root_name"]}')
    defs = ('<defs><marker id="cg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            '<path class="cg-arrow" d="M0,0 L10,5 L0,10 z"/></marker></defs>')
    svg = (f'<svg class="chain-graph" viewBox="-2 0 {width + 4} {height + HEAD + 4:.0f}" role="group" aria-label="{e(label)}">'
           f'<title>{e(label)}</title>{defs}{"".join(lines)}{"".join(parts)}</svg>')
    legend = L('箭头为供货方向（提供方 → 接收方）；虚线框为未点名的对手方，虚线连线为外部来源，淡色为未复核；橙色文字为停止展开的原因。'
               '连线不表示影响大小，各占比的分母不同，只按原文口径标注。悬停查看完整名称与关系。',
               'Arrows point from provider to recipient; dashed boxes are unnamed counterparties, dashed links external sources, '
               'faded items not reviewed; orange text gives why expansion stopped. A link does not measure impact; shares have '
               'different denominators and are shown only as disclosed. Hover for full names and relationships.')
    return f'<div class="chain-graph-wrap">{svg}</div><p class="small muted">{legend}</p>'


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
    root = _short(res['root_name'])
    notes = ''.join(f'<li><a href="{e(n["url"])}">10-K</a> · {e(n["locator"])}<blockquote>{e(n["excerpt"])}</blockquote>'
                    f'<p class="small muted">{te(n.get("limits") or "")}</p></li>' for n in res['downstream_notes'])
    rows = ''.join(f'<tr><td>{te(q["subject"])}</td><td><a href="{e(q["url"])}">{e(q["form"])}</a> · {e(q["period_end"])}</td>'
                   f'<td>{L("点名", "Named") if q["result"] == "found" else L("未点名", "Not named")}</td><td>{te(q["method"])}</td></tr>'
                   for q in res['reverse_search'])
    heads = [L('公司', 'Company'), L('年报（财年末）', 'Annual report (fiscal year end)'), L(f'是否点名 {root}', f'Names {root}?'),
             L('方法', 'Method')]
    return (_edge_table(res['downstream'], 'chain-downstream', L(f'下游：{root} 的客户', f'Downstream: {root} customers'))
            + f'<h4>{L(f"{root} 原文中的客户类型（不生成具名关系）", f"Customer types in {root} filing (no named relationships)")}</h4><ul>{notes}</ul>'
            + f'<h4 id="chain-reverse-search">{L(f"反向检索：客户自己的年报是否点名 {root}", f"Reverse search: do customers name {root} in their own filings?")}</h4>'
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
    root = _short(res['root_name'])
    heads = [L('公司与链上位置', 'Company and position'), L('单位', 'Unit'), L('财年 1', 'Fiscal year 1'),
             L('财年 2', 'Fiscal year 2'), L('财年 3', 'Fiscal year 3')]
    note = L('每家公司只用自己的一份年报（三个财年），同比只在同一申报、同一币种内计算；财年截止月不同，不按日历年对齐；不计算相关系数，'
             f'同期变化不说明由 {root} 带动。', 'Each company uses one of its own annual reports (three fiscal years); growth is computed '
             'within one filing and currency only. Fiscal years end in different months and are not aligned to calendar years; no '
             f'correlations are computed, and co-movement does not show that {root} drove it.')
    return (f'<h3 id="chain-revenue">{L(f"同期营收：{root} 与上游第 1 层", f"Same-period revenue: {root} and upstream layer 1")}</h3><p>{note}</p>'
            '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in heads) + '</tr></thead><tbody>' + ''.join(rows)
            + '</tbody></table></div>' + (f'<p class="small muted">{L("尚未取得年报：", "Annual reports not yet obtained: ")}{missing}</p>' if missing else ''))


SIDE = {'competition': ('竞争', 'Competition'), 'partnership': ('合作', 'Partnership'), 'substitution': ('替代', 'Substitution')}


def _side(res):
    seen, items = set(), []
    for s in res['upstream']['side_relations'] + res['downstream']['side_relations']:
        if s['relation'] in seen:  # 上下游两条链都可能列出同一条旁注关系
            continue
        seen.add(s['relation'])
        label = L(*SIDE.get(s['type'], (s['type'], s['type'])))
        items.append(f'<li>{" ↔ ".join(te(n) for n in s["party_names"])} · {label}'
                     + (f' · {te(s["market"])}' if s.get('market') else '') + '</li>')
    return (f'<details><summary>{L("竞争与合作关系（旁注，不当作传导路径）", "Competition and partnership (side notes; not a transmission path)")}</summary><ul>{"".join(items)}</ul></details>'
            if items else '')


def details(r):
    res = r['results']
    return (chain_graph(r)
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
    res = r['results']
    s, root = res['summary'], _short(res['root_name'])
    b = s['breakpoints']['upstream']
    layer2 = res['upstream']['layers'][1] if len(res['upstream']['layers']) > 1 else []
    anon = sum(x['counterparty_type'] == 'anonymous' for x in layer2)
    named = len(layer2) - anon
    two_zh = '；'.join(x for x in (f'点名 {named} 家公司' if named else '', f'{anon} 项为未点名的投入类别' if anon else '') if x)
    two_en = '; '.join(x for x in (f'{named} named companies' if named else '', f'{anon} unnamed input categories' if anon else '') if x)
    return L(f"上游第 1 层点名 {s['upstream_named']} 家供应方，其中 {b.get('activity_unknown', 0)} 家业务未定、"
             f"{b.get('not_searched', 0)} 处尚未查阅；第 2 层{two_zh or '没有关系'}；下游具名客户 {s['downstream_named']} 家，"
             f"{s['reverse_searched']} 家样本公司年报有 {s['reverse_found']} 家点名 {root}",
             f"Upstream layer 1 names {s['upstream_named']} suppliers ({b.get('activity_unknown', 0)} with business not stated, "
             f"{b.get('not_searched', 0)} not yet read); layer 2: {two_en or 'no relationships'}; {s['downstream_named']} named downstream "
             f"customers, and {s['reverse_found']} of {s['reverse_searched']} sample companies' filings name {root}")


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
