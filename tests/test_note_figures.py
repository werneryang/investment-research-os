"""研究报告图块：数值只来自公开记录，引用不成立就报错，插入位置按二级标题。"""
from pathlib import Path
import re
import shutil

import pytest
import yaml

from investment_os.notes import load_notes, parser
from investment_os.site.note_figures import FigureError, SPEC_DIR, evidence_tags, load_spec, nice_scale, render_body
from tests.conftest import PROJECT_ROOT

NVDA = 'NVDA-20261117-q3-fy27'


def real_notes():
    notes, bad = load_notes(PROJECT_ROOT)
    assert not bad
    return {n['id']: n for n in notes}


def test_every_committed_spec_resolves_and_renders_against_its_note():
    notes = real_notes()
    specs = sorted((PROJECT_ROOT / SPEC_DIR).glob('*.yaml'))
    assert specs
    for path in specs:
        note = notes[path.stem]  # 图块文件名必须对应已发布的报告
        spec = load_spec(PROJECT_ROOT, note)
        page = render_body(parser(), note['body'], spec)
        assert page.count('<figure class="nf"') + page.count('class="nf-kpis"') == len(spec['figures'])


def test_nvda_numbers_come_from_the_record_and_sit_in_the_right_sections():
    note = real_notes()[NVDA]
    page = render_body(parser(), note['body'], load_spec(PROJECT_ROOT, note))
    record = yaml.safe_load((PROJECT_ROOT / 'methodology/records/sec-nvda-earnings-20261117.yaml').read_text())
    assert f"{record['quarter_inputs']['FY27Q3']['revenue'] / 1000:,.1f}" in page  # 115.8
    assert f"{record['guidance']['computed_midpoint_vs_current_pct']:.1f}%" in page  # 标题里代入的 12.2%
    # 数字条在「一句话结论」节末、营收图在「发生了什么」标题之后
    assert page.index('nf-kpis') < page.index('<h2>发生了什么</h2>') < page.index('fig-revenue-5q') < page.index('<table>')
    # 出处行只列本图用到的字段（标题代入的字段不串到下一张图）
    commit = page[page.index('id="fig-commitments"'):]
    commit = commit[:commit.index('</figure>')]
    assert 'CFO_to_NI' not in commit and 'commitments.supply_and_capacity' in commit
    assert '<span class="ev ev-infer">推断</span>' in page and '【推断】' not in page


