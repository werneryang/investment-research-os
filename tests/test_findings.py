"""规则化关键发现、发现变化记录、覆盖条与能力地图状态。"""

from investment_os.registry import Registry
from investment_os.research.findings import FLAT_BP, changes, findings, state
from investment_os.site.capability import direction_status, framework, summary
from investment_os.site.coverage import coverage_strip

from .conftest import PROJECT_ROOT


def _level(start, end, change):
    return {"observations": 250, "start": start, "end": end, "change_bp": change,
            "start_date": "2024-01-02", "end_date": "2024-12-31"}


def _result(**over):
    base = {
        "branch": "rates_curve", "run_id": "r1", "data_cutoff": "2024-12-31",
        "results": {
            "levels": {"3M": _level(5.46, 4.37, -109.0), "2Y": _level(4.33, 4.25, -8.0),
                       "10Y": _level(3.95, 4.58, 63.0)},
            "spreads": {"2Y-10Y": {"observations": 250, "start": -38.0, "end": 33.0, "change_bp": 71.0,
                                   "inversion": {"observations": 250, "inverted_days": 166, "zero_days": 3,
                                                 "inverted_share": 0.664}}},
            "curvature": {},
        },
        "coverage": {"period_complete": True},
    }
    base.update(over)
    return base


def test_findings_are_rule_based_and_cite_metrics():
    fs = findings(_result())
    texts = [f["text"] for f in fs]
    assert texts[0] == "10 年期收益率由 3.95% 升至 4.58%（+63 bp，2024-01-02 至 2024-12-31）。"
    assert "关键期限涨跌不一：1 个上升、2 个下降" in texts[1]
    spread = next(t for t in texts if t.startswith("10Y − 2Y"))
    assert "由 −38 bp 变为 33 bp（+71 bp，该段曲线变陡，由倒挂转为正斜率）" in spread
    assert "期间倒挂 166 天，占有效观测 66%，另有 3 天恰为 0（不计入倒挂）" in spread
    assert fs[0]["evidence"]["results.levels.10Y.change_bp"] == 63.0
    # 只描述，不作判断
    assert not any(w in "".join(texts) for w in ("预示", "看涨", "看跌", "建议"))


def test_small_changes_are_flat_and_incomplete_periods_withhold_counts():
    r = _result(coverage={"period_complete": False, "incomplete_reason": "预期 250 个观测日，实际 2 个"})
    r["results"]["levels"]["10Y"]["change_bp"] = FLAT_BP - 1
    texts = [f["text"] for f in findings(r)]
    assert texts[0].startswith("10 年期收益率基本持平")
    assert not any("倒挂 166 天" in t for t in texts)  # 期间不完整时不输出倒挂天数
    assert texts[-1].startswith("研究期间覆盖不足（预期 250 个观测日，实际 2 个）")


def test_unknown_branch_has_no_findings():
    assert findings({"branch": "other"}) == []


def test_changes_record_state_transitions():
    a = _result()
    b = _result(run_id="r2", data_cutoff="2025-06-30")
    b["results"] = {**b["results"], "spreads": {"2Y-10Y": {**a["results"]["spreads"]["2Y-10Y"],
                                                            "end": -5.0, "change_bp": -38.0}}}
    assert state(a)["10Y − 2Y 期末"] == "正斜率"
    log = changes([a, b])
    assert {"run_id": "r2", "data_cutoff": "2025-06-30", "item": "10Y − 2Y 期末",
            "from": "正斜率", "to": "倒挂"} in log
    assert changes([a, a]) == []


def test_coverage_strip_marks_missing_and_tenor_gaps():
    r = {"coverage": {"tenors": {"10Y": {}}, "missing_dates": ["2024-01-03"], "missing_days": 1},
         "tables": {"daily": [{"date": "2024-01-02", "10Y": 3.95}, {"date": "2024-01-04", "10Y": None}]}}
    svg = coverage_strip(r)
    assert svg.count('<rect class="cov-miss"') == 2  # 观测日行与 10Y 行各一格
    assert svg.count('<rect class="cov-gap"') == 1  # 1 月 4 日有曲线但 10Y 缺失
    assert "2024-01-03" in svg


def test_coverage_strip_monthly_summary_and_exception_list():
    r = {"coverage": {"tenors": {"10Y": {}}, "missing_dates": ["2024-01-03"], "missing_days": 1,
                      "pending_dates": ["2024-02-01"]},
         "tables": {"daily": [{"date": "2024-01-02", "10Y": 3.95}, {"date": "2024-01-04", "10Y": None}]}}
    html = coverage_strip(r)
    monthly = html[html.index('class="cov-monthly"'):html.index("</svg>", html.index('class="cov-monthly"'))]
    assert monthly.count('<rect class="m cov-miss"') == 2  # 1 月最差状态为缺失（观测日行与 10Y 行）
    assert monthly.count('<rect class="m cov-pending"') == 2  # 2 月只有未取得日
    r["coverage"]["pending_dates"].append("2024-01-05")
    r["coverage"]["missing_dates"] = []
    r["tables"]["daily"][1]["10Y"] = 4.0
    html2 = coverage_strip(r)
    monthly2 = html2[html2.index('class="cov-monthly"'):]
    assert monthly2.count('<rect class="m cov-ok"') == 2  # 1 月有合格日，单个未取得日不把整月画成未取得
    assert "观测日：2/3 天合格" in monthly and "10Y：1/3 天合格" in monthly  # 1 月 4 日有曲线但 10Y 缺失
    exceptions = html[html.index('class="cov-exceptions"'):]
    assert "非合格日期（3 条）" in exceptions
    assert "2024-01-03 · 整日" in exceptions and "2024-01-04 · 10Y" in exceptions
    assert "2024-02-01 · 整日：未取得" in exceptions


