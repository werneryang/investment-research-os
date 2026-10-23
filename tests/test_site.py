"""项目网站、相对日期研究与 verify --all。"""

import json
import shutil
from datetime import date, datetime, timezone

from investment_os.cli import main
from investment_os.registry import resolve_relative_dates
from investment_os.runs import run_study, verify_run
from investment_os.site import build_site

from .conftest import PROJECT_ROOT
from .test_study_e2e import write_study


def test_relative_dates_resolve_once_and_are_frozen(loaded):
    raw = resolve_relative_dates({"scope": {"start": "today-1y", "end": "today", "frequency": "daily"}},
                                 date(2026, 10, 22))
    assert raw["scope"]["start"] == "2025-10-22" and raw["scope"]["end"] == "2026-10-22"
    assert raw["scope"]["relative_dates"] == {"start": "today-1y", "end": "today"}

    # 运行清单记录换算后的日期；之后复现不重新取「今天」
    path = write_study(loaded, scope={"market": "US", "currency": "USD", "start": "today-3d",
                                      "end": "today", "frequency": "daily", "vintage_policy": "latest"})
    fixed = datetime(2024, 1, 5, 23, 0, tzinfo=timezone.utc)
    manifest = run_study(loaded, path, clock=lambda: fixed)
    scope = manifest["study_config"]["scope"]
    assert (scope["start"], scope["end"]) == ("2024-01-02", "2024-01-05")
    assert verify_run(loaded, manifest["run_id"])["reproduced"] is True


def test_verify_all_cli(loaded, capsys):
    run_study(loaded, write_study(loaded))
    run_study(loaded, write_study(loaded, title="另一次"))
    assert main(["--root", str(loaded), "verify", "--all"]) == 0
    assert capsys.readouterr().out.count("[reproduced]") == 2


def test_build_site_from_runs(loaded):
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    old = run_study(loaded, write_study(loaded))
    latest = run_study(loaded, write_study(loaded))
    verify_run(loaded, latest["run_id"])

    index = build_site(loaded, loaded / "_site")
    page = index.read_text(encoding="utf-8")
    assert "测试曲线" in page
    assert "3.95% → 4.05%" in page  # 10Y 期初 → 期末
    # 利差显示名写明减法方向；核验标识说明范围
    assert "10Y − 2Y 利差" in page and "2Y–10Y" not in page
    assert "同源一致性检查 · 通过" in page and "固定输入重算 · 一致" in page
    assert "不是独立验证" in page
    # 研究运行状态与站点更新状态分开
    assert "本次运行 · 成功" in page and "data-built-at=" in page and 'class="stale"' in page
    # 首页指向稳定的最新报告与历史页
    assert 'href="latest/ust_curve_test/report.html"' in page
    assert 'href="history/ust_curve_test.html"' in page
    site = loaded / "_site"
    assert (site / "latest" / "ust_curve_test" / "report.html").exists()
    assert (site / "assets" / "charts.js").exists() and (site / "assets" / "style.css").exists()
    # 没有档案时，历史页列出全部运行
    history = (site / "history" / "ust_curve_test.html").read_text(encoding="utf-8")
    assert old["run_id"] in history and latest["run_id"] in history
    report = site / "runs" / latest["run_id"] / "report.html"
    text = report.read_text(encoding="utf-8")
    assert '<a href="../../index.html">' in text and "10Y − 2Y" in text and "a {" in text
    assert (report.parent / "figures" / "spreads.png").exists()
    assert (site / ".nojekyll").exists()
    assert str(loaded) not in page

    daily = json.loads((report.parent / "daily.json").read_text(encoding="utf-8"))
    assert daily["spreads"] == [{"key": "2Y-10Y", "label": "10Y − 2Y"}]
    assert [t["code"] for t in daily["tenors"]][:2] == ["1M", "2M"]
    assert daily["rows"][0]["date"] == "2024-01-02" and daily["rows"][0]["10Y"] == 3.95

    summary = json.loads((site / "summary.json").read_text(encoding="utf-8"))
    run = summary["runs"][0]
    assert run["run_id"] == latest["run_id"] and run["reproduced"] is True and run["history"] == 2


def test_daily_json_keeps_gaps(loaded):
    from investment_os.site import _daily_json
    result = {"results": {"levels": {"10Y": {}}, "spreads": {}, "curvature": {}},
              "tables": {"daily": [{"date": "2024-01-02", "10Y": 3.95}, {"date": "2024-01-03", "10Y": None}]}}
    assert _daily_json(result)["rows"][1]["10Y"] is None  # 缺失保持为空，不插值


def test_spread_display_labels():
    from investment_os.analytics.rates import curvature_label, spread_label
    assert spread_label("2Y-10Y") == "10Y − 2Y"
    assert spread_label("3M-10Y") == "10Y − 3M"
    assert curvature_label("2Y/5Y/10Y") == "2×5Y − 2Y − 10Y"


def test_site_without_runs(project):
    shutil.copytree(PROJECT_ROOT / "site", project / "site")
    page = build_site(project, project / "_site").read_text(encoding="utf-8")
    assert "暂无运行记录" in page