def write_spec(root, note, figures, records=None):
    (root / SPEC_DIR).mkdir(parents=True, exist_ok=True)
    spec = {'schema_version': 'note-figures.v1', 'note': note['id'],
            'records': records or {'R': 'methodology/records/sec-nvda-earnings-20261117.yaml'}, 'figures': figures}
    (root / SPEC_DIR / f"{note['id']}.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True))


@pytest.fixture
def sandbox(tmp_path):
    shutil.copytree(PROJECT_ROOT / 'methodology/records', tmp_path / 'methodology/records')
    return tmp_path, real_notes()[NVDA]


BAR = {'type': 'bar', 'section': '发生了什么', 'title': 't', 'x': ['FY27Q3'], 'value': 'R:quarter_inputs.{x}.revenue'}


@pytest.mark.parametrize('change, message', [
    ({'value': 115.8}, '不接受手填'),                                   # 手填数字
    ({'value': 'R:quarter_inputs.{x}.no_such_field'}, 'no_such_field'),  # 字段不存在
    ({'value': 'R:quarter_inputs.{x}'}, '不是数值'),                     # 不是数值
    ({'value': 'S:quarter_inputs.{x}.revenue'}, '未声明的记录'),
    ({'type': 'pie'}, 'type'),
])
def test_bad_references_fail_loudly(sandbox, change, message):
    root, note = sandbox
    write_spec(root, note, [{**BAR, **change}])
    with pytest.raises(FigureError, match=message):
        load_spec(root, note)


def test_record_must_be_public_and_linked_from_the_note(sandbox):
    root, note = sandbox
    write_spec(root, note, [BAR], {'R': 'methodology/records/sec-aapl-value-chain-20261117.yaml'})
    with pytest.raises(FigureError, match='没有链接'):
        load_spec(root, note)
    write_spec(root, note, [BAR], {'R': 'config/notes.yaml'})
    with pytest.raises(FigureError, match='methodology/records'):
        load_spec(root, note)


def test_section_must_match_exactly_one_heading(sandbox):
    root, note = sandbox
    write_spec(root, note, [{**BAR, 'section': '不存在的节'}])
    with pytest.raises(FigureError, match='匹配到 0 处'):
        render_body(parser(), note['body'], load_spec(root, note))


def test_notes_without_spec_render_unchanged_except_evidence_tags(sandbox):
    root, note = sandbox
    assert load_spec(root, note) is None
    md = parser()
    assert render_body(md, note['body'], None) == evidence_tags(md.render(note['body']))


def test_axis_ticks_are_round():
    assert nice_scale(133.9) == (150, 50)
    assert nice_scale(390) == (400, 100)
    assert nice_scale(0.863)[0] == 1.0


# ---- 第二批图型：收入结构条、层次 × 时态矩阵、供应商依赖斜率图（AAPL）、三级标题定位 ----

AAPL = 'AAPL-20261117-value-chain'
LAYOUT = 'methodology/records/sec-aapl-value-chain-layout-20261127.yaml'


def aapl_page():
    note = real_notes()[AAPL]
    return note, render_body(parser(), note['body'], load_spec(PROJECT_ROOT, note))


def figure_html(page, fig_id):
    chunk = page[page.index(f'id="fig-{fig_id}"'):]
    return chunk[:chunk.index('</figure>')]


def test_aapl_figures_sit_under_their_h3_headings_and_numbers_come_from_records():
    note, page = aapl_page()
    rec = yaml.safe_load((PROJECT_ROOT / 'methodology/records/sec-aapl-value-chain-20261117.yaml').read_text())
    sup = yaml.safe_load((PROJECT_ROOT / 'methodology/records/sec-aapl-supplier-concentration-20261117.yaml').read_text())
    # 三张图各在自己的三级标题之后、该节第一张表之前（节末的数字条除外）
    order = [page.index('<h3>业务体量与渠道'), page.index('id="fig-revenue-mix"'),
             page.index('<h3>一手具名关系'), page.index('id="fig-layer-tense"'),
             page.index('<h3>供应商收入对 Apple 的依赖'), page.index('id="fig-supplier-dependency"')]
    assert order == sorted(order)
    assert page.index('id="fig-kpis"') < page.index('<h2>发生了什么</h2>')
    mix = figure_html(page, 'revenue-mix')
    cats = rec['financial_context']['categories']
    assert f"{cats['iPhone']['reported_revenue']:,}" in mix and f"{cats['Services']['computed_share_percent']:.1f}%" in mix
    dep = figure_html(page, 'supplier-dependency')
    assert f"{sup['findings']['skyworks']['percent_supplier_revenue'][0]:g}%" in dep
    assert 'Broadcom' in dep and '不画' in dep and '≥10%' in dep  # 下限画空心点，匿名客户不画进线


def test_matrix_counts_every_relationship_once_and_matches_the_record():
    note, page = aapl_page()
    rec = yaml.safe_load((PROJECT_ROOT / 'methodology/records/sec-aapl-value-chain-20261117.yaml').read_text())
    lay = yaml.safe_load((PROJECT_ROOT / LAYOUT).read_text())
    assert {i['id'] for i in lay['items']} == {r['id'] for r in rec['relationships']}
    html_text = figure_html(page, 'layer-tense')
    assert f"已登记的 {len(rec['relationships'])} 条具名关系" in html_text
    cells = [int(n) for n in re.findall(r'<td class="nf-mx-c[^"]*"><b>(\d+)</b>', html_text)]
    assert sum(cells) == len(rec['relationships'])
    assert 'ev-infer' in html_text  # 归类是整理，标推断


@pytest.fixture
def aapl_sandbox(tmp_path):
    shutil.copytree(PROJECT_ROOT / 'methodology/records', tmp_path / 'methodology/records')
    (tmp_path / SPEC_DIR).mkdir(parents=True)
    shutil.copy(PROJECT_ROOT / SPEC_DIR / f'{AAPL}.yaml', tmp_path / SPEC_DIR)
    return tmp_path, real_notes()[AAPL]


def test_supplement_record_needs_an_unchanged_parent(aapl_sandbox):
    root, note = aapl_sandbox
    assert load_spec(root, note)  # 原样可用
    parent = root / 'methodology/records/sec-aapl-value-chain-20261117.yaml'
    parent.write_text(parent.read_text() + '\n# edited\n')  # 父记录被改动，补充记录的哈希对不上
    with pytest.raises(FigureError, match='没有链接'):
        load_spec(root, note)


def test_matrix_rejects_missing_or_unknown_relationships(aapl_sandbox):
    root, note = aapl_sandbox
    path = root / LAYOUT
    lay = yaml.safe_load(path.read_text())
    lay['items'] = lay['items'][1:]  # 少了一条关系
    path.write_text(yaml.safe_dump(lay, allow_unicode=True))
    with pytest.raises(FigureError, match='不一致'):
        load_spec(root, note)
    lay = yaml.safe_load((PROJECT_ROOT / LAYOUT).read_text())
    lay['items'][0]['tense'] = 'someday'
    path.write_text(yaml.safe_dump(lay, allow_unicode=True))
    with pytest.raises(FigureError, match='不在登记的取值里'):
        load_spec(root, note)


def test_stack_parts_must_add_up_and_slope_pairs_periods_with_values(aapl_sandbox):
    root, note = aapl_sandbox
    path = root / SPEC_DIR / f'{AAPL}.yaml'
    spec = yaml.safe_load(path.read_text())
    mix = next(f for f in spec['figures'] if f['id'] == 'revenue-mix')
    mix['parts'].pop()  # 去掉 iPad，合计不再等于总额
    path.write_text(yaml.safe_dump(spec, allow_unicode=True))
    with pytest.raises(FigureError, match='合计与总额不符'):
        load_spec(root, note)
    spec = yaml.safe_load((PROJECT_ROOT / SPEC_DIR / f'{AAPL}.yaml').read_text())
    dep = next(f for f in spec['figures'] if f['id'] == 'supplier-dependency')
    dep['x'] = ['FY2023', 'FY2025', 'FY2026']  # 记录里没有 FY2023
    path.write_text(yaml.safe_dump(spec, allow_unicode=True))
    with pytest.raises(FigureError, match='没有期间'):
        load_spec(root, note)


def test_googl_figures_use_derived_q4_cloud_revenue_and_stay_in_their_sections():
    note = real_notes()['GOOGL-20261116-q3-26']
    page = render_body(parser(), note['body'], load_spec(PROJECT_ROOT, note))
    rec = yaml.safe_load((PROJECT_ROOT / 'methodology/records/sec-googl-earnings-20261116.yaml').read_text())['method_output']
    cloud = figure_html(page, 'cloud-5q')
    assert f"{rec['Q4_2025_derived_inputs']['values']['Cloud_revenue'] / 1000:.1f}" in cloud  # 17.7：推得的 2025Q4
    assert page.index('<h2>发生了什么</h2>') < page.index('id="fig-cloud-5q"') < page.index('<h2>质量与可持续性</h2>') \
        < page.index('id="fig-cash-vs-capex"') < page.index('<h2>指引与待验证的判断</h2>') < page.index('id="fig-rpo-3q"')


def test_nvda_guidance_figure_compares_prior_range_with_actual_and_flags_outside():
    note = real_notes()[NVDA]
    page = render_body(parser(), note['body'], load_spec(PROJECT_ROOT, note))
    rec = yaml.safe_load((PROJECT_ROOT / 'methodology/records/sec-nvda-earnings-20261117.yaml').read_text())
    prior = rec['prior_guidance_check']
    fig = figure_html(page, 'guidance-vs-prior')
    assert f"{prior['actual_revenue'] / 1000:.1f}" in fig and f"{prior['actual_minus_upper_bound'] / 1000:.1f}" in fig
    assert page.index('<h2>质量与可持续性</h2>') < page.index('id="fig-guidance-vs-prior"')
    # 营收与毛利率的上季实际都在上季区间外（用第 2 色），Q4 只有区间没有实际点
    assert fig.count('class="nf-dot nf-s2"') == 2 and 'nf-dot nf-s1' not in fig
    assert '71–72' in fig  # 没有中点时标区间两端
    assert '指引区间 126.1–133.9，中点 130.0' in fig


def test_range_rejects_inverted_or_out_of_axis_values(sandbox):
    root, note = sandbox
    row = {'label': 'FY27Q4', 'low': 'R:guidance.computed_revenue_high', 'high': 'R:guidance.computed_revenue_low'}
    write_spec(root, note, [{'type': 'range', 'section': '发生了什么', 'title': 't', 'y_min': 100, 'y_max': 140, 'rows': [row]}])
    with pytest.raises(FigureError, match='下限大于上限'):
        load_spec(root, note)
    row = {'label': 'FY27Q4', 'low': 'R:guidance.computed_revenue_low', 'high': 'R:guidance.computed_revenue_high'}
    write_spec(root, note, [{'type': 'range', 'section': '发生了什么', 'title': 't', 'y_min': 100, 'y_max': 130, 'rows': [row]}])
    with pytest.raises(FigureError, match='超出'):
        load_spec(root, note)


# ---- 第三批图型：瀑布、阶段条、层级树、时间线、情景区间 / 敏感性 ----
# 现有报告还用不到这些图型，用测试夹具：一份假报告加一份假记录，只存在于临时目录。

FIX_REC = 'methodology/records/fixture-figures.yaml'
FIX_NOTE = {'id': 'TEST-20261119-fixture',
            'body': f'# 测试报告\n\n记录：[{FIX_REC}]({FIX_REC})\n\n## 增长从哪里来\n\n正文。\n\n## 指引与待验证\n\n正文。\n'}
FIX_DATA = {
    'growth': {'base': 100.0, 'volume': 12.0, 'share': 3.0, 'price': -2.0, 'mix': 1.5, 'scope': 0.6, 'current': 115.0,
               'current_rounded': 115.5},
    'funnel': {'unit': '个项目', 'unit_usd': '百万美元', 'serviceable': 40, 'qualified': 18, 'design_win': 9,
               'production': 4, 'bigger': 50},
    'tree': {
        'nodes': [
            {'id': 'semi', 'label': '半导体', 'aggregation': 'sum', 'value': 100},
            {'id': 'logic', 'label': '逻辑', 'parent': 'semi', 'lifecycle': 'growth', 'value': 60},
            {'id': 'memory', 'label': '存储', 'parent': 'semi', 'lifecycle': 'cyclical', 'value': 40},
            {'id': 'dram', 'label': 'DRAM', 'parent': 'memory', 'lifecycle': 'cyclical'},
            {'id': 'equip', 'label': '设备', 'lifecycle': 'mature'},
        ],
        'relations': [{'from': 'equip', 'to': 'logic', 'type': 'upstream_downstream'},
                      {'from': 'logic', 'to': 'memory', 'type': 'additive'}],
    },
    'events': {'as_of': '2026-11-19', 'items': [
        {'id': 'q3', 'label': 'Q3 财报', 'date': '2026-11-17', 'status': 'occurred'},
        {'id': 'ramp', 'label': '新产线爬坡', 'start': '2026-12-01', 'end': '2027-06-30', 'status': 'pending'},
        {'id': 'q4', 'label': 'Q4 财报', 'date': '2027-02-20', 'status': 'pending'},
    ]},
    'valuation': {'price': 152.0, 'bear': [90.0, 110.0, 100.0], 'base': [130.0, 170.0, 150.0], 'bull': [180.0, 240.0, 210.0],
                  'sens': {'fair': 150.0, 'growth': [120.0, 185.0], 'margin': [140.0, 161.0], 'wacc': [175.0, 128.0]}},
}

WATERFALL = {'id': 'wf', 'type': 'waterfall', 'section': '增长从哪里来', 'title': '收入增长主要来自数量', 'unit': '亿元',
             'start': {'label': '基期', 'value': 'R:growth.base'},
             'steps': [{'label': '数量', 'value': 'R:growth.volume', 'evidence': 'calc'},
                       {'label': '份额', 'value': 'R:growth.share', 'evidence': 'infer'},
                       {'label': '价格', 'value': 'R:growth.price'},
                       {'label': '组合', 'value': 'R:growth.mix'},
                       {'label': '范围', 'value': 'R:growth.scope', 'evidence': 'fwd'}],
             'end': {'label': '本期', 'value': 'R:growth.current'}, 'tolerance': 0.2}
FUNNEL = {'id': 'fn', 'type': 'funnel', 'section': '指引与待验证', 'title': '量产阶段只剩 4 个项目', 'unit': '个项目',
          'stages': [{'label': '可参与需求', 'value': 'R:funnel.serviceable', 'unit_ref': 'R:funnel.unit'},
                     {'label': '认证', 'value': 'R:funnel.qualified'},
                     {'label': '设计导入与合同', 'value': 'R:funnel.design_win'},
                     {'label': '量产与收入', 'value': 'R:funnel.production', 'evidence': 'fact'}]}
TREE = {'id': 'tr', 'type': 'tree', 'section': '增长从哪里来', 'title': '逻辑占六成', 'unit': '亿元',
        'nodes': 'R:tree.nodes', 'relations': 'R:tree.relations', 'evidence': 'infer'}
TIMELINE = {'id': 'tl', 'type': 'timeline', 'section': '指引与待验证', 'title': '两件事待兑现',
            'events': 'R:events.items', 'as_of': 'R:events.as_of'}
SCENARIO = {'id': 'sc', 'type': 'scenario', 'section': '指引与待验证', 'title': '现价接近基准情景中点', 'unit': '美元',
            'x_min': 50, 'x_max': 250, 'reference': {'label': '现价', 'value': 'R:valuation.price'},
            'rows': [{'label': name, 'low': f'R:valuation.{key}[0]', 'high': f'R:valuation.{key}[1]', 'mid': f'R:valuation.{key}[2]'}
                     for name, key in (('悲观', 'bear'), ('基准', 'base'), ('乐观', 'bull'))]}
TORNADO = {'id': 'tn', 'type': 'scenario', 'mode': 'sensitivity', 'section': '指引与待验证', 'title': '增速假设影响最大',
           'unit': '美元', 'x_min': 100, 'x_max': 200, 'base': {'label': '基准公允价值', 'value': 'R:valuation.sens.fair'},
           'reference': {'label': '现价', 'value': 'R:valuation.price'},
           'rows': [{'label': '利润率 ±2pp', 'low': 'R:valuation.sens.margin[0]', 'high': 'R:valuation.sens.margin[1]'},
                    {'label': '增速 ±3pp', 'low': 'R:valuation.sens.growth[0]', 'high': 'R:valuation.sens.growth[1]'},
                    {'label': '折现率 ∓1pp', 'low': 'R:valuation.sens.wacc[0]', 'high': 'R:valuation.sens.wacc[1]'}]}


@pytest.fixture
def fixture_root(tmp_path):
    (tmp_path / 'methodology/records').mkdir(parents=True)
    return tmp_path


def render_fixture(root, figures, data=None):
    import copy
    (root / FIX_REC).write_text(yaml.safe_dump(copy.deepcopy(data or FIX_DATA), allow_unicode=True))
    write_spec(root, FIX_NOTE, figures, {'R': FIX_REC})
    return render_body(parser(), FIX_NOTE['body'], load_spec(root, FIX_NOTE))


def fixture_with(change):
    import copy
    data = copy.deepcopy(FIX_DATA)
    change(data)
    return data


def test_new_types_render_without_scripts_and_only_palette_colours(fixture_root):
    page = render_fixture(fixture_root, [WATERFALL, FUNNEL, TREE, TIMELINE, SCENARIO, TORNADO])
    for fid in ('wf', 'fn', 'tr', 'tl', 'sc', 'tn'):
        html_text = figure_html(page, fid)
        assert '<svg' in html_text and '<script' not in html_text and 'onclick' not in html_text
        assert not re.search(r'#[0-9a-fA-F]{3,6}\b', html_text)  # 颜色只走样式表的 --c1…--c8
    assert page.index('<h2>增长从哪里来</h2>') < page.index('id="fig-wf"') < page.index('<h2>指引与待验证</h2>') < page.index('id="fig-fn"')
    css = (PROJECT_ROOT / 'site/assets/style.css').read_text()
    new_css = css[css.index('/* 第三批图型'):]
    assert not re.search(r'#[0-9a-fA-F]{3,6}\b', new_css)


def test_waterfall_bridges_start_to_end_and_marks_evidence(fixture_root):
    wf = figure_html(render_fixture(fixture_root, [WATERFALL]), 'wf')
    assert '+12.0' in wf and '−2.0' in wf and '115.0' in wf
    assert 'class="nf-s3"' in wf and 'class="nf-s8"' in wf  # 增项、减项各一色
    assert wf.count('class="nf-guide"') == 1  # 范围一项标展望，画虚线框
    assert '推断' in wf and '<code>growth.volume</code>' in wf
    assert '+0.100' in wf  # 残差 100+15.1−115 = 0.1，在容差内并写进数据表


@pytest.mark.parametrize('change, message', [
    ({'tolerance': 0}, '超出容差'),
    ({'end': {'label': '本期', 'value': 'R:growth.current_rounded'}}, '超出容差'),
    ({'steps': []}, '至少要有一个'),
    ({'start': {'label': '基期', 'value': 100}}, '不接受手填'),
    ({'steps': [{'label': '数量', 'value': 'R:growth.volume', 'evidence': 'guess'}]}, 'evidence'),
])
def test_waterfall_rejects_bridges_that_do_not_close(fixture_root, change, message):
    with pytest.raises(FigureError, match=message):
        render_fixture(fixture_root, [{**WATERFALL, **change}])


def test_funnel_shows_stage_conversion(fixture_root):
    fn = figure_html(render_fixture(fixture_root, [FUNNEL]), 'fn')
    assert '上一阶段的 45%' in fn and '44.4%' in fn  # 9/18 显示 50%，4/9 = 44.4%
    assert '<code>funnel.unit</code>' in fn


def test_funnel_rejects_mixed_units_and_unexplained_increases(fixture_root):
    mixed = {**FUNNEL, 'stages': [*FUNNEL['stages'][:3], {'label': '量产与收入', 'value': 'R:funnel.production', 'unit_ref': 'R:funnel.unit_usd'}]}
    with pytest.raises(FigureError, match='单位'):
        render_fixture(fixture_root, [mixed])
    grow = [FUNNEL['stages'][0], {'label': '认证', 'value': 'R:funnel.bigger'}]
    with pytest.raises(FigureError, match='大于上一阶段'):
        render_fixture(fixture_root, [{**FUNNEL, 'stages': grow}])
    grow[1] = {**grow[1], 'allow_increase': True}
    with pytest.raises(FigureError, match='note'):
        render_fixture(fixture_root, [{**FUNNEL, 'stages': grow}])
    grow[1] = {**grow[1], 'note': '认证口径含存量项目'}
    assert 'id="fig-fn"' in render_fixture(fixture_root, [{**FUNNEL, 'stages': grow}])
    with pytest.raises(FigureError, match='unit'):
        render_fixture(fixture_root, [{k: v for k, v in FUNNEL.items() if k != 'unit'}])


def test_tree_draws_lifecycle_and_relations_and_never_sums_upstream(fixture_root):
    tr = figure_html(render_fixture(fixture_root, [TREE]), 'tr')
    assert '成长' in tr and '周期' in tr and '成熟' in tr
    assert 'Σ 子项相加' in tr and '子项不相加' in tr  # 半导体声明相加；存储没有
    assert 'marker-end="url(#nf-arrow)"' in tr and 'nf-rel-upstream_downstream' in tr
    assert tr.count('marker-end') == 1  # 只有上下游画箭头
    assert '<code>tree.nodes</code>' in tr


@pytest.mark.parametrize('change, message', [
    (lambda d: d['tree']['nodes'].append({'id': 'logic', 'label': '重复'}), '节点 id 重复'),
    (lambda d: d['tree']['relations'].append({'from': 'logic', 'to': 'nope', 'type': 'overlap'}), '不存在的节点'),
    (lambda d: d['tree']['nodes'].append({'id': 'x', 'label': 'x', 'parent': 'ghost'}), '父节点 ghost 不存在'),
    (lambda d: d['tree']['nodes'][1].update(lifecycle='hot'), '生命周期'),
    (lambda d: d['tree']['relations'].append({'from': 'logic', 'to': 'memory', 'type': 'similar'}), '关系类型'),
    # 半导体声明子项相加，子项之间却是上下游：不能画成可相加
    (lambda d: d['tree']['relations'].__setitem__(1, {'from': 'logic', 'to': 'memory', 'type': 'upstream_downstream'}), '不能按相加汇总'),
    (lambda d: d['tree']['nodes'][2].update(value=30), '子项合计'),
    (lambda d: d['tree']['relations'].append({'from': 'memory', 'to': 'dram', 'type': 'substitute'}), '同一支上'),
    (lambda d: d['tree']['nodes'][0].update(parent='dram'), '环'),
])
def test_tree_rejects_bad_structure(fixture_root, change, message):
    with pytest.raises(FigureError, match=message):
        render_fixture(fixture_root, [TREE], fixture_with(change))


def test_timeline_orders_events_and_marks_pending(fixture_root):
    tl = figure_html(render_fixture(fixture_root, [TIMELINE]), 'tl')
    assert tl.index('Q3 财报') < tl.index('新产线爬坡') < tl.index('Q4 财报')
    assert 'nf-tl-pend' in tl and 'class="nf-guide"' in tl and 'nf-dot nf-s1' in tl
    assert '查阅日 2026-11-19' in tl and '待兑现' in tl and '已发生' in tl


@pytest.mark.parametrize('change, message', [
    (lambda d: d['events']['items'][0].update(date='2026-13-01'), '日期不合法'),
    (lambda d: d['events']['items'][0].update(date='Nov 17'), '日期不合法'),
    (lambda d: d['events']['items'][1].update(start='2027-07-01'), '区间倒置'),
    (lambda d: d['events']['items'][2].update(status='occurred'), '晚于查阅日'),
    (lambda d: d['events']['items'][2].update(status='maybe'), '状态'),
    (lambda d: d['events']['items'][2].update(id='q3'), '事件 id 重复'),
])
def test_timeline_rejects_bad_dates_and_states(fixture_root, change, message):
    with pytest.raises(FigureError, match=message):
        render_fixture(fixture_root, [TIMELINE], fixture_with(change))


def test_scenario_draws_dashed_ranges_and_reference_line(fixture_root):
    page = render_fixture(fixture_root, [SCENARIO, TORNADO])
    sc = figure_html(page, 'sc')
    assert sc.count('class="nf-guide"') == 3 and 'nf-s1' not in sc  # 情景一律虚线框，不画实心
    assert 'nf-refval' in sc and '现价 152.0' in sc
    tn = figure_html(page, 'tn')
    # 按幅度排序：增速（65）> 折现率（47）> 利润率（21），与声明顺序无关
    assert tn.index('增速 ±3pp') < tn.index('折现率 ∓1pp') < tn.index('利润率 ±2pp')
    assert 'nf-guide2' in tn and 'nf-s1' not in tn


@pytest.mark.parametrize('fig, change, message', [
    (SCENARIO, lambda d: d['valuation'].update(base=[170.0, 130.0, 150.0]), '下限大于上限'),
    (SCENARIO, lambda d: d['valuation'].update(base=[130.0, 170.0, 200.0]), '中点不在区间内'),
    (SCENARIO, lambda d: d['valuation'].update(price=400.0), '超出坐标范围'),
    (TORNADO, lambda d: d['valuation']['sens'].update(fair=90.0), '超出坐标范围'),
])
def test_scenario_rejects_inverted_or_out_of_axis(fixture_root, fig, change, message):
    with pytest.raises(FigureError, match=message):
        render_fixture(fixture_root, [fig], fixture_with(change))


def test_new_types_work_inside_group_panels(fixture_root):
    group = {'id': 'gp', 'type': 'group', 'section': '增长从哪里来', 'title': '两张小图',
             'panels': [{**FUNNEL, 'title': '漏斗'}, {**TIMELINE, 'title': '时间线'}]}
    gp = figure_html(render_fixture(fixture_root, [group]), 'gp')
    assert gp.count('<svg') == 2
