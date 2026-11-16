"""Event timeline pages: dated facts with verbatim excerpts, filing times, items the filings do not mention, next dates."""
from .common import e, stat
from .i18n import L, is_en

KIND = {'context': ('事件前', 'Before the event'), 'related': ('同期其他高管变动', 'Other officer change, same period'),
        'event': ('事件', 'Event'), 'filing': ('披露', 'Filing'), 'scheduled': ('已公布的日程', 'Announced date')}


def _lang(d):
    return (d or {}).get('en' if is_en() else 'zh', '')


def _t(t):
    return f'{t:+d}' if t else '0'


def _row(x):
    kind = L(*KIND[x['kind']])
    source = f'<a href="{e(x["url"])}">{e(x["form"])}</a>'
    if x['kind'] == 'filing':
        items = (L('；事项 ', '; items ') + e(', '.join(x['items']))) if x['items'] else ''
        what = L(f'原文在 EDGAR 接受：{x["accepted_at"]}', f'Accepted by EDGAR: {x["accepted_at"]}') + items
        return f'<tr class="muted"><td>{e(x["date"])}</td><td>{_t(x["t"])}</td><td>{kind}</td><td>{what}</td><td>{source}</td></tr>'
    quote = (f'<details><summary>{L("原文摘录", "Excerpt")}</summary><blockquote>{e(x["excerpt"])}</blockquote></details>')
    return (f'<tr><td>{e(x["date"])}</td><td>{_t(x["t"])}</td><td>{kind}</td><td>{e(_lang(x["statement"]))}{quote}</td>'
            f'<td>{source} · {e(x.get("locator") or "")}</td></tr>')


def _timeline(res):
    heads = [L('日期', 'Date'), L('相对事件日（天）', 'Days from event'), L('类别', 'Type'), L('事实', 'Fact'), L('出处', 'Source')]
    intro = L('事实只取公司申报原文写明的内容，每条附原文逐字摘录；相对事件日按日历日计算。「披露」是原文在 EDGAR 的接受时间（美东）。',
              'Facts are only what the company filings state, each with a verbatim excerpt; days from the event are calendar days. '
              '"Filing" rows give the EDGAR acceptance time (US Eastern).')
    return (f'<h3 id="event-timeline">{L("时间线", "Timeline")}</h3><p>{intro}</p><div class="scroll"><table><thead><tr>'
            + ''.join(f'<th>{h}</th>' for h in heads) + '</tr></thead><tbody>'
            + ''.join(_row(x) for x in res['timeline']) + '</tbody></table></div>')


