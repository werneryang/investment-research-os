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
