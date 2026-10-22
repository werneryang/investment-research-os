"""贯通验证：取得 → 标准化 → 公共分析 → 报告与运行记录（architecture §10 P2）。"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from investment_os.cli import main
from investment_os.data import ingest
from investment_os.runs import run_study, verify_run

from .conftest import TREASURY_2024, dgs10_connector, treasury_connector

STUDY = {
    "study_id": "ust_curve_test",
    "title": "测试曲线",
    "question": "2024 年初曲线如何变化？",
    "result_type": "descriptive",
    "branch": "rates_curve",
    "scope": {"market": "US", "currency": "USD", "start": "2024-01-02", "end": "2024-01-05",
              "frequency": "daily", "vintage_policy": "latest"},
    "data": {"curve": "ust_par_yield_curve",
             "cross_check": {"dataset": "fred_dgs10", "required": False}},
    "method": {"key_tenors": ["3M", "2Y", "5Y", "10Y", "30Y"], "spreads": [["2Y", "10Y"]],
               "curvature": ["2Y", "5Y", "10Y"], "min_coverage": 0.95},
    "benchmark": "期初曲线",
    "limitations": ["测试数据"],
}


def write_study(project: Path, **overrides) -> Path:
    study = {**STUDY, **overrides}
    path = project / "config" / "studies" / "test.yaml"
    path.write_text(yaml.safe_dump(study, allow_unicode=True), encoding="utf-8")
    return path


def load_result(project: Path, manifest: dict) -> dict:
    return json.loads((project / "runs" / manifest["run_id"] / "result.json").read_text())


def test_full_run_matches_hand_calculation(loaded):
    manifest = run_study(loaded, write_study(loaded))
    assert manifest["status"] == "success", manifest.get("error")
    result = load_result(loaded, manifest)

    ten = result["results"]["levels"]["10Y"]
    assert (ten["start"], ten["end"]) == (3.95, 4.05)
    assert ten["change_bp"] == pytest.approx(10)
    assert (ten["min"], ten["min_date"]) == (3.91, "2024-01-03")

    s = result["results"]["spreads"]["2Y-10Y"]
    assert s["start"] == pytest.approx((3.95 - 4.33) * 100)
    assert s["end"] == pytest.approx((4.05 - 4.40) * 100)
    assert s["inversion"]["inverted_days"] == 4

    c = result["results"]["curvature"]["2Y/5Y/10Y"]
    assert c["start"] == pytest.approx((2 * 3.93 - 4.33 - 3.95) * 100)

    assert result["validation"]["cross_check"]["status"] == "pass"
    assert result["validation"]["cross_check"]["matched"] == 4
    assert result["validation"]["cross_check"]["independent"] is False
    assert result["validation"]["raw_spot_check"]["status"] == "pass"

    # 运行清单记录数据版本、代码与输出校验值
    assert {i["dataset_id"] for i in manifest["inputs"]} == {"ust_par_yield_curve", "fred_dgs10"}
    assert manifest["code"]["package_version"]
    paths = [o["path"] for o in manifest["outputs"]]
    assert any(p.endswith("report.html") for p in paths)
    assert any(p.endswith("report.md") for p in paths)
    html = next((loaded / p).read_text() for p in paths if p.endswith(".html"))
    assert "测试曲线" in html and "data:image/png;base64" in html


def test_run_is_reproducible_with_pinned_versions(loaded, registry, store):
    manifest = run_study(loaded, write_study(loaded))
    # 之后数据被修订，复现仍使用清单中的旧版本
    revised = TREASURY_2024.replace("01/05/2024,5.54", "01/05/2024,5.70").replace(",4.05,4.37", ",4.10,4.37")
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: revised}))
    record = verify_run(loaded, manifest["run_id"])
    assert record["reproduced"] is True
    # 用最新版本重新运行则结果不同
    rerun = run_study(loaded, write_study(loaded))
    assert rerun["result_hash"] != manifest["result_hash"]


def test_insufficient_coverage_limits_dependent_conclusions(loaded):
    path = write_study(loaded, method={**STUDY["method"], "key_tenors": ["2Y", "10Y", "6W"]})
    manifest = run_study(loaded, path)
    assert manifest["status"] == "partial"
    result = load_result(loaded, manifest)
    items = {u["item"] for u in result["unsupported"]}
    assert "期限 6W" in items
    assert "曲率 2Y/5Y/10Y" in items  # 5Y 不在关键期限内，曲率不输出
    assert "2Y-10Y" in result["results"]["spreads"]  # 不受影响的结论照常输出
    assert result["results"]["curvature"] == {}


def test_incomplete_period_is_disclosed(loaded):
    manifest = run_study(loaded, write_study(loaded, scope={**STUDY["scope"], "end": "2024-03-31"}))
    assert manifest["status"] == "partial"
    result = load_result(loaded, manifest)
    assert result["coverage"]["period_complete"] is False
    assert any("未能证明完整覆盖" in x for x in result["limitations"])


def test_missing_optional_input_skips_cross_check(project, registry, store):
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: TREASURY_2024}))
    manifest = run_study(project, write_study(project))
    assert manifest["status"] == "success"
    assert any("fred_dgs10" in w for w in manifest["warnings"])
    assert load_result(project, manifest)["validation"]["cross_check"]["status"] == "skipped"


def test_missing_required_input_fails_with_record(project):
    manifest = run_study(project, write_study(project))
    assert manifest["status"] == "failed"
    assert "iros fetch ust_par_yield_curve" in manifest["error"]
    saved = json.loads((project / "runs" / manifest["run_id"] / "manifest.json").read_text())
    assert saved["status"] == "failed"


def test_cli_run_and_verify(loaded, capsys):
    path = write_study(loaded)
    assert main(["--root", str(loaded), "run", str(path)]) == 0
    run_id = capsys.readouterr().out.split()[1]
    assert main(["--root", str(loaded), "verify", run_id]) == 0
    assert "reproduced" in capsys.readouterr().out
    assert main(["--root", str(loaded), "datasets"]) == 0
    assert "ust_par_yield_curve" in capsys.readouterr().out


def test_as_of_rejects_current_revision_not_held_at_the_time(loaded):
    """回归 F1：数据今天才取得，不能用于 2024 年的时点研究。"""
    scope = {**STUDY["scope"], "vintage_policy": "as_of", "as_of": "2024-01-04T05:00:00Z"}
    manifest = run_study(loaded, write_study(loaded, scope=scope))
    assert manifest["status"] == "failed"
    assert "只有当前修订版本" in manifest["error"]


class AtTime:
    """把接入器取得时间固定为某一时刻，模拟过去真实取得的快照。"""

    def __init__(self, inner, at):
        self.inner, self.at, self.name = inner, at, inner.name

    def fetch(self, dataset, request):
        payloads = self.inner.fetch(dataset, request)
        for p in payloads:
            p.retrieved_at = self.at
        return payloads

    def parse(self, dataset, payload):
        return self.inner.parse(dataset, payload)


def test_as_of_replays_snapshot_held_at_the_time(project, registry, store):
    """本地重放：使用当时已取得的版本，后来的修订不进入当时的视图。"""
    then = datetime(2024, 1, 4, 6, 0, tzinfo=timezone.utc)
    early = "\n".join(TREASURY_2024.splitlines()[0:1] + TREASURY_2024.splitlines()[3:5]) + "\n"
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           AtTime(treasury_connector({2024: early}), then), clock=lambda: then)
    revised = TREASURY_2024.replace("01/03/2024,5.54", "01/03/2024,5.99")
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: revised}))

    scope = {**STUDY["scope"], "end": "2024-01-03", "vintage_policy": "as_of",
             "as_of": "2024-01-04T12:00:00Z"}
    manifest = run_study(project, write_study(project, scope=scope,
                                              method={**STUDY["method"], "key_tenors": ["1M", "10Y"],
                                                      "spreads": [], "curvature": []}))
    assert manifest["status"] == "success", manifest.get("error")
    assert manifest["inputs"][0]["version_id"] == store.versions("ust_par_yield_curve")[0].version_id
    result = load_result(project, manifest)
    assert result["results"]["levels"]["1M"]["end"] == 5.54  # 当时的值，不是后来的 5.99


SPARSE = "\n".join([TREASURY_2024.splitlines()[0],
                    "12/31/2024,4.40,4.39,4.37,4.32,4.24,4.16,4.25,4.27,4.38,4.48,4.58,4.86,4.78",
                    TREASURY_2024.splitlines()[-1]]) + "\n"


def test_two_observations_in_a_year_is_not_complete(project, registry, store):
    """回归 F2：全年只剩首尾两日，不能报告为完整、成功。"""
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: SPARSE}))
    scope = {**STUDY["scope"], "start": "2024-01-01", "end": "2024-12-31"}
    manifest = run_study(project, write_study(project, scope=scope))
    assert manifest["status"] == "partial"
    result = load_result(project, manifest)
    cov = result["coverage"]
    assert cov["period_complete"] is False
    assert (cov["expected_days"], cov["curve_days"]) == (250, 2)
    assert cov["tenors"]["10Y"]["share"] == pytest.approx(2 / 250)
    assert {u["item"] for u in result["unsupported"]} >= {"期限 10Y", "期间统计（均值、极值、倒挂天数）"}
    assert result["results"]["levels"] == {}  # 期限覆盖不足，水平也不输出


def test_incomplete_period_keeps_endpoints_but_withholds_period_stats(loaded):
    # 数据只到 1 月 5 日，研究期间到 1 月 31 日；降低门槛使期限仍被支持，单独检验期间统计的限制
    scope = {**STUDY["scope"], "end": "2024-01-31"}
    method = {**STUDY["method"], "min_coverage": 0.15}  # 实际 4 / 预期 21 日
    manifest = run_study(loaded, write_study(loaded, scope=scope, method=method))
    assert manifest["status"] == "partial"
    result = load_result(loaded, manifest)
    assert result["coverage"]["period_complete"] is False
    assert result["coverage"]["expected_days"] == 21
    ten = result["results"]["levels"]["10Y"]
    assert (ten["start"], ten["end"], ten["change_bp"]) == (3.95, 4.05, pytest.approx(10))
    assert ten["mean"] is None and ten["min"] is None and ten["max"] is None
    assert result["results"]["spreads"]["2Y-10Y"]["inversion"] is None
    html = next((loaded / o["path"]).read_text() for o in manifest["outputs"]
                if o["path"].endswith(".html"))
    assert "未能证明完整" in html


def test_same_second_runs_do_not_overwrite(loaded):
    """回归 F4：同一秒启动的两次运行各自留档。"""
    fixed = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    m1 = run_study(loaded, write_study(loaded, title="第一次"), clock=lambda: fixed)
    m2 = run_study(loaded, write_study(loaded, title="第二次"), clock=lambda: fixed)
    assert m1["run_id"] != m2["run_id"]
    for m, title in ((m1, "第一次"), (m2, "第二次")):
        saved = json.loads((loaded / "runs" / m["run_id"] / "manifest.json").read_text())
        assert saved["study_config"]["title"] == title
        assert saved["result_hash"] == m["result_hash"]


def test_verify_keeps_originally_missing_optional_input_missing(project, registry, store):
    """回归 F5：原运行没有交叉核验数据，后来导入也不改变复现结果。"""
    ingest(registry, store, "ust_par_yield_curve", {"start": 2024, "end": 2024},
           treasury_connector({2024: TREASURY_2024}))
    manifest = run_study(project, write_study(project))
    unused = [i for i in manifest["inputs"] if not i["used"]]
    assert [i["role"] for i in unused] == ["cross_check"]
    ingest(registry, store, "fred_dgs10", {"start": "2024-01-01", "end": "2024-01-05"},
           dgs10_connector("2024-01-01", "2024-01-05"))
    assert verify_run(project, manifest["run_id"])["reproduced"] is True