def _not_mentioned(res):
    docs = {x['document']: x for x in res['timeline'] if x['kind'] == 'filing'}
    rows = []
    for n in res['not_mentioned']:
        where = ', '.join(f'<a href="{e(docs[d]["url"])}">{e(docs[d]["form"])}</a>' if d in docs else e(d) for d in n['documents'])
        rows.append(f'<tr><td>{e(_lang(n["item"]))}</td><td>{where}</td><td>{e(", ".join(n["terms"]))}</td></tr>')
    heads = [L('事项', 'Item'), L('检查过的原文', 'Filings checked'), L('检索词（均未出现）', 'Search terms (none found)')]
    intro = L('下列事项在所列原文中没有提及。这只说明原文没有写，不说明事情不存在，公司也可能日后另行披露。',
              'The filings listed do not mention these items. That only means the filings do not say; it does not mean the '
              'thing did not happen, and the company may disclose it later.')
    return (f'<h3 id="event-not-mentioned">{L("原文没有写明的事项", "What the filings do not say")}</h3><p>{intro}</p>'
            '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in heads) + '</tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')


def _scheduled(res):
    if not res['scheduled']:
        return ''
    items = ''.join(f'<li>{e(x["date"])} · {e(_lang(x["statement"]))}</li>' for x in res['scheduled'])
    return (f'<h3 id="event-next">{L("截至查阅日公布的后续日程", "Dates announced as of the check date")}</h3><ul>{items}</ul>'
            f'<p class="small muted">{L("日程是公司事先公布的安排，到期后应按实际发生的情况更新登记。", "These are dates the company announced in advance; update the registration once they have passed.")}</p>')


def details(r):
    res = r['results']
    ev = res['event']
    checked = ev.get('filings_checked') or {}
    note = (f'<p class="small muted">{L("截至", "Filings checked as of ")}{e(ev["as_of"])}{L(" 查阅 EDGAR 申报列表", " on the EDGAR filing list")}'
            + (f'（{e(checked.get("note"))}）' if checked.get('note') and not is_en() else '') + '</p>')
    return _timeline(res) + note + _not_mentioned(res) + _scheduled(res)


def _stats(r):
    res = r['results']
    d, s = res.get('disclosure') or {}, res['summary']
    return ('<div class="stats">' + stat(L('事件日', 'Event date'), e(res['event']['event_date']))
            + stat(L('首份披露', 'First filing'), e(d.get('date', '—')),
                   L(f'事件后 {d["lag_days"]} 天', f'{d["lag_days"]} days after the event') if d else '')
            + stat(L('原文写明的事实', 'Facts stated in filings'), str(s['counts']['event']),
                   L(f'另有事件前 {s["counts"]["context"]} 条、同期 {s["counts"]["related"]} 条',
                     f'plus {s["counts"]["context"]} before and {s["counts"]["related"]} same-period'))
            + stat(L('原文未提及', 'Not mentioned'), str(s['not_mentioned'])) + '</div>')


def _summary(r):
    res = r['results']
    d, s = res.get('disclosure') or {}, res['summary']
    return L(f"事件日 {res['event']['event_date']}，事件后 {d.get('lag_days', '—')} 天由 {d.get('form', '—')} 披露；原文写明 {s['counts']['event']} 条事件事实，"
             f"{s['not_mentioned']} 项未提及（含离任原因）",
             f"Event on {res['event']['event_date']}, disclosed by {d.get('form', '—')} {d.get('lag_days', '—')} days later; the filings state "
             f"{s['counts']['event']} event facts and do not mention {s['not_mentioned']} items, including the reason")


def make_renderer(Renderer):
    return Renderer(
        key_stats=_stats,
        method_items=lambda r: ['<li>' + e(r['methods']['description']) + '</li>' if not is_en() else
                                '<li>Facts are read from a fixed event evidence bundle and ordered by date. Each carries a verbatim '
                                'excerpt checked against the hashed filing; filing rows give the EDGAR acceptance time. Items the '
                                'filings do not mention list the filings and terms checked. No cause, impact or market reaction is inferred.</li>'],
        coverage_title_t=('时间线与原文未写明的事项', 'Timeline and what the filings do not say'),
        coverage_section=details,
        evidence_rows=lambda r: [(L('核对', 'Checks'), L('原文 SHA256、逐条摘录、未提及检索词均在生成证据包前核对。',
                                                          'Filing SHA256, each excerpt and the absent search terms were checked before the bundle was built.')),
                                 (L('人工复核', 'Manual review'), L('没有人工签认；事实陈述为技术复核。', 'No human sign-off; fact statements are technically reviewed.'))],
        evidence_summary=lambda r: [L('事实只来自公司申报原文；不使用媒体报道。', 'Facts come only from company filings; no media reports.')],
        history_columns_t=((('事件事实', 'Event facts'), lambda r: str(r['results']['summary']['counts']['event'])),),
        chart_data=lambda r: None, figures_t=(),
        use_note_t=('整理原文写明的事实与时间；不判断原因、影响或市场反应，不作投资建议',
                    'Organises what the filings state and when; no cause, impact or market reaction; not investment advice'),
        state_description_t=('事件事实与披露时间', 'event facts and filing times'),
        inline_visuals=True,
        home_summary=_summary)
