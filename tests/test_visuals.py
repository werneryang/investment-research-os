"""网站图形：通用面板数据、热力图、时间线与「在图中定位」。全部离线，用构造的结果。"""

import json
import re

from investment_os.site.browse import coverage_matrix
from investment_os.site.i18n import use
from investment_os.site.industry import chart as industry_chart, matrix as industry_matrix
from investment_os.site.refining import _investment_chart
from investment_os.site.renderers import ASSETS, ATTRIBUTION
from investment_os.site.study import findings_list
from investment_os.site.visuals import heatmap, nice_ticks, panel, panels, series, timeline, view


def _points(chart, title_part):
    p = next(p for p in chart["panels"] if title_part in p["title"])
    return p, [pt for v in p["views"] for s in v["series"] for pt in s["points"]]


def test_empty_panels_are_dropped_and_ticks_cover_the_data():
    empty = panel("line", "t", {}, {}, [view("", series("s", []))])
    assert empty is None and panels(empty) is None
    ticks = nice_ticks(1926, 2026.8, 6)
    assert ticks[0] <= 1926 and ticks[-1] >= 2026.8


def test_heatmap_leaves_missing_cells_blank_and_marks_refs():
    html = heatmap([("a", "A"), ("b", "B")], [("x", "X")],
                   lambda r, c: (0.5, "results.summary.0") if r == "a" else None, lambda v: f"{v:.1f}")
    assert 'data-ref="results.summary.0"' in html and "75%" in html  # 最大值混入 75%
    assert '<td class="cell empty">—</td>' in html  # 缺失不着色、不补零


def test_asset_chart_presents_results_with_refs_and_keeps_gaps():
    result = {"results": {"assets": ["SP500", "GOLD"], "first_year": 1928, "last_year": 2025,
                          "nominal": {"SP500": {"volatility": 0.19, "geometric": 0.10, "max_drawdown": -0.65},
                                      "GOLD": {"volatility": 0.21, "geometric": 0.05, "max_drawdown": -0.6}},
                          "real": {"SP500": {"first_year": 1948, "last_year": 2025, "volatility": 0.17, "geometric": 0.08}},
                          "rolling": {"window_years": 20}},
              "tables": {"wealth_index": [{"year": 1928, "SP500": 1.4, "GOLD": None}],
                         "rolling": [{"end_year": 1947, "SP500": 0.04}]}}
    chart = ASSETS.chart_data(result)
    assert chart["kind"] == "panels"
    scatter, pts = _points(chart, "波动率")
    assert [v["label"] for v in scatter["views"]] == ["名义 1928–2025", "实际 1948–2025"]
    assert pts[0] == {"x": 19.0, "y": 10.0, "label": "标普 500", "ref": "results.nominal.SP500"}
    wealth, _ = _points(chart, "累计财富")
    gold = next(s for s in wealth["views"][0]["series"] if s["label"] == "黄金")
    assert gold["points"][0]["y"] is None and gold["slot"] == 1  # 缺失不补零；颜色跟随资产
    assert wealth["y"]["log_default"] is True


def test_industry_matrix_and_scatter_cite_summary_rows():
    rows = [{"window": "2001–2025", "sector": "Chips", "status": "ok", "cagr": 0.12, "volatility": 0.3, "max_drawdown": -0.6},
            {"window": "2001–2025", "sector": "Oil", "status": "ok", "cagr": 0.07, "volatility": 0.25, "max_drawdown": -0.5},
            {"window": "2016–2025", "sector": "Chips", "status": "ok", "cagr": 0.30, "volatility": 0.35, "max_drawdown": -0.4},
            {"window": "2016–2025", "sector": "Oil", "status": "incomplete", "cagr": 0.01, "volatility": 0.3, "max_drawdown": -0.7}]
    result = {"results": {"industry_count": 12, "summary": rows,
                          "windows": [["2016–2025", "2016-01", "2025-12"], ["2001–2025", "2001-01", "2025-12"]]},
              "tables": {"wealth": []}}
    html = industry_matrix(result)
    assert html.index(">Chips<") < html.index(">Oil<")  # 按最长窗口排序
    assert 'data-ref="results.summary.2"' in html and "cell empty" in html  # 不完整窗口留空
    chart = industry_chart(result)
    scatter, _ = _points(chart, "波动率")
    assert scatter["views"][0]["label"] == "2016–2025"  # 默认最近窗口
    assert [p["label"] for p in scatter["views"][0]["series"][0]["points"]] == ["Chips"]


