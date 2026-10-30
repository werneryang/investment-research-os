"""产业链研究 §5.4：10-K 业绩图接入器，以及利用率、裂解价差与炼油公司总收益的描述性对照。

价格、利用率与总收益都是虚构值；只检验接入器与研究分支自己的逻辑（定位、换算、核对与定级）。
"""

import json

import pandas as pd
import pytest

from investment_os.connectors.base import FetchError
from investment_os.connectors.sec import SecClient
from investment_os.connectors.sec_graph import SecPerformanceGraphConnector, extract, text_of
from investment_os.contracts import SERIES_COLUMNS, DatasetVersion
from investment_os.data import ingest
from investment_os.registry import parse_study
from investment_os.reporting.report import _sections, write_report
from investment_os.research.base import StudyInput
from investment_os.research.refining_investment import run

# ---- 接入器 ---------------------------------------------------------------------

def graph_html(header, rows, extra=""):
    """业绩图数值表的最小 HTML：表头一行，每行标签后接数值单元格（带美元符号的单元格单独成格）。"""
    cells = "".join(f"<td>{h}</td>" for h in header.split(" "))
    body = "".join(f"<tr><td>{label}</td>" + "".join(f"<td>$</td><td>{v}</td>" for v in values) + "</tr>"
                   for label, values in rows)
    return (f"<html><body><p>Performance graph {extra}</p><table><tr>{cells}</tr>{body}</table>"
            "<p>ITEM 6.</p></body></html>").encode()


def _filings(project):
    import yaml
    doc = yaml.safe_load((project / "config" / "datasets.yaml").read_text(encoding="utf-8"))
    return doc["datasets"]["sec_tsr_valero"]["params"]["filings"]


def _pages(filings, override=None):
    pages = {}
    for i, f in enumerate(filings):
        company = ["100.00", *(f"{100 + 10 * (k + 1) + i:.2f}" for k in range(5))]
        sp500 = ["100.00", *(f"{100 + 5 * (k + 1):.2f}" for k in range(5))]
        pages[f["url"]] = graph_html(f["header"], [(f["rows"]["company"], company), (f["rows"]["sp500"], sp500)])
    pages.update(override or {})
    return pages


def sec_connector(pages):
    return SecPerformanceGraphConnector(SecClient(user_agent="test test@example.com",
                                                  get=lambda url, headers, timeout: pages[url],
                                                  sleep=lambda s: None, attempts=1))


