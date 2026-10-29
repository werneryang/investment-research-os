"""产业链研究 P2/P3a：约束引擎的虚构算例、舍入区间、输入能力等级，以及 EIA 炼油统计与情景的端到端运行。

xlrd 只能读取 .xls，接入器测试用假的工作簿对象代替文件格式，只检验接入器自己的逻辑。
"""

import json

import pandas as pd
import pytest
import xlrd
import yaml

from investment_os.analytics.constraints import Capacity, ConstraintError, Requirement, max_output
from investment_os.analytics.rounding import compatible, decimals_ok, ratio_interval
from investment_os.connectors import eia
from investment_os.connectors.eia import BASE_URL, EiaPetXlsConnector
from investment_os.contracts import SERIES_COLUMNS, DatasetVersion
from investment_os.data import ingest
from investment_os.registry import parse_study
from investment_os.research.base import StudyInput
from investment_os.research.feasibility import assess, check_assumption
from investment_os.research.refining import run as refining_run
from investment_os.runs import run_study, verify_run

from .conftest import NO_RETRY, FakeHttp

FILE = "PET_PNP_WIUP_DCU_NUS_W.xls"
XLS_MAGIC = b"\xd0\xcf\x11\xe0" + b"\0" * 60
TITLES = {
    "WGIRIUS2": "Weekly U.S. Gross Inputs into Refineries  (Thousand Barrels per Day)",
    "WOCLEUS2": "Weekly U. S. Operable Crude Oil Distillation Capacity   (Thousand Barrels per Calendar Day)",
    "WPULEUS3": "Weekly U.S. Percent Utilization of Refinery Operable Capacity (Percent)",
}
DATASETS = {"inputs": "eia_refinery_gross_inputs", "capacity": "eia_refinery_operable_capacity",
            "utilization": "eia_refinery_utilization"}
WEEKS = pd.date_range("2025-01-01", "2025-12-31", freq="W-FRI")  # 52 个周五