def test_attribution_waterfall_ends_in_the_nominal_total():
    leg = lambda v: {"change_bp": v}  # noqa: E731
    result = {"results": {"long_end": {"tenor": "10Y", "nominal": leg(63), "real": leg(50), "breakeven": leg(13), "residual_bp": 0.0},
                          "short_end": {"tenor": "2Y", "nominal": leg(-8), "policy": leg(-100), "spread": leg(92)},
                          "slope": {"label": "10Y − 2Y", "change_bp": 71, "contributions_bp": {"real": 50, "policy": 100, "spread": -92}}},
              "tables": {"path_bp": []}}
    chart = ATTRIBUTION.chart_data(result)
    fall, _ = _points(chart, "贡献")
    ten = fall["views"][0]["series"][0]["points"]
    assert [p["y"] for p in ten] == [50, 13, 63] and ten[-1]["total"] is True  # 取整残差为零时不画
    assert ten[-1]["ref"] == "results.long_end.nominal"


def test_refining_measures_with_different_units_get_separate_panels():
    result = {"results": {"by_year": [{"year": 2016, "complete": True, "mean_crack": 12.5}], "tsr": {"v": {"name": "Valero"}}},
              "tables": {"weekly": [{"week_ending": "2016-01-01", "crack": 10.0, "utilization": 92.5}],
                         "annual_tsr": [{"company": "v", "year": 2016, "tsr": 0.01, "sp500": 0.12, "excess": -0.11}]}}
    chart = _investment_chart(result)
    lines = [p for p in chart["panels"] if p["type"] == "line"]
    assert len(lines) == 2 and {p["y"]["unit"] for p in lines} == {"$/bbl", "%"}  # 不用双纵轴
    _, pts = _points(chart, "超额收益")
    assert pts == [{"x": 12.5, "y": -11.0, "label": "2016"}]


def test_findings_offer_locate_only_for_result_paths():
    html = findings_list([{"text": "t", "evidence": {"results.nominal.SP500.geometric": 0.1, "companies": 15}}])
    refs = json.loads(re.search(r'data-refs="([^"]*)"', html).group(1).replace("&quot;", '"'))
    assert refs == ["results.nominal.SP500.geometric"] and "hidden" in html  # 脚本确认有对应图形后才显示


def test_home_matrix_counts_studies_per_object_and_question():
    tax = {"objects": {"assets": {"name": {"zh": "大类资产", "en": "Asset classes"}},
                       "funds": {"name": {"zh": "基金", "en": "Funds"}}},
           "questions": {"risk": {"name": {"zh": "收益与风险", "en": "Returns and risk"}},
                         "flows": {"name": {"zh": "资金流", "en": "Flows"}}}}
    route = {"object": "assets", "question": "risk", "available": True}
    html = coverage_matrix(tax, [{"routes": [route, route]}, {"routes": [route]}])
    assert 'href="research.html?object=assets&amp;question=risk">2<' in html  # 同一研究的重复入口只算一次
    assert ">资金流<" not in html and "cell empty" in html  # 没有任何研究的问题不占列；没有研究的对象留空


def test_timeline_keeps_short_studies_visible():
    with use("en"):
        html = timeline([("Long", "1926-07", "2025-12", "studies/a/"), ("Short", "2024-01", "2024-12", None)], title="t")
    widths = [float(w) for w in re.findall(r'<rect [^>]*width="([\d.]+)"', html)]
    assert min(widths) >= 6 and ">2024<" in html and 'href="studies/a/"' in html
