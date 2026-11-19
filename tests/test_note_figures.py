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
LAYOUT = 'methodology/records/sec-aapl-value-chain-layout-20261119.yaml'


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