def weekly_values(weeks=WEEKS):
    """虚构但口径一致的周度值：G、K 为整数，U 为按 EIA 方式由未舍入值算出再保留一位小数。"""
    rows = []
    for i, day in enumerate(weeks):
        k = 18000.0 + 100 * (i // 13)  # 每季度更新一次产能
        g = float(15500 + (i * 37) % 2000)
        rows.append((day, g, k, round(100 * g / k, 1)))
    return rows


# ---- P2：约束引擎（纯虚构算例，不代表真实产业数据） ----------------------------------

GPU = [Requirement("server", "gpu", 4, "gpu"), Requirement("gpu", "packaging", 1, "gpu_package")]


def test_fictional_gpu_example_matches_design_document():
    """设计文档 §9 的算例：需求 700 台增加 20% → 840 台、3,360 颗 GPU；封装最多支持 750 台，缺口 90 台。"""
    out = max_output("server", 700 * 1.2, GPU,
                     [Capacity("gpu", 3600, "gpu"), Capacity("packaging", 3000, "gpu_package")])
    assert out["demand"] == pytest.approx(840)
    assert out["requirements"]["gpu"]["required"] == pytest.approx(3360)
    assert out["output"] == pytest.approx(750) and out["shortfall"] == pytest.approx(90)
    assert out["binding"] == ["packaging"]
    assert out["supported_by_resource"] == {"gpu": 900, "packaging": 750}


def test_no_binding_constraint_when_demand_fits():
    out = max_output("server", 700, GPU, [Capacity("gpu", 3600, "gpu"), Capacity("packaging", 3000, "gpu_package")])
    assert out["output"] == 700 and out["shortfall"] == 0 and out["binding"] == []


def test_requirements_add_up_over_multiple_paths():
    reqs = [Requirement("box", "a", 2, "u"), Requirement("box", "b", 1, "v"), Requirement("b", "a", 3, "u")]
    out = max_output("box", 10, reqs, [Capacity("a", 100, "u"), Capacity("b", 100, "v")])
    assert out["requirements"]["a"]["coefficient"] == 5  # 2 直接 + 1 × 3 间接
    assert out["output"] == 10


@pytest.mark.parametrize("reqs, caps, message", [
    (GPU, [Capacity("gpu", 3600, "gpu")], "缺少能力"),
    (GPU, [Capacity("gpu", None, "gpu"), Capacity("packaging", 3000, "gpu_package")], "缺失"),
    (GPU, [Capacity("gpu", float("nan"), "gpu"), Capacity("packaging", 3000, "gpu_package")], "缺失"),
    (GPU, [Capacity("gpu", 3600, "kb/d"), Capacity("packaging", 3000, "gpu_package")], "单位"),
    (GPU, [Capacity("gpu", 3600, "gpu"), Capacity("packaging", 3000, "gpu_package"), Capacity("hbm", 1, "x")],
     "未使用"),
    ([Requirement("a", "b", 1, "u"), Requirement("b", "c", 1, "u"), Requirement("c", "b", 1, "u")],
     [Capacity("b", 1, "u"), Capacity("c", 1, "u")], "回路"),
    ([Requirement("a", "b", 0, "u")], [Capacity("b", 1, "u")], "必须为正"),
    ([Requirement("a", "b", 1, "u"), Requirement("c", "b", 1, "v")], [Capacity("b", 1, "u")], "单位不一致"),
])
def test_engine_rejects_missing_wrong_units_and_cycles(reqs, caps, message):
    with pytest.raises(ConstraintError, match=message):
        max_output("server" if reqs is GPU else "a", 10, reqs, caps)


def test_rounding_intervals_replace_empirical_tolerance():
    assert decimals_ok(93.4, 1) and decimals_ok(16860.0, 0) and not decimals_ok(93.45, 1)
    lo, hi = ratio_interval(16860, 0, 18044, 0, scale=100)
    assert lo < 100 * 16860 / 18044 < hi
    assert compatible((lo, hi), 93.4, 1) and not compatible((lo, hi), 93.6, 1)
    # 复算差超过 0.05 仍可能相容：G、K 的舍入也会传到比值上
    assert compatible((93.30, 93.36), 93.4, 1)


# ---- P1：输入能力等级 ------------------------------------------------------------

def _inputs(status="access_verified"):
    return [StudyInput(role=r, dataset_id=d, frame=pd.DataFrame(), version=None, source_status=status)
            for r, d in DATASETS.items()]


ALLOWED = {"kappa": {"range": [0.9, 1.0], "unit": "比例", "rationale": "测试"}}


def test_feasibility_has_four_paths_and_propagates():
    a = assess("stats", inputs=_inputs())
    assert a.grade == "A"
    rec, err = check_assumption("kappa", 0.95, ALLOWED)
    b = assess("scen", inputs=_inputs(), assumptions=[rec], depends_on=[a])
    assert err is None and b.grade == "B"
    assert assess("child", inputs=_inputs(), depends_on=[b]).grade == "B"  # 依赖 B 的单元至少为 B
    _, err = check_assumption("kappa", 1.05, ALLOWED)
    c = assess("scen", inputs=_inputs(), assumption_errors=[err], depends_on=[a])
    assert c.grade == "C" and "超出允许范围" in c.reasons[0]
    assert assess("child", inputs=_inputs(), depends_on=[c]).grade == "C"
    u = assess("stats", inputs=_inputs("candidate"))
    assert u.grade == "unassessed" and not u.computable
    assert assess("empty", inputs=[]).grade == "unassessed"


def test_hard_errors_cannot_be_downgraded_to_b_by_assumptions():
    rec, _ = check_assumption("kappa", 0.95, ALLOWED)
    assert assess("x", inputs=_inputs(), hard_errors=["单位错误"], assumptions=[rec]).grade == "C"


@pytest.mark.parametrize("allowed, message", [
    ({}, "不在允许假设清单"),
    ({"kappa": {"range": [0.9, 1.0], "unit": "比例"}}, "缺少 rationale"),
])
def test_unlisted_or_incomplete_assumptions_are_not_allowed(allowed, message):
    _, err = check_assumption("kappa", 0.95, allowed)
    assert message in err


# ---- P0：EIA 接入 ----------------------------------------------------------------

class FakeSheet:
    def __init__(self, rows):
        self.rows, self.nrows, self.ncols = rows, len(rows), len(rows[0])

    def cell_value(self, r, c):
        return self.rows[r][c]


class FakeBook:
    datemode = 0

    def __init__(self, sheets):
        self.sheets = sheets

    def sheet_by_name(self, name):
        if name not in self.sheets:
            raise xlrd.XLRDError(f"No sheet named <{name}>")
        return self.sheets[name]

    def sheet_names(self):
        return list(self.sheets)


def _serial(day):
    return float((pd.Timestamp(day) - pd.Timestamp("1899-12-30")).days)


def sheet_rows(values, titles=TITLES, extra_week=None):
    """与 Data 1 相同的结构：首列原油净投入（更早开始），其后为三个所需序列。"""
    rows = [["Back to Contents", "Data 1: Refiner Inputs and Utilization", "", "", ""],
            ["Sourcekey", "WCRRIUS2", "WGIRIUS2", "WOCLEUS2", "WPULEUS3"],
            ["Date", "Weekly U.S. Refiner Net Input of Crude Oil  (Thousand Barrels per Day)",
             titles["WGIRIUS2"], titles["WOCLEUS2"], titles["WPULEUS3"]],
            [_serial("1982-08-20"), 11722.0, "", "", ""]]
    rows += [[_serial(d), 15000.0, g, k, u] for d, g, k, u in values]
    if extra_week is not None:
        rows.append(extra_week)
    return rows


@pytest.fixture
def eia_book(monkeypatch):
    holder = {"rows": sheet_rows(weekly_values())}
    monkeypatch.setattr(eia.xlrd, "open_workbook", lambda **kw: FakeBook({"Data 1": FakeSheet(holder["rows"])}))
    return holder


def eia_connector(body=XLS_MAGIC):
    return EiaPetXlsConnector(http_get=FakeHttp({f"{BASE_URL}/{FILE}": body}), **NO_RETRY)


def test_eia_locates_columns_by_sourcekey_and_keeps_gaps(registry, store, eia_book):
    r = ingest(registry, store, "eia_refinery_gross_inputs", {}, eia_connector())
    assert r.status == "created"
    df, v = store.load("eia_refinery_gross_inputs")
    assert set(df["series_id"]) == {"WGIRIUS2"} and set(df["unit"]) == {"thousand_barrels_per_day"}
    first = df.sort_values("observation_at").iloc[0]
    assert first.observation_at == pd.Timestamp("1982-08-20") and first.quality_status == "missing"
    ok = df[df.quality_status == "ok"]
    assert len(ok) == 52 and ok.observation_at.min() == WEEKS[0]
    assert v.series["WGIRIUS2"]["sourcekey"] == "WGIRIUS2" and v.raw_snapshots[0]["path"].endswith(".xls")
    # 周结束日的保守可用时间：观测日后第 7 天 0 点（美东）
    row = ok.iloc[0]
    assert row.available_at == pd.Timestamp("2025-01-10", tz="America/New_York").tz_convert("UTC")


def test_eia_rejects_changed_titles_error_pages_and_layout(registry, store, eia_book):
    eia_book["rows"] = sheet_rows(weekly_values(), titles={**TITLES, "WGIRIUS2": "Weekly U.S. Crude Oil Inputs"})
    r = ingest(registry, store, "eia_refinery_gross_inputs", {}, eia_connector())
    assert r.status == "failed" and "列标题" in r.message
    r = ingest(registry, store, "eia_refinery_gross_inputs", {}, eia_connector(b"<html>error</html>"))
    assert r.status == "failed" and "不是 .xls" in r.message
    eia_book["rows"] = sheet_rows(weekly_values(), extra_week=["Notes: revised", "", "", "", ""])
    r = ingest(registry, store, "eia_refinery_gross_inputs", {}, eia_connector())
    assert r.status == "failed" and "不是 Excel 日期" in r.message


# ---- P3a：研究分支 ---------------------------------------------------------------

def _load_all(registry, store):
    for ds in DATASETS.values():
        assert ingest(registry, store, ds, {}, eia_connector()).status == "created"


STATS = {
    "study_id": "refining_stats_test", "title": "测试", "question": "周度统计？", "result_type": "descriptive",
    "branch": "refining_throughput",
    "scope": {"market": "US", "activity": "petroleum_refining", "start": "2025-01-01", "end": "2025-12-31",
              "frequency": "weekly", "vintage_policy": "latest"},
    "data": dict(DATASETS), "method": {}, "limitations": ["测试数据"],
}
SCEN = {
    **STATS, "study_id": "refining_scen_test", "result_type": "simulation",
    "method": {"reference_window": ["2025-01-01", "2025-12-31"], "allowed_assumptions": ALLOWED,
               "scenarios": [{"id": "ok", "g": 0.1, "kappa": 1.0}, {"id": "tight", "g": 0.0, "kappa": 0.9},
                             {"id": "bad", "g": 0.1, "kappa": 1.05}]},
}


def _write(project, doc, name="refining.yaml"):
    path = project / "config" / "studies" / name
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


def _result(project, m):
    return json.loads((project / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))


def test_statistics_study_is_grade_a_complete_and_reproducible(project, registry, store, eia_book):
    _load_all(registry, store)
    m = run_study(project, _write(project, STATS))
    assert m["status"] == "success", m.get("error")
    r = _result(project, m)
    assert r["results"]["feasibility"]["weekly_statistics"]["grade"] == "A"
    assert r["coverage"]["completeness"] == "complete" and r["coverage"]["valid_weeks"] == 52
    assert r["validation"]["ratio_check"]["status"] == "pass" and r["validation"]["ratio_check"]["checked"] == 52
    assert r["results"]["statistics"]["capacity_values"] == [18000.0, 18100.0, 18200.0, 18300.0]
    assert verify_run(project, m["run_id"])["reproduced"]


def test_scenarios_are_b_blocked_c_and_flag_inconsistent_baselines(project, registry, store, eia_book):
    _load_all(registry, store)
    r = _result(project, run_study(project, _write(project, SCEN)))
    grades = {k: v["grade"] for k, v in r["results"]["feasibility"].items()}
    assert grades == {"weekly_statistics": "A", "scenario:ok": "B", "scenario:tight": "B", "scenario:bad": "C"}
    by_id = {s["id"]: s for s in r["results"]["scenarios"]}
    assert "mean_shortfall" not in by_id["bad"]  # 受阻情景不生成数值
    assert any(u["item"] == "情景 bad" for u in r["unsupported"])
    # kappa = 0.9：基准利用率高于 90% 的周不自洽，不计入缺口，也不把上限抬高
    above = sum(1 for _, g, k, _ in weekly_values() if g > 0.9 * k)
    assert above > 0 and by_id["tight"]["weeks_inconsistent"] == above
    assert by_id["tight"]["weeks_with_shortfall"] == 0  # g = 0 时其余周没有缺口
    ok = by_id["ok"]
    rows = [w for w in r["tables"]["scenario_weeks"] if w["scenario"] == "ok"]
    assert all(w["shortfall"] == pytest.approx(max(1.1 * w["gross_inputs"] - w["q_cap"], 0)) for w in rows)
    assert ok["weeks_evaluated"] == 52 and r["validation"]["baseline_check"]["status"] == "pass"


def test_missing_week_is_not_interpolated_and_blocks_full_period_claim(project, registry, store, eia_book):
    values = weekly_values()
    day, _, k, _ = values[10]
    values[10] = (day, "", k, "")
    eia_book["rows"] = sheet_rows(values)
    _load_all(registry, store)
    m = run_study(project, _write(project, STATS))
    r = _result(project, m)
    assert m["status"] == "partial" and r["coverage"]["completeness"] == "partial"
    assert r["coverage"]["missing_weeks"] == [day.date().isoformat()]
    assert r["results"]["statistics"]["weeks"] == 51
    assert any(u["item"] == "完整期间结论" for u in r["unsupported"])


def test_published_ratio_conflict_blocks_statistics(project, registry, store, eia_book):
    values = weekly_values()
    day, g, k, u = values[5]
    values[5] = (day, g, k, u + 0.3)  # 公布值与 G、K 不相容
    eia_book["rows"] = sheet_rows(values)
    _load_all(registry, store)
    r = _result(project, run_study(project, _write(project, SCEN)))
    assert r["validation"]["ratio_check"]["status"] == "fail"
    assert r["results"]["feasibility"]["weekly_statistics"]["grade"] == "C"
    assert r["results"]["statistics"] is None
    assert all(v["grade"] == "C" for k, v in r["results"]["feasibility"].items() if k.startswith("scenario:"))


def test_wrong_model_route_is_rejected(project, registry, store, eia_book):
    """行业代码或数据形状相似不能决定模型：炼油模板用于芯片活动时拒绝运行。"""
    _load_all(registry, store)
    doc = {**STATS, "scope": {**STATS["scope"], "activity": "semiconductor_foundry"}}
    m = run_study(project, _write(project, doc))
    assert m["status"] == "failed" and "适用范围不符" in m["error"]
    doc = {**STATS, "method": {"scenarios": [{"id": "x", "g": 0.1, "kappa": 1.0}]}}
    m = run_study(project, _write(project, doc, "desc_with_scenarios.yaml"))
    assert m["status"] == "failed" and "不能包含情景" in m["error"]


def _frame(series_id, unit, values):
    df = pd.DataFrame({c: None for c in SERIES_COLUMNS}, index=range(len(values)))
    df["series_id"], df["unit"], df["source_id"] = series_id, unit, "eia"
    df["observation_at"] = pd.to_datetime([d for d, _ in values])
    df["value"] = [v for _, v in values]
    df["quality_status"], df["reason"] = "ok", ""
    return df


def _version(ds):
    return DatasetVersion(dataset_id=ds, version_id=f"v-{ds}", schema_version="series.v1", content_hash="h",
                          created_at="", rows=0, path="", raw_snapshots=[], transform="", quality={})


def _direct_inputs(status="access_verified", capacity_unit="thousand_barrels_per_calendar_day"):
    vals = weekly_values()
    frames = {"inputs": _frame("WGIRIUS2", "thousand_barrels_per_day", [(d, g) for d, g, _, _ in vals]),
              "capacity": _frame("WOCLEUS2", capacity_unit, [(d, k) for d, _, k, _ in vals]),
              "utilization": _frame("WPULEUS3", "percent", [(d, u) for d, _, _, u in vals])}
    return {r: StudyInput(role=r, dataset_id=DATASETS[r], frame=f, version=_version(DATASETS[r]),
                          source_status=status) for r, f in frames.items()}


def test_wrong_units_are_hard_errors_and_unverified_sources_are_not_computed():
    study = parse_study(SCEN)
    r = refining_run(study, _direct_inputs(capacity_unit="thousand_barrels_per_day"), None)
    stats = r.results["feasibility"]["weekly_statistics"]
    assert stats["grade"] == "C" and "单位" in stats["reasons"][0] and r.results["statistics"] is None
    assert r.validation["ratio_check"]["status"] == "skipped"
    r = refining_run(study, _direct_inputs(status="candidate"), None)
    assert r.results["feasibility"]["weekly_statistics"]["grade"] == "unassessed"
    assert all(s["grade"] == "unassessed" for s in r.results["scenarios"])  # 输入未达接入已验证，情景也不计算
    assert r.results["statistics"] is None and not r.tables["scenario_weeks"]


def test_reference_window_coverage_is_recorded_separately(project, registry, store, eia_book):
    """研究期间在用途核验范围内，不代表参照窗口也在范围内：参照窗口单独记录并在清单中固定。"""
    _load_all(registry, store)
    doc = {**SCEN, "method": {**SCEN["method"], "reference_window": ["2015-01-01", "2025-12-31"]}}
    m = run_study(project, _write(project, doc))
    r = _result(project, m)
    util = next(i for i in m["inputs"] if i["role"] == "utilization")
    assert util["use_scope"]["status"] == "in_scope"  # 研究期间 2025 年
    ref = r["results"]["assumption_reference"]["use_scope"]
    assert ref["status"] == "partial" and ref["uncovered"] == [["2015-01-01", "2024-12-31"]]
    assert util["reference_scope"] == ref
    assert any("未覆盖 2015-01-01—2024-12-31" in x for x in r["limitations"])
    report = (project / next(o["path"] for o in m["outputs"] if o["path"].endswith(".md"))).read_text(encoding="utf-8")
    assert "部分在核验范围内（partial），未覆盖 2015-01-01—2024-12-31" in report
    assert verify_run(project, m["run_id"])["reproduced"]
    # 参照窗口完全在核验范围内时不追加限制
    r2 = _result(project, run_study(project, _write(project, SCEN, "in_scope.yaml")))
    assert r2["results"]["assumption_reference"]["use_scope"]["status"] == "in_scope"
    assert not any("假设参照期" in x for x in r2["limitations"])
