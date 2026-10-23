"""第二类研究：假设平价债券的利率敏感性情景；以及研究页展示组件的通用性。"""

import json
import shutil

import pytest
import yaml

from investment_os.analytics import bonds
from investment_os.runs import run_study, verify_run
from investment_os.site import build_site
from investment_os.site.renderers import UNSUPPORTED, get_renderer
from investment_os.site.study import chart_panel

from .conftest import PROJECT_ROOT

STUDY = {
    "study_id": "par_bond_test",
    "title": "测试情景",
    "question": "假设平价债券在收益率冲击下的价格变化？",
    "result_type": "simulation",
    "branch": "par_bond_scenarios",
    "scope": {"market": "US", "currency": "USD", "start": "2024-01-02", "end": "2024-01-05",
              "frequency": "daily", "vintage_policy": "latest"},
    "data": {"curve": "ust_par_yield_curve"},
    "method": {"tenors": ["2Y", "10Y", "30Y"], "coupon_frequency": 2, "shocks_bp": [-200, -100, 100, 200],
               "finite_difference_bp": 1},
    "benchmark": "完整重新定价",
    "limitations": ["测试数据"],
}


def _write(project, **over):
    path = project / "config" / "studies" / "par.yaml"
    path.write_text(yaml.safe_dump({**STUDY, **over}, allow_unicode=True), encoding="utf-8")
    return path


def _result(project, m):
    return json.loads((project / "runs" / m["run_id"] / "result.json").read_text(encoding="utf-8"))


# ---- 公共分析 ------------------------------------------------------------------

def test_par_bond_matches_closed_form_and_known_values():
    y = 0.04
    assert bonds.price(y, y, 10) == pytest.approx(100, abs=1e-9)
    d = bonds.modified_duration(y, y, 10)
    assert d == pytest.approx((1 - 1.02 ** -20) / 0.04, rel=1e-12)  # 封闭解
    assert d == pytest.approx(8.1757, abs=1e-4)
    assert bonds.macaulay_duration(y, y, 10) == pytest.approx(d * 1.02, rel=1e-12)
    assert bonds.convexity(y, y, 10) == pytest.approx(bonds.effective_convexity(y, y, 10), rel=1e-5)
    assert bonds.effective_duration(y, y, 10) == pytest.approx(d, rel=1e-6)
    assert bonds.par_modified_duration_closed_form(0.0, 5) == 5


def test_scenario_errors_follow_positive_convexity():
    for shock in (-200, -50, 50, 200):
        s = bonds.scenario(0.05, 0.05, 30, shock)
        assert s["duration_error_pp"] < 0  # 只用久期总是低估价格
        assert abs(s["duration_convexity_error_pp"]) < abs(s["duration_error_pp"])
    up = bonds.scenario(0.04, 0.04, 10, 100)
    assert up["full_pct"] == pytest.approx((bonds.price(0.04, 0.05, 10) / 100 - 1) * 100)


def test_fractional_periods_are_rejected():
    with pytest.raises(ValueError, match="整数个付息期"):
        bonds.price(0.04, 0.04, 1.25)


# ---- 研究分支 --------------------------------------------------------------------

