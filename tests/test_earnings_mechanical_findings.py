"""Mechanical cash cannot inherit issuer-defined FCF wording or legacy fingerprints."""
from copy import deepcopy

from investment_os.research.findings import findings, interpret, rule_fingerprint
from investment_os.site.collect import load_interpretation
from investment_os.site.findings_en import english_findings
from tests.test_earnings import earnings_root, run, registration, write


def test_mechanical_rules_separate_from_legacy_recorded_rules(earnings_root):
    write(earnings_root, registration())
    legacy = run(earnings_root)
    before = deepcopy(legacy['interpretation'])
    result = deepcopy(legacy)
    result['results']['profile']['fcf_caliber'] = 'mechanical'
    result['interpretation'] = interpret(result)
    it = result['interpretation']
    assert findings(result) == it['items']
    assert it['rule_version'] == 'earnings_quarter-mechanical-cash.v1'
    assert it['rule_fingerprint'] != rule_fingerprint('earnings_quarter')
    assert it['rule_fingerprint'] == rule_fingerprint('earnings_quarter', result)
    cash = next(i for i in it['items'] if i['id'] == 'earnings_cash')
    assert '机械差额' in cash['text'] and '不是已核实的发行人 FCF' in cash['text']
    assert '现金机械差额符号' in it['state'] and '自由现金流符号' not in it['state']
    en = next(i for i in english_findings(result, it['items']) if i['id'] == 'earnings_cash')
    assert 'mechanical difference' in en['text'] and 'not verified issuer FCF' in en['text']
    assert load_interpretation(result)['rules_changed'] is False
    assert interpret(legacy) == before
    assert load_interpretation(legacy)['rules_changed'] is False