def test_graph_rows_are_located_by_declared_header_and_label(project, registry, store):
    filings = _filings(project)
    r = ingest(registry, store, "sec_tsr_valero", {}, sec_connector(_pages(filings)))
    assert r.status == "created"
    df, v = store.load("sec_tsr_valero")
    first = filings[0]["accession"]
    s = df[df["series_id"] == f"company|{first}"].sort_values("observation_at")
    assert s["value"].tolist() == [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    assert str(s["observation_at"].iloc[0].date()) == "2015-12-31"
    assert len(df) == 36 and set(df["unit"]) == {"index_base_100"}
    assert v.series[f"sp500|{first}"]["label"] == "S&P 500"
    # 发布时间是 EDGAR 接受日期，可用时间为次日
    assert str(s["published_at"].iloc[0].tz_convert("America/New_York").date()) == filings[0]["accepted_at"]


@pytest.mark.parametrize("change, message", [
    (lambda f: graph_html(f["header"].replace("2015", "2014"), []), "找不到表头"),
    # 「S&P 500」不能匹配「S&P 500 Index」：行标签逐字核对
    (lambda f: graph_html(f["header"], [(f["rows"]["company"], ["100.00"] * 6),
                                        ("S&P 500 Index", ["100.00"] * 6)]), "找不到行「S&P 500」"),
    (lambda f: graph_html(f["header"], [(f["rows"]["company"], ["99.00"] + ["100.00"] * 5),
                                        (f["rows"]["sp500"], ["100.00"] * 6)]), "不是基期 100"),
    (lambda f: graph_html(f["header"], [(f["rows"]["company"], ["100.00"] * 5),
                                        (f["rows"]["sp500"], ["100.00"] * 5)]), "6 个数值"),
    (lambda f: graph_html(f["header"], [(f["rows"]["company"], ["100.00"] * 6),
                                        (f["rows"]["sp500"], ["100.00"] * 6)], extra=f["header"]), "不止一次"),
])
def test_graph_changes_fail_instead_of_guessing(project, registry, store, change, message):
    filings = _filings(project)
    r = ingest(registry, store, "sec_tsr_valero", {},
               sec_connector(_pages(filings, {filings[0]["url"]: change(filings[0])})))
    assert r.status == "failed" and message in r.message and store.latest("sec_tsr_valero") is None


def test_text_extraction_strips_tags_and_entities():
    f = {"accession": "x", "header": "As of December 31, 2015 2016",
         "dates": ["2015-12-31", "2016-12-31"], "rows": {"sp500": "S&P 500"}}
    page = b"<p>As of December&#160;31,  2015 <b>2016</b></p><p>S&amp;P 500 $ 100.00 $ 1,111.96</p>"
    assert extract(text_of(page), f) == {"sp500": ["100.00", "1111.96"]}
    with pytest.raises(FetchError):
        extract(text_of(b"<p>As of December 31, 2015 2016</p>" + b"x" * 3000 + b"<p>S&amp;P 500 100.00 1.00</p>"), f)


# ---- 研究分支 ---------------------------------------------------------------------

STUDY = {
    "study_id": "refining_investment_test", "title": "t", "question": "q", "result_type": "descriptive",
    "branch": "refining_investment",
    "scope": {"market": "US", "activity": "petroleum_refining", "start": "2020-01-01", "end": "2021-12-31",
              "frequency": "weekly"},
    "data": {},
    "method": {"crack_spread": {"crude": 3, "gasoline": 2, "distillate": 1, "gallons_per_barrel": 42},
               "companies": [{"id": "a", "name": "Alpha", "role": "tsr_a", "primary": ["A-20", "A-21"]},
                             {"id": "b", "name": "Beta", "role": "tsr_b", "primary": ["B-21"]}],
               "not_covered": [{"name": "Gamma", "reason": "只有图片"}]},
    "limitations": ["测试"],
}
WEEKS = pd.date_range("2020-01-01", "2021-12-31", freq="W-FRI")
WEALTH = {"a": {2017: 1.0, 2018: 1.2, 2019: 0.9, 2020: 0.6, 2021: 1.1},
          "b": {2017: 1.0, 2018: 0.8, 2019: 1.0, 2020: 0.3, 2021: 0.9},
          "sp500": {2017: 1.0, 2018: 0.95, 2019: 1.25, 2020: 1.48, 2021: 1.9}}


def _frame(rows, unit, source="eia"):
    df = pd.DataFrame({c: None for c in SERIES_COLUMNS}, index=range(len(rows)))
    df["series_id"] = [s for s, _, _ in rows]
    df["observation_at"] = pd.to_datetime([d for _, d, _ in rows])
    df["value"] = [v for _, _, v in rows]
    df["unit"], df["source_id"], df["quality_status"], df["reason"] = unit, source, "ok", ""
    return df


def _filing(company, accession, years, bump=0.0):
    """一份申报：以首年年末为 100，按虚构财富路径换算并保留两位小数。"""
    rows = []
    for key in (company, "sp500"):
        w = WEALTH[key]
        for y in years:
            value = 100.0 if y == years[0] else round(100 * w[y] / w[years[0]], 2) + (bump if y == years[-1] else 0)
            rows.append((f"{'company' if key != 'sp500' else 'sp500'}|{accession}", f"{y}-12-31", value))
    return rows


def _version(ds):
    return DatasetVersion(dataset_id=ds, version_id=f"v-{ds}", schema_version="series.v1", content_hash="h",
                          created_at="", rows=0, path="", raw_snapshots=[], transform="", quality={})


def _inputs(status="access_verified", drop_week=None, tsr_a=None, tsr_b=None, tsr_unit="index_base_100"):
    weeks = [d for d in WEEKS if d != drop_week]
    frames = {
        "utilization": _frame([("WPULEUS3", d, 80.0 + (i % 15)) for i, d in enumerate(WEEKS)], "percent"),
        "crude": _frame([("RWTC", d, 50.0 + 0.1 * i) for i, d in enumerate(WEEKS)], "usd_per_barrel"),
        "gasoline": _frame([("EER_EPMRU_PF4_RGC_DPG", d, 1.5) for d in weeks], "usd_per_gallon"),
        "distillate": _frame([("EER_EPD2DXL0_PF4_RGC_DPG", d, 1.8) for d in WEEKS], "usd_per_gallon"),
        "tsr_a": _frame(tsr_a if tsr_a is not None else
                        _filing("a", "A-20", [2017, 2018, 2019, 2020]) + _filing("a", "A-21", [2019, 2020, 2021])
                        + _filing("a", "A-check", [2018, 2019, 2020, 2021]), tsr_unit, "sec_edgar"),
        "tsr_b": _frame(tsr_b if tsr_b is not None else _filing("b", "B-21", [2017, 2018, 2019, 2020, 2021]),
                        tsr_unit, "sec_edgar"),
    }
    return {r: StudyInput(role=r, dataset_id=f"ds_{r}", frame=f, version=_version(f"ds_{r}"), source_status=status)
            for r, f in frames.items()}


def _run(inputs=None, **study):
    return run(parse_study({**STUDY, **study}), inputs or _inputs(), None)


def test_crack_spread_annual_returns_and_comparison_are_grade_a():
    r = _run()
    grades = {k: v["grade"] for k, v in r.results["feasibility"].items()}
    assert set(grades.values()) == {"A"} and set(grades) == {"crack_spread", "utilization_crack", "tsr:a", "comparison:a",
                                                             "tsr:b", "comparison:b"}
    # (2 × 42 × 1.5 + 1 × 42 × 1.8 − 3 × 50) ÷ 3 = 17.2 美元/桶
    assert r.tables["weekly"][0]["crack"] == pytest.approx(17.2)
    assert r.results["crack_spread"]["weeks"] == len(WEEKS)
    annual = {(a["company"], a["year"]): a for a in r.tables["annual_tsr"]}
    # 2020 取第一份同时含 2019、2020 年末的主申报 A-20；2021 只有 A-21 覆盖
    assert annual[("a", 2020)]["accession"] == "A-20" and annual[("a", 2021)]["accession"] == "A-21"
    assert annual[("a", 2020)]["tsr"] == pytest.approx(0.6 / 0.9 - 1, abs=1e-3)
    assert annual[("a", 2021)]["excess"] == pytest.approx((1.1 / 0.6 - 1) - (1.9 / 1.48 - 1), abs=1e-3)
    tsr = r.results["tsr"]["a"]
    assert tsr["cumulative"]["company"] == pytest.approx(1.1 / 0.9 - 1, abs=1e-3)
    assert isinstance(tsr["years_beating_sp500"], int)
    # A-check 与主申报在 2019–2021 重叠：公司与标普 500 各 3 年
    assert r.validation["overlap_check:a"] == {**r.validation["overlap_check:a"], "status": "pass", "checked": 6}
    assert r.validation["sp500_cross_issuer"]["status"] == "pass" and r.validation["sp500_cross_issuer"]["checked"] == 2
    assert r.results["comparison"]["a"]["excess_vs_crack_change"]["n"] == 1
    assert r.results["comparison"]["a"]["excess_vs_mean_crack"]["spearman"] is None  # 少于 3 年不给相关
    # 研究问题之外的公司写入限制，不算受限结论
    assert not r.unsupported and r.coverage["completeness"] == "complete"
    assert "未纳入 Gamma：只有图片" in r.limitations
    json.dumps(r.to_dict())  # 结果可序列化，数值不带 numpy 类型


def test_missing_week_is_not_interpolated_and_drops_that_year():
    gap = pd.Timestamp("2021-03-05")
    r = _run(_inputs(drop_week=gap))
    assert r.coverage["missing_weeks"] == ["2021-03-05"] and r.coverage["incomplete_years"] == ["2021"]
    week = next(w for w in r.tables["weekly"] if w["week_ending"] == "2021-03-05")
    assert week["crack"] is None
    y2021 = next(b for b in r.results["by_year"] if b["year"] == 2021)
    assert not y2021["complete"] and "mean_crack" not in y2021
    assert r.results["comparison"]["a"]["excess_vs_crack_change"]["n"] == 0
    assert any("缺周年份" in u["item"] for u in r.unsupported) and r.coverage["completeness"] == "partial"


def test_inconsistent_overlap_blocks_that_company_only():
    tsr_a = (_filing("a", "A-20", [2017, 2018, 2019, 2020]) + _filing("a", "A-21", [2019, 2020, 2021])
             + _filing("a", "A-check", [2018, 2019, 2020, 2021], bump=5.0))
    r = _run(_inputs(tsr_a=tsr_a))
    grades = {k: v["grade"] for k, v in r.results["feasibility"].items()}
    assert grades["tsr:a"] == "C" and "comparison:a" not in grades  # 总收益不可计算时不做对照
    assert r.validation["overlap_check:a"]["status"] == "fail"
    assert {f["year"] for f in r.validation["overlap_check:a"]["failures"]} == {2021}
    assert not [a for a in r.tables["annual_tsr"] if a["company"] == "a"] and "a" not in r.results["tsr"]
    assert grades["tsr:b"] == "A" and "b" in r.results["comparison"]
    assert any(u["item"] == "Alpha 年度总收益" for u in r.unsupported)


def test_sp500_disagreement_between_companies_blocks_both():
    tsr_b = [(s, d, v + (3.0 if s.startswith("sp500") and d == "2020-12-31" else 0))
             for s, d, v in _filing("b", "B-21", [2017, 2018, 2019, 2020, 2021])]
    r = _run(_inputs(tsr_b=tsr_b))
    assert r.validation["sp500_cross_issuer"]["status"] == "fail"
    assert {r.results["feasibility"][f"tsr:{c}"]["grade"] for c in "ab"} == {"C"}
    assert not r.tables["annual_tsr"] and not r.results["comparison"]


def test_missing_primary_year_and_wrong_units_are_c():
    r = _run(_inputs(tsr_a=_filing("a", "A-20", [2017, 2018, 2019, 2020])))
    a = r.results["feasibility"]["tsr:a"]
    assert a["grade"] == "C" and any("2021" in x for x in a["reasons"])
    r = _run(_inputs(tsr_unit="USD"))
    assert r.results["feasibility"]["tsr:a"]["grade"] == "C" and "单位" in r.results["feasibility"]["tsr:a"]["reasons"][0]
    r = _run(_inputs(status="candidate"))
    assert {v["grade"] for v in r.results["feasibility"].values()} == {"unassessed"}
    assert r.results["crack_spread"] is None and not r.tables["weekly"]


@pytest.mark.parametrize("change, message", [
    ({"scope": {**STUDY["scope"], "end": "2021-06-30"}}, "完整日历年"),
    ({"scope": {**STUDY["scope"], "frequency": "monthly"}}, "适用范围"),
    ({"method": {**STUDY["method"], "crack_spread": {"crude": 3, "gasoline": 2, "distillate": 2,
                                                     "gallons_per_barrel": 42}}}, "产品桶数之和"),
    ({"method": {**STUDY["method"], "crack_spread": {"crude": 3, "gasoline": 2, "distillate": 1}}}, "42"),
    ({"result_type": "simulation"}, "只产出描述统计"),
])
def test_study_definition_errors_are_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        _run(**change)


def test_report_sections_and_figures(project):
    result = {**_run().to_dict(), "run_id": "test-run", "generated_at": "2026-10-30T00:00:00+00:00", "result_hash": "h"}
    text = json.dumps(_sections(result), ensure_ascii=False)
    for needle in ("3-2-1 裂解价差", "Alpha 2 年累计总收益", "重叠申报收益核对（a）", "标普 500 跨公司核对", "与价差变化"):
        assert needle in text
    paths = write_report(project, result)
    assert any(p.suffix == ".md" for p in paths)


def test_weekly_columns_limit_the_published_table():
    r = _run(method={**STUDY["method"], "weekly_columns": ["utilization", "crack"]})
    assert set(r.tables["weekly"][0]) == {"week_ending", "utilization", "crack"}
    assert r.results["crack_spread"] == _run().results["crack_spread"]  # 只影响表格，不影响计算
    assert {"crude", "gasoline", "distillate"} <= set(_run().tables["weekly"][0])  # 未声明时保留全部列
    with pytest.raises(ValueError, match="不存在"):
        _run(method={**STUDY["method"], "weekly_columns": ["price"]})


def test_site_renderers_are_registered_for_both_refining_branches():
    from investment_os.site.i18n import use
    from investment_os.site.renderers import get_renderer

    assert get_renderer("refining_throughput").supported and get_renderer("refining_investment").supported
    result = _run().to_dict()
    r = get_renderer("refining_investment")
    for language in ("zh", "en"):
        with use(language, {"phrases": {}, "patterns": []}):
            html = r.key_stats(result) + r.coverage_section(result)
            rows = r.evidence_rows(result)
    assert "Alpha" in html and "S&P 500" in html
    assert any("S&P 500 cross-issuer check" in label for label, _ in rows)
    assert [f for f, _ in r.figures] == ["refining_crack_utilization.png", "refining_excess_vs_crack.png"]