def test_par_bond_study_end_to_end(loaded):
    m = run_study(loaded, _write(loaded))
    assert m["status"] == "success", m.get("error")
    r = _result(loaded, m)
    assert r["result_type"] == "simulation" and r["results"]["base_date"] == "2024-01-05"
    b10 = r["results"]["bonds"]["10Y"]
    assert b10["yield_pct"] == pytest.approx(4.05) and b10["price"] == pytest.approx(100)
    assert b10["modified_duration"] == pytest.approx(bonds.par_modified_duration_closed_form(0.0405, 10))
    checks = r["validation"]["closed_form_checks"]
    assert checks["status"] == "pass" and checks["checked"] == 12  # 3 个期限 × 4 项
    texts = " ".join(f["text"] for f in r["interpretation"]["items"])
    assert "10Y 假设平价债券" in texts and "期限越长，久期越大" in texts
    assert "只用久期时，所有期限与冲击下的估计都低于完整重新定价的价格" in texts
    assert r["interpretation"]["rule_version"] == "par_bond-findings.v1"
    # 情景研究的用途是 scenario：Treasury 的「描述性」用途核验不适用
    curve = next(i for i in m["inputs"] if i["role"] == "curve")
    assert curve["use"] == "scenario" and curve["source_status"] == "access_verified"
    assert "use_scope" not in curve
    assert verify_run(loaded, m["run_id"])["reproduced"] is True
    report = next((loaded / o["path"]).read_text() for o in m["outputs"] if o["path"].endswith("report.md"))
    assert "封闭解与重新定价核对" in report and "| 10Y 冲击 bp |" in report and "假设与输入" in report
    assert any(o["path"].endswith("scenario_price.png") for o in m["outputs"])


def test_closed_form_check_failure_is_reported(loaded, monkeypatch):
    monkeypatch.setattr(bonds, "convexity", lambda *a, **k: 1.0)  # 故意给出错误的解析凸性
    m = run_study(loaded, _write(loaded))
    r = _result(loaded, m)
    assert r["validation"]["closed_form_checks"]["status"] == "fail"
    assert m["status"] == "partial"


def test_missing_tenor_fails_explicitly(loaded):
    m = run_study(loaded, _write(loaded, method={**STUDY["method"], "tenors": ["10Y", "50Y"]}))
    assert m["status"] == "failed" and "50Y" in m["error"]


# ---- 门户：展示组件 --------------------------------------------------------------

def test_site_renders_scenario_study_with_its_own_components(loaded):
    from .test_study_e2e import write_study
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    run_study(loaded, write_study(loaded))  # 曲线研究
    m = run_study(loaded, _write(loaded))
    build_site(loaded, loaded / "_site")
    site = loaded / "_site"
    page = (site / "studies" / "par_bond_test" / "index.html").read_text(encoding="utf-8")
    for heading in ("研究问题", "关键发现", "可视化证据", "方法", "证据与限制", "历史与复现"):
        assert f"<h2>{heading}</h2>" in page
    assert "<h3 class=\"sub\">假设与输入</h3>" in page and "10Y 修正久期" in page
    assert "情景与策略模拟" in page and "假设情景，不是预测，也不是真实债券或基金的风险" in page
    assert "封闭解与重新定价核对" in page and "误差档位" in page
    # 不套用曲线研究的说明
    assert "倒挂" not in page and "不是预测或交易回测" not in page and "数据覆盖条" not in page
    assert "<th>基准日</th>" in page and "<th>10Y − 2Y 期末 bp</th>" not in page
    # 卡片与历史表统一为「最大绝对误差」，并注明对应的有符号误差
    assert "久期 + 凸性最大绝对误差" in page and "<th>最大绝对误差 pp</th>" in page
    assert "对应误差 −" in page or "对应误差 +" in page
    assert "最大误差</div>" not in page
    chart = json.loads((site / "runs" / m["run_id"] / "chart.json").read_text(encoding="utf-8"))
    assert chart["kind"] == "scenarios" and chart["focus"] == "10Y" and len(chart["scenarios"]["30Y"]) == 4
    curve_page = (site / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert "<h3 class=\"sub\">数据覆盖</h3>" in curve_page and "历史描述，不是预测或交易回测" in curve_page


def test_unknown_branch_uses_explicit_fallback():
    r = get_renderer("no_such_branch")
    assert r is UNSUPPORTED and not r.supported
    assert "暂无展示组件" in r.key_stats({}) and r.chart_data({}) is None
    panel = chart_panel("runs/x", [], r.figures, interactive=False)
    assert "data-src" not in panel and "该运行没有静态图" in panel
