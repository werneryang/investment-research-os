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
    site = loaded / "_site"
    page = index.read_text(encoding="utf-8")
    # 首页以研究发现为主体：规则生成的发现、关键数字与证据摘要，链接到研究页
    assert "研究焦点" in page and "关键发现" in page
    assert "10 年期收益率由 3.95% 升至 4.05%" in page
    assert "3.95% → 4.05%" in page and "10Y − 2Y 利差" in page and "2Y–10Y" not in page
    assert "用途：历史描述，不是预测或交易回测" in page
    assert 'href="studies/ust_curve_test/"' in page
    # 系统状态在页脚；过期提示由脚本在过期时显示
    assert "data-built-at=" in page and 'class="stale"' in page and "系统状态" in page
    assert str(loaded) not in page
    assert (site / "assets" / "charts.js").exists() and (site / ".nojekyll").exists()

    study = (site / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    for heading in ("研究问题", "关键发现", "可视化证据", "方法", "证据与限制", "历史与复现"):
        assert f"<h2>{heading}</h2>" in study
    assert "依据" in study and "results.levels.10Y.change_bp" in study
    assert "同源一致性检查" in study and "不是独立验证" in study and "固定输入重算" in study
    assert 'class="coverage"' in study and "cov-ok" in study
    assert old["run_id"] in study and latest["run_id"] in study  # 无档案时历史列出全部运行
    run_dir = site / "runs" / latest["run_id"]
    for name in ("report.html", "manifest.json", "result.json", "daily.json", "figures/spreads.png"):
        assert (run_dir / name).exists()
    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert '<a href="../../index.html">' in report and "10Y − 2Y" in report and "a {" in report
    assert (site / "latest" / "ust_curve_test" / "report.html").exists()
    # 旧的历史页地址转到研究页的历史部分
    assert "studies/ust_curve_test/#history" in (site / "history" / "ust_curve_test.html").read_text()

    cap = (site / "map.html").read_text(encoding="utf-8")
    assert "美国国债收益率曲线" in cap and "规划，未开始" in cap
    methods = (site / "methods.html").read_text(encoding="utf-8")
    assert 'id="status"' in methods and "us_treasury_daily" in methods

    daily = json.loads((run_dir / "daily.json").read_text(encoding="utf-8"))
    assert daily["spreads"] == [{"key": "2Y-10Y", "label": "10Y − 2Y"}]
    assert [t["code"] for t in daily["tenors"]][:2] == ["1M", "2M"]
    assert daily["rows"][0]["date"] == "2024-01-02" and daily["rows"][0]["10Y"] == 3.95

    summary = json.loads((site / "summary.json").read_text(encoding="utf-8"))
    run = summary["runs"][0]
    assert run["run_id"] == latest["run_id"] and run["reproduced"] is True and run["history"] == 2
    assert run["findings"][0]["id"] == "level_10y"


def test_daily_json_keeps_gaps(loaded):
    from investment_os.site import daily_json as _daily_json
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
    assert "暂无研究运行记录" in page
    assert (project / "_site" / "map.html").exists() and (project / "_site" / "methods.html").exists()
