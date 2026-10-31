"""Two-level browsing reads the registered routes: one primary shelf per study, other routes only as see-also links."""
import pytest
import yaml

from investment_os.site.browse import home_page, object_page
from investment_os.site.discovery import catalog
from .conftest import PROJECT_ROOT

BUILD = {'built_at': '2026-10-31T00:00:00+00:00'}


def _item(title, cutoff='2026-10-30'):
    return {'result': {'branch': 'unknown', 'title': title, 'question': 'Q', 'result_type': 'descriptive', 'scope': {},
                       'data_cutoff': cutoff, 'limitations': [], 'validation': {}, 'unsupported': []},
            'manifest': {'run_id': 'r', 'status': 'success', 'inputs': []}, 'verification': None, 'findings': []}


@pytest.fixture
def site():
    content = yaml.safe_load((PROJECT_ROOT / 'site/content.yaml').read_text())
    latest = {'ust_curve_2024': _item('2024 curve'), 'us_asset_history': _item('Asset history', '2025-12-31'),
              'company_apple': _item('Apple：年度财报研究'), 'company_sample': _item('15 家公司')}
    ds = {d: {} for r in content['classification']['capabilities'] for d in r.get('datasets', [])}
    model = catalog(content, latest, {}, ds)
    for rec in model['studies']:  # stub results carry no sections; mark every route of a published study available
        for r in rec['routes']:
            if rec['published']:
                r['available'], r['href'] = True, f"studies/{rec['id']}/#{r['target']}"
    return content, model, latest


def test_home_lists_objects_with_subtypes_and_defers_filters(site):
    content, model, latest = site
    html = home_page(content, model, latest, BUILD)
    assert 'action="research.html"' in html and 'href="research.html">高级筛选' in html
    assert 'href="browse/assets/">大类资产 ›' in html and 'href="browse/company/">公司 ›' in html
    # The rates curve is the only primary study under rates; equities appear only through the multi-asset study.
    assert 'href="browse/assets/#rates">国债与利率</a><span class="muted">1<' in html
    assert 'href="browse/assets/#equity">股票市场整体</a><span class="muted">另见 1<' in html
    # A collection counts its companies, not its lead study.
    assert '1 家公司' in html and 'href="studies/company_apple/">Apple</a>' in html
    assert '尚无研究：' in html and 'href="browse/industry/"' in html  # no published industry study
    assert 'research.html?question=prices' in html and 'research.html?question=valuation' not in html
    assert '最新数据截至 2026-10-30' in html


def test_object_page_shelves_primary_studies_and_links_secondary_routes(site):
    content, model, latest = site
    html = object_page(content, model, latest, BUILD, 'assets')
    rates = html[html.index('id="rates"'):html.index('</section>', html.index('id="rates"'))]
    assert 'href="../../studies/ust_curve_2024/">2024 curve</a>' in rates and '截至 2026-10-30' in rates
    assert '尚未发布' in rates  # registered primary studies without a run stay visible but unlinked
    equity = html[html.index('id="equity"'):html.index('</section>', html.index('id="equity"'))]
    assert '暂无专门研究' in equity and '另见' in equity and 'href="../../studies/us_asset_history/#' in equity
    assert 'href="../../research.html?object=assets"' in html and 'href="../industry/">行业与产业链' in html


def test_company_page_counts_companies_and_lists_members(site):
    content, model, latest = site
    html = object_page(content, model, latest, BUILD, 'company')
    assert '<p class="tagline">1 家公司，按子类与研究问题列出。' in html
    assert 'href="../../studies/company_apple/">Apple</a>' in html and '<table>' in html
