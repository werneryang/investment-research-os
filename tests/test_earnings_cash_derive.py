"""Source-backed cash subtraction and non-EBIT segment disclosure contracts."""
import copy
import hashlib

import pytest

from investment_os import earnings as er
from investment_os.research.earnings_quarter import method_text
from investment_os.site import earnings_quarter as page
from tests.test_earnings import earnings_root, filing, registration, run, write


def derived_registration(root):
    reg = registration()
    # Separate exact source bytes: the single-quarter results 6,263/4,732 are not printed.
    raw = filing() + b'<p>14,897 13,014 8,634 8,282</p>'
    er.filings_dir(root).joinpath('10q.htm').write_bytes(raw)
    reg['documents'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
    reg['documents'].append({**reg['documents'][0], 'id': 'prior',
                             'accession': '0000000000-26-000002', 'accepted_at': '2026-07-23T01:02:31Z'})
    reg['cash_flow'].update({
        'nine_months_2026': {'start': '2026-01-01', 'end': '2026-09-30', 'document': 'doc', 'cfo': 14897, 'cash_ppe': 13014},
        'six_months_2026': {'start': '2026-01-01', 'end': '2026-06-30', 'document': 'prior', 'cfo': 8634, 'cash_ppe': 8282},
        'q3_2026': {'start': '2026-07-01', 'end': '2026-09-30', 'derive': {
            'total': 'nine_months_2026', 'less': 'six_months_2026',
            'method': {'zh': '九个月减六个月', 'en': 'nine months less six months'},
            'note': {'zh': '现金流来自累计减算，不是原表直接单季值', 'en': 'Cash flow is cumulative subtraction, not a printed single-quarter row'}}}})
    reg.pop('issuer_fcf')  # no issuer-defined claim for the mechanical difference
    reg['profile']['fcf_caliber'] = 'mechanical'
    return reg


def test_derived_cash_checks_only_parents_and_preserves_both_sources(earnings_root):
    reg = derived_registration(earnings_root)
    write(earnings_root, reg)
    assert not er._number_in(filing().decode(), 6263)
    assert er.check(earnings_root).errors == []
    b = er.build_bundle(earnings_root)
    records = {x['id']: x for x in b['records']}
    value = records['ex_2026q3|cash_flow|q3_2026|cfo']
    assert value['value'] == 6263
    assert value['derived'] is True and 'document' not in value
    assert value['published_at'] == '2026-10-28'
    d = value['derivation']
    assert d['expression'] == 'nine_months_2026 - six_months_2026'
    assert [s['document'] for s in d['sources']] == ['doc', 'prior']
    assert [s['accession'] for s in d['sources']] == ['0000000000-26-000001', '0000000000-26-000002']
    assert d['accepted_at'] == '2026-10-29T00:29:06Z'
    assert b['metadata']['earnings']['ex_2026q3']['cash_derivations']['q3_2026'] == d


@pytest.mark.parametrize('mutate,fragment', [
    (lambda r: r['cash_flow']['q3_2026'].update(document='doc'), '不能混入'),
    (lambda r: r['cash_flow']['q3_2026'].update(cfo=6263), '不能混入'),
    (lambda r: r['cash_flow']['q3_2026'].update(values={'cfo': 6263}), '不能混入'),
    (lambda r: r['cash_flow']['q3_2026']['derive'].update(total='q3_2026'), '不能嵌套或循环'),
    (lambda r: r['cash_flow']['q3_2026']['derive'].update(less='nine_months_2026'), '不能嵌套或循环'),
    (lambda r: r['cash_flow']['six_months_2026'].update(derive={'total': 'q3_2026'}), '不能嵌套或循环'),
    (lambda r: r['cash_flow']['q3_2026']['derive'].update(total='missing'), '不存在'),
    (lambda r: r['cash_flow']['q3_2026']['derive'].update(note={'en': 'only English'}), '中英文'),
    (lambda r: r['cash_flow']['q3_2026'].update(start='2026-07-02'), '期间必须'),
    (lambda r: r['cash_flow']['q3_2026'].update(end='2026-10-01'), '期间必须'),
    (lambda r: r['cash_flow']['six_months_2026'].update(start='2026-02-01'), '期间必须'),
    (lambda r: r['cash_flow']['six_months_2026'].update(end='2026-09-30'), '期间必须'),
    (lambda r: r['cash_flow']['six_months_2026'].pop('start'), '期间必须'),
    (lambda r: r['cash_flow']['q3_2026'].update(start='not-a-date'), '期间必须'),
    (lambda r: r['cash_flow']['six_months_2026'].update(document='missing'), '已登记的原文'),
    (lambda r: r['documents'][1].update(accepted_at='2026-07-22'), '带时区'),
    (lambda r: r['cash_flow']['six_months_2026'].update(cfo=True), '有限数值'),
    (lambda r: r['cash_flow']['six_months_2026'].update(cash_ppe=float('nan')), '有限数值'),
    (lambda r: r['cash_flow']['six_months_2026'].update(cash_ppe=-1), '非负现金支出'),
    (lambda r: r['cash_flow']['six_months_2026'].update(cash_ppe=14000), '推导现金支出不能为负'),
])
def test_reject_invalid_cash_derivations_without_crashing(earnings_root, mutate, fragment):
    reg = derived_registration(earnings_root)
    mutate(reg)
    errors = er.profile_errors(reg)
    assert any(fragment in e for e in errors), errors
    write(earnings_root, reg)
    with pytest.raises(ValueError, match='核对未通过'):
        er.build_bundle(earnings_root)


def test_derived_inputs_still_require_original_value_presence(earnings_root):
    reg = derived_registration(earnings_root)
    reg['cash_flow']['six_months_2026']['cfo'] = 8000001
    write(earnings_root, reg)
    assert any('8,000,001 没有出现在原文' in e for e in er.check(earnings_root).errors)


def test_cash_derivations_reach_result_and_visible_cash_footnote(earnings_root):
    reg = derived_registration(earnings_root)
    reg['profile']['metrics']['cash_ppe'] = {'zh': '购置支出（不含融资租赁、扣除销售）', 'en': 'Purchases excluding finance leases, net of sales'}
    write(earnings_root, reg)
    result = run(earnings_root)
    res = result['results']
    q = next(q for q in res['quarters'] if q['period'] == 'q3_2026')
    assert q['cfo'] == 6263 and q['cash_ppe'] == 4732 and q['free_cash_flow'] == 1531
    assert not q['derived'] and q['cash_derived']
    assert q['cash_derivation'] == res['cash_derivations']['q3_2026']
    html = page._cash_table(res)
    assert '现金流来自累计减算' in html and '0000000000-26-000002' in html
    assert '算术差额' in html and '自由现金流（发行人定义）' not in html
    assert '不含融资租赁、扣除销售' in html
    assert '未核实为发行人' in method_text(reg['profile'], 5)['zh']


def test_gross_profit_segment_not_labelled_operating_profit(earnings_root):
    reg = registration()
    p = reg['profile']
    p.pop('segment_ops')
    p['findings'].pop('segment')
    p['segments'] = [{'name': {'zh': '硬件', 'en': 'Hardware'}, 'revenue': 'Services_revenue',
                      'profit': 'Services_op', 'margin': 'Services_margin',
                      'profit_label': {'zh': '毛利润', 'en': 'gross profit'},
                      'margin_label': {'zh': '毛利率', 'en': 'gross margin'}}]
    assert er.profile_errors(reg) == []
    write(earnings_root, reg)
    result = run(earnings_root)
    html = page._segment_table(result['results'])
    assert '硬件 收入' in html and '硬件 毛利润' in html and '硬件 毛利率' in html
    assert '硬件 营业利润' not in html and 'segment_op_delta_yoy' not in result['results']['comparison']
    p['segments'][0]['op'] = 'Services_op'
    assert any('不能同时写 op' in e for e in er.profile_errors(reg))
    p['segments'][0].pop('op')
    p['segments'][0].pop('profit_label')
    assert any('profit_label' in e for e in er.profile_errors(reg))


def test_existing_direct_registration_snapshot_is_unchanged(earnings_root):
    reg = registration()
    write(earnings_root, reg)
    b = er.build_bundle(earnings_root)
    assert 'cash_derivations' not in b['metadata']['earnings'][reg['earnings_id']]
    assert all('derived' not in r and 'derivation' not in r for r in b['records'])
    result = run(earnings_root)
    assert 'cash_derivations' not in result['results']
    assert all('cash_derived' not in r for r in result['results']['quarters'])
    assert '发行人定义' in page._cash_table(result['results'])
    assert '发行人定义' in method_text(reg['profile'], 5)['zh']


def test_latest_source_acceptance_is_maximum_not_always_total(earnings_root):
    reg = derived_registration(earnings_root)
    reg['documents'][1]['accepted_at'] = '2026-11-02T14:00:00-05:00'
    write(earnings_root, reg)
    rows = er.build_bundle(earnings_root)['records']
    row = next(r for r in rows if r['id'] == 'ex_2026q3|cash_flow|q3_2026|cfo')
    assert row['published_at'] == '2026-11-02'
    assert row['derivation']['accepted_at'] == '2026-11-02T14:00:00-05:00'


def test_principal_is_subtracted_separately_when_derived(earnings_root):
    reg = derived_registration(earnings_root)
    p = reg['profile']
    p.pop('fcf_caliber')
    p['fcf_deduct_principal'] = True
    p['metrics']['cash_ppe_principal'] = {'zh': '购置相关本金', 'en': 'Related principal'}
    for cf in reg['cash_flow'].values():
        if not cf.get('derive'):
            cf['cash_ppe_principal'] = 0
    reg['cash_flow']['nine_months_2026']['cash_ppe_principal'] = 100
    reg['cash_flow']['six_months_2026']['cash_ppe_principal'] = 20
    write(earnings_root, reg)
    resolved = er.resolved_cash(reg, 'q3_2026')
    assert resolved == {'cfo': 6263, 'cash_ppe': 4732, 'cash_ppe_principal': 80}
    assert er.free_cash_flow(resolved, p) == 1451
    assert er.profile_errors(reg) == []
    reg['cash_flow']['six_months_2026']['cash_ppe_principal'] = 200
    assert any('cash_ppe_principal 推导现金支出不能为负' in e for e in er.profile_errors(reg))


def test_derived_cash_end_must_match_displayed_quarter(earnings_root):
    reg = derived_registration(earnings_root)
    reg['profile']['quarters'][-1]['end'] = '2026-12-31'
    assert any('现金流推导终点必须与季度终点一致' in e for e in er.profile_errors(reg))


def test_mechanical_caliber_requires_explicit_purchase_label(earnings_root):
    reg = derived_registration(earnings_root)
    reg['profile']['metrics'].pop('cash_ppe')
    assert any('真实购置支出口径' in e for e in er.profile_errors(reg))


@pytest.mark.parametrize('change,fragment', [
    (lambda r: (r['cash_flow']['q3_2026'].update(end='2026-10-31'), r['cash_flow']['nine_months_2026'].update(end='2026-10-31')), '季度终点一致'),
    (lambda r: r['profile']['quarters'][-1].update(start='2026-07-02'), '季度起点一致'),
    (lambda r: r['profile']['year_to_date'].update(quarters=['q1_2026', 'q2_2026']), '所含季度终点一致'),
])
def test_display_period_and_ytd_do_not_silently_drift(earnings_root, change, fragment):
    reg = derived_registration(earnings_root)
    change(reg)
    assert any(fragment in e for e in er.profile_errors(reg))