def test_coverage_strip_states_when_all_observations_qualify():
    r = {"coverage": {"tenors": {"10Y": {}}},
         "tables": {"daily": [{"date": "2024-01-02", "10Y": 3.95}]}}
    html = coverage_strip(r)
    assert "cov-exceptions" not in html and "均有合格观测" in html


def test_coverage_strip_discloses_partial_missing_list():
    r = {"coverage": {"tenors": {}, "missing_examples": ["2024-01-03"], "missing_days": 5},
         "tables": {"daily": [{"date": "2024-01-02"}]}}
    assert "只记录了部分缺失日期" in coverage_strip(r)


def _latest(status="success", start="2024-01-01", end="2024-12-31"):
    return {"s1": {"manifest": {"status": status},
                   "result": {"branch": "rates_curve", "scope": {"start": start, "end": end}}}}


def test_capability_categories_come_from_registry_and_runs():
    reg = Registry.load(PROJECT_ROOT)
    ds = {"ust_par_yield_curve": {"status": "access_verified", "version_id": "v1", "verified_uses": []},
          "fred_sofr": {"status": "access_verified", "version_id": "v2", "verified_uses": []}}
    active = direction_status({"datasets": ["ust_par_yield_curve"], "studies": ["s1"]}, reg, ds, _latest())
    # 真实登记中已有 ust_par_yield_curve 的描述性用途核验；只对该用途计入
    assert [(d, u.value) for d, u, _, _ in active["validated"]] == [("ust_par_yield_curve", "descriptive")]
    assert "2024-01-01 至 2026-10-22" in active["validated"][0][2].scope
    as_of = {"s1": {"manifest": {"status": "success"},
                    "result": {"branch": "rates_curve",
                               "scope": {"vintage_policy": "as_of", "start": "2024-01-01", "end": "2024-12-31"}}}}
    assert direction_status({"datasets": ["ust_par_yield_curve"], "studies": ["s1"]}, reg, ds, as_of)["validated"] == []
    two = direction_status({"datasets": ["ust_par_yield_curve", "fred_sofr"], "studies": ["s1"]}, reg, ds, _latest())
    assert two["unvalidated"] == ["fred_sofr"]
    assert direction_status({"datasets": ["fred_sofr"], "studies": []}, reg, ds, {})["category"] == "data_only"
    assert direction_status({"planned": True}, reg, ds, {})["category"] == "planned"
    # 已登记但本次未取得的数据集不是「规划」
    assert direction_status({"datasets": ["alfred_sofr"], "studies": []}, reg,
                         {"alfred_sofr": {"status": "docs_verified", "version_id": None,
                                              "verified_uses": []}}, {})["category"] == "registered"
    content = {"data_groups": [
        {"id": "a", "directions": [{"datasets": ["ust_par_yield_curve"], "studies": ["s1"]}, {"planned": True}]},
        {"id": "b", "directions": [{"datasets": ["fred_sofr"], "studies": []}]},
        {"id": "c", "directions": [{"planned": True}]}]}
    assert summary(content, reg, ds, _latest()) == {"active": 1, "data_only": 1, "registered": 0, "planned": 2}
    # 分支状态取其方向中最好的一项
    assert [b["category"] for b in framework(content, reg, ds, _latest())] == ["active", "data_only", "planned"]


def test_capability_map_shows_partial_scope():
    from investment_os.site.capability import _validated_entry
    reg = Registry.load(PROJECT_ROOT)
    ds = {"ust_par_yield_curve": {"status": "access_verified", "version_id": "v1", "verified_uses": []}}
    inside = direction_status({"datasets": ["ust_par_yield_curve"], "studies": ["s1"]}, reg, ds, _latest())
    assert inside["validated"][0][3][0][1]["status"] == "in_scope"
    assert "部分在范围内" not in _validated_entry(*inside["validated"][0])

    past = direction_status({"datasets": ["ust_par_yield_curve"], "studies": ["s1"]}, reg, ds,
                         _latest(start="2025-10-23", end="2026-10-25"))
    cov = past["validated"][0][3][0][1]
    assert cov["status"] == "partial" and cov["uncovered"] == [["2026-10-23", "2026-10-25"]]
    html = _validated_entry(*past["validated"][0])
    assert "用途已验证 · 部分在范围内" in html and "2026-10-23 至 2026-10-25" in html
