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

    daily = json.loads((run_dir / "chart.json").read_text(encoding="utf-8"))
    assert daily["kind"] == "curve"
    assert daily["spreads"] == [{"key": "2Y-10Y", "label": "10Y − 2Y"}]
    assert [t["code"] for t in daily["tenors"]][:2] == ["1M", "2M"]
    assert daily["rows"][0]["date"] == "2024-01-02" and daily["rows"][0]["10Y"] == 3.95

    summary = json.loads((site / "summary.json").read_text(encoding="utf-8"))
    run = summary["runs"][0]
    assert run["run_id"] == latest["run_id"] and run["reproduced"] is True and run["history"] == 2
    assert run["findings"][0]["id"] == "level_10y"


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


def _visible_chinese(html: str) -> list[str]:
    """正文中未标为 lang="zh-CN" 的中文（语言切换链接除外）。"""
    import re

    body = html[html.index("<body"):]
    body = re.sub(r'<span lang="zh-CN">.*?</span>', "", body, flags=re.S)
    body = re.sub(r'<a class="lang-switch"[^>]*>.*?</a>', "", body)
    return re.findall(r".{0,20}[一-鿿　-〿＀-￯].{0,20}", body)


def test_english_pages_mirror_chinese_pages(loaded):
    """英文页面在 en/ 下镜像中文页面，共用根目录的资源与运行记录；页面顶端可以互相切换。"""
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    m = run_study(loaded, write_study(loaded))
    verify_run(loaded, m["run_id"])
    build_site(loaded, loaded / "_site")
    site = loaded / "_site"
    for page in ("index.html", "map.html", "methods.html", "studies/ust_curve_test/index.html"):
        assert (site / "en" / page).exists()
    zh_home = (site / "index.html").read_text(encoding="utf-8")
    en_home = (site / "en" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="zh-CN">' in zh_home and '<html lang="en">' in en_home
    assert '<a class="lang-switch" href="en/index.html" hreflang="en"' in zh_home
    assert '<a class="lang-switch" href="../index.html" hreflang="zh-CN"' in en_home
    assert 'href="../assets/style.css' in en_home and "Research framework" in en_home
    # 选过英文的读者打开中文地址时转到英文页面；?lang=zh 可以强制中文
    assert 'localStorage.getItem("lang")==="en"' in zh_home and "localStorage" not in en_home.split("</head>")[0]

    en_study = (site / "en" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert '<a class="lang-switch" href="../../../studies/ust_curve_test/"' in en_study
    assert f'src="../../../runs/{m["run_id"]}/figures/' in en_study and "Key findings" in en_study
    # 发现由英文措辞从同一结果生成；记录中的中文原文不改写
    assert "The 10-year yield rose from 3.95% to 4.05%" in en_study
    assert "10 年期收益率由 3.95% 升至 4.05%" in (site / "studies" / "ust_curve_test" / "index.html").read_text()
    for page in ("index.html", "map.html", "methods.html", "studies/ust_curve_test/index.html"):
        assert _visible_chinese((site / "en" / page).read_text(encoding="utf-8")) == [], page
    # 旧的历史页地址只在中文站点保留
    assert not (site / "en" / "history").exists()


def test_untranslated_record_text_is_marked_and_reported(loaded):
    """没有译文的记录文字在英文页面保留原文、标为中文，并在 summary.json 中列出。"""
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    run_study(loaded, write_study(loaded))
    build_site(loaded, loaded / "_site")
    en_study = (loaded / "_site" / "en" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert '<span lang="zh-CN">测试曲线</span>' in en_study  # 测试研究的标题没有译文
    summary = json.loads((loaded / "_site" / "summary.json").read_text(encoding="utf-8"))
    assert {"测试曲线", "2024 年初曲线如何变化？", "测试数据"} <= set(summary["untranslated"])


def test_site_content_has_english_text():
    """site/content.yaml 中显示在页面上的文字都有英文译文（与 site/en.yaml 一起维护）。"""
    import yaml

    from investment_os.site.i18n import has_cjk, load_phrases, tx, use

    content = yaml.safe_load((PROJECT_ROOT / "site" / "content.yaml").read_text(encoding="utf-8"))
    texts = [content["tagline"]] + [m["label"] for m in content["studies"].values()]
    for b in content["branches"]:
        texts += [b["name"], b["question"]]
        for d in b["directions"]:
            texts += [d["name"], d.get("summary", ""), d.get("needs", "")]
            texts += d.get("can_answer", []) + d.get("cannot_answer", [])
    for p in content["phases"]:
        texts += [p["name"], p["summary"]]
    for m in content["modules"]:
        texts += [m["name"], m["role"]]
    for g in content["guarantees"]:
        texts += [g["title"], g["detail"]]
    missing: set[str] = set()
    with use("en", load_phrases(PROJECT_ROOT), missing):
        for t in texts:
            tx(" ".join(str(t).split()) if t else t)
    assert not missing, sorted(missing)
    assert all(not has_cjk(x) for x in load_phrases(PROJECT_ROOT)["phrases"].values())


def test_english_findings_cover_every_rule():
    """英文页面的发现与记录一一对应；每条中文规则都有英文措辞。"""
    from investment_os.research.findings import par_bond_findings, rates_curve_findings
    from investment_os.site.findings_en import english_findings

    curve = {"branch": "rates_curve", "results": {
        "levels": {t: {"observations": 5, "start": 4.0, "end": 4.2, "change_bp": 20,
                       "start_date": "2024-01-02", "end_date": "2024-01-08"} for t in ("3M", "2Y", "10Y")},
        "spreads": {"2Y-10Y": {"observations": 5, "start": -10, "end": 5, "change_bp": 15,
                               "inversion": {"inverted_days": 2, "inverted_share": 0.4, "observations": 5,
                                             "zero_days": 1}}},
        "curvature": {"2Y/5Y/10Y": {"observations": 5, "start": -3, "end": -9, "change_bp": -6}}},
        "coverage": {"completeness": "gaps", "due_days": 6, "missing_days": 1}}
    recorded = rates_curve_findings(curve)
    en = english_findings(curve, recorded)
    assert [f["id"] for f in en] == [f["id"] for f in recorded] and all(f["translated"] for f in en)
    assert "turning from inverted to positive" in en[2]["text"] and "sank" in en[3]["text"]
    bond = {"branch": "par_bond_scenarios", "results": {
        "base_date": "2026-10-22",
        "bonds": {"2Y": {"coupon_pct": 4.0, "modified_duration": 1.9, "convexity": 4.6}},
        "scenarios": {"2Y": [{"shock_bp": 100, "full_pct": -1.85, "duration_pct": -1.9, "duration_error_pp": -0.05,
                              "duration_convexity_pct": -1.87, "duration_convexity_error_pp": -0.001}]}}}
    en = english_findings(bond, par_bond_findings(bond))
    assert all(f["translated"] for f in en) and en[0]["text"].startswith("A hypothetical 2Y par bond")
