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
    # 首页先列六个分支的总览（规划中的分支链接到能力地图），再列已有研究；每项研究只有一句发现与用途
    assert "<h2>研究框架</h2>" in page and page.count('class="branch-tile') == 6
    assert '<li class="branch-tile planned"><a href="map.html#sectors_regions">地区与行业</a>' in page
    assert "每项研究的形成：" in page and "研究焦点" in page
    assert "未归入研究方向的研究" in page  # 测试研究不在 content.yaml 的任何方向中
    assert "10 年期收益率由 3.95% 升至 4.05%" in page
    assert "关键发现" not in page and "stat-value" not in page  # 指标卡片与发现列表只在研究页
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
    for name in ("report.html", "manifest.json", "result.json", "chart.json", "figures/spreads.png"):
        assert (run_dir / name).exists()
    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert '<a href="../../index.html">' in report and "10Y − 2Y" in report and "a {" in report
    assert (site / "latest" / "ust_curve_test" / "report.html").exists()
    # 旧的历史页地址转到研究页的历史部分
    assert "studies/ust_curve_test/#history" in (site / "history" / "ust_curve_test.html").read_text()

    cap = (site / "map.html").read_text(encoding="utf-8")
    assert "<h2>研究分支与方向</h2>" in cap and "美国国债期限结构" in cap and "规划，未开始" in cap
    assert "<tr class='branch' id='markets_assets'>" in cap and "工具结构" in cap
    assert "研究模块渐进扩展 <span class=\"chip chip-partial\">部分完成</span>" in cap  # P3 已有两类研究
    methods = (site / "methods.html").read_text(encoding="utf-8")
    assert 'id="status"' in methods and "us_treasury_daily" in methods

    # 资源目录：已接入与候选来源同在一处，候选标明未核验；方向链接到能力地图的分支
    src = (site / "sources.html").read_text(encoding="utf-8")
    assert '<a href="sources.html" aria-current="page">数据资源目录</a>' in src
    assert 'id="src-ust_treasury"' in src and 'id="src-ken_french"' in src and "未经核验" in src
    assert "ust_par_yield_curve</code> 接入已验证；用途已验证：历史描述" in src
    assert 'href="map.html#markets_assets" title="市场与大类资产">美国国债期限结构</a>' in src
    assert "<h2>能力缺口</h2>" in src and "完整历史期权链" in src
    assert 'href="sources.html"' in page  # 其他页面的导航也有资源目录

    daily = json.loads((run_dir / "chart.json").read_text(encoding="utf-8"))
    assert daily["kind"] == "curve"
    assert daily["spreads"] == [{"key": "2Y-10Y", "label": "10Y − 2Y"}]
    assert [t["code"] for t in daily["tenors"]][:2] == ["1M", "2M"]
    assert daily["rows"][0]["date"] == "2024-01-02" and daily["rows"][0]["10Y"] == 3.95

    summary = json.loads((site / "summary.json").read_text(encoding="utf-8"))
    run = summary["runs"][0]
    assert run["run_id"] == latest["run_id"] and run["reproduced"] is True and run["history"] == 2
    assert run["findings"][0]["id"] == "level_10y"
    by_id = {x["id"]: x for x in summary["sources"]}
    assert by_id["ust_treasury"]["status"] == "use_verified" and by_id["shiller"]["status"] == "candidate"
    assert by_id["sec_edgar"]["status"] == "docs_verified" and by_id["sec_edgar"]["datasets"] == []


def test_daily_json_keeps_gaps(loaded):
    from investment_os.site.renderers import CURVE
    _daily_json = CURVE.chart_data
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


def test_home_places_studies_in_their_branch(loaded):
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    content = loaded / "site" / "content.yaml"
    text = content.read_text(encoding="utf-8")
    assert "studies: [ust_curve_last_year, ust_curve_2024]" in text
    content.write_text(text.replace("studies: [ust_curve_last_year, ust_curve_2024]", "studies: [ust_curve_test]"),
                       encoding="utf-8")
    run_study(loaded, write_study(loaded))
    page = build_site(loaded, loaded / "_site").read_text(encoding="utf-8")
    card = page[page.index('id="markets_assets"'):]
    card = card[:card.index("</article>")]
    assert "研究焦点" in card and 'href="studies/ust_curve_test/"' in card and "美国国债期限结构" in card
    # 分支写明具体覆盖，不用一个「已有研究」概括整个分支
    assert "6 个方向：1 个已有研究，1 个只有数据；规划中：股票 · 信用 · 波动率 · 跨市场比较" in card
    assert "未归入研究方向的研究" not in page
    # 已有研究的分支排在只有数据的分支之前
    assert page.index('id="markets_assets"') < page.index('id="macro_policy"')


def test_home_caveats_show_only_exceptions():
    from investment_os.site.home import _caveats
    ok = {"result": {"validation": {"raw_spot_check": {"checked": 12, "status": "pass"}}},
          "verification": {"reproduced": True}, "manifest": {"inputs": []}}
    assert _caveats(ok) == []
    bad = {"result": {"validation": {}, "unsupported": ["x"]}, "verification": {"reproduced": False},
           "manifest": {"inputs": [{"dataset_id": "ust", "use_scope": {"status": "partial",
                                                                     "uncovered": [["2026-10-23", "2026-10-23"]]}}]}}
    assert _caveats(bad) == ["固定输入重算不一致", "用途核验部分在范围内（ust 范围外：2026-10-23）",
                             "1 项结论因数据不足不输出"]


def test_shared_data_lists_only_directions_with_runs():
    from investment_os.site.home import _shared_data
    dirs = [({"name": "期限结构", "datasets": ["ust"]}, {"runs": [1]}),
            ({"name": "利率敏感性", "datasets": ["ust"]}, {"runs": [1]}),
            ({"name": "规划", "datasets": ["ust"]}, {"runs": []})]
    html = _shared_data(dirs)
    assert "同时支撑「期限结构」「利率敏感性」" in html and "规划" not in html
    assert _shared_data(dirs[:1]) == ""


def test_charts_are_static_first_and_self_hosted(loaded):
    """静态图默认可见、交互图表区默认隐藏；Chart.js 随站点托管，不引用外部 CDN。"""
    import base64
    import hashlib
    import re

    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    m = run_study(loaded, write_study(loaded))
    build_site(loaded, loaded / "_site")
    site = loaded / "_site"
    home = (site / "index.html").read_text(encoding="utf-8")
    study = (site / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    run = f"runs/{m['run_id']}"
    assert "chart-panel" not in home and "chart.umd" not in home  # 图表只在研究页
    for page, prefix, figs in ((study, "../../", ("curve_snapshots.png", "key_tenors.png", "spreads.png")),):
        panel = re.search(r'<div class="chart-panel".*?</p></div>', page, re.S).group(0)
        static = re.search(r'<div class="chart-static figs">(.*?)</div>', panel, re.S).group(1)
        for f in figs:
            assert f'src="{prefix}{run}/figures/{f}"' in static
        assert '<div class="interactive" hidden></div>' in panel
        assert re.search(rf'<script defer src="{prefix}assets/vendor/chart\.umd\.min\.js\?v=[0-9a-f]{{10}}"></script>', page)
        assert re.search(rf'<link rel="stylesheet" href="{prefix}assets/style\.css\?v=[0-9a-f]{{10}}">', page)
        assert "cdnjs" not in page and "cdn.jsdelivr" not in page
    vendored = (site / "assets" / "vendor" / "chart.umd.min.js").read_bytes()
    sri = "sha512-" + base64.b64encode(hashlib.sha512(vendored).digest()).decode()
    readme = (PROJECT_ROOT / "site" / "assets" / "vendor" / "README.md").read_text(encoding="utf-8")
    assert sri in readme  # 托管文件与登记的来源校验值一致
    # 回退提示只在确有静态图时才说「以下为静态图」
    js = (site / "assets" / "charts.js").read_text(encoding="utf-8")
    assert "hasStatic ?" in js and "已显示静态图" not in js
