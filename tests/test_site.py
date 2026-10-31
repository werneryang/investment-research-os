"""项目网站、相对日期研究与 verify --all。"""

import json
import shutil
from datetime import date, datetime, timezone

import pytest

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
    assert '<h2>按对象找</h2>' in page and '<h2>按问题找</h2>' in page
    assert page.count('data-filter="object"') == 7 and page.count('data-filter="question"') == 10
    assert '尚未分类' in page and '研究目录' in page
    assert '10 年期收益率由 3.95% 升至 4.05%' in page
    assert 'href="studies/ust_curve_test/"' in page
    assert 'data-record=' in page and '已执行的' in page
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
    assert "尚无研究（数据已接入）" not in cap
    assert "<h2>数据来源分组</h2>" in cap and "美国国债期限结构" in cap and "规划，未开始" in cap
    assert "<tr class='branch' id='markets_assets'>" in cap and "工具结构" in cap
    assert "研究模块渐进扩展 <span class=\"chip chip-partial\">部分完成</span>" in cap  # P3 已有两类研究
    methods = (site / "methods.html").read_text(encoding="utf-8")
    assert 'id="status"' in methods and "us_treasury_daily" in methods
    # 公开存档与本机定时快照分开说明；列出登记了定时取得的数据集
    assert "<th>公开存档</th>" in methods and "数据存档" not in methods
    assert "本机定时快照目前覆盖" in methods and "<code>fred_payems</code>" in methods

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
    assert by_id["ust_treasury"]["status"] == "use_verified" and by_id["imf"]["status"] == "candidate"
    assert by_id["yfinance"]["status"] == "docs_verified" and by_id["yfinance"]["datasets"] == []


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
    assert "尚未发布" in page
    assert (project / "_site" / "map.html").exists() and (project / "_site" / "methods.html").exists()


def test_site_refuses_unmanaged_output_and_protected_paths(project):
    shutil.copytree(PROJECT_ROOT / "site", project / "site")
    out = project / "documents"
    out.mkdir()
    sentinel = out / "unrelated.txt"
    sentinel.write_text("keep me")
    with pytest.raises(ValueError, match="未标记"):
        build_site(project, out)
    assert sentinel.read_text() == "keep me"
    for target in (project, project.parent, project / "data", project / "reports" / "site",
                   project / "config"):
        with pytest.raises(ValueError, match="重叠"):
            build_site(project, target)
    assert (project / "config" / "sources.yaml").exists()
    link = project / "linked-output"
    link.symlink_to(out, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        build_site(project, link)
    archive = project / "custom-archive"
    with pytest.raises(ValueError, match="重叠"):
        build_site(project, archive / "site", archive)
    assert sentinel.read_text() == "keep me"


def test_site_rebuilds_owned_output_but_preserves_extra_files(project):
    shutil.copytree(PROJECT_ROOT / "site", project / "site")
    out = project / "_site"
    out.mkdir()  # 新的空目录也可以使用
    build_site(project, out)
    (out / "index.html").write_text("old generated page")
    build_site(project, out)
    assert "尚未发布" in (out / "index.html").read_text()
    sentinel = out / "unrelated.txt"
    sentinel.write_text("keep me")
    with pytest.raises(ValueError, match="未登记"):
        build_site(project, out)
    assert sentinel.read_text() == "keep me"


def test_site_checks_integrity_again_and_preserves_previous_build(loaded):
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    m = run_study(loaded, write_study(loaded))
    verify_run(loaded, m["run_id"])
    out = loaded / "_site"
    build_site(loaded, out)
    page = (out / "studies" / m["study_id"] / "index.html").read_text()
    assert "保存产物完整性" in page
    previous = (out / "index.html").read_bytes()
    result_path = loaded / "runs" / m["run_id"] / "result.json"
    result = json.loads(result_path.read_text())
    result["results"]["levels"]["10Y"]["end"] = 99.99
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="产物完整性检查失败"):
        build_site(loaded, out)
    assert (out / "index.html").read_bytes() == previous


def test_site_restores_previous_build_if_install_fails(project, monkeypatch):
    from pathlib import Path

    shutil.copytree(PROJECT_ROOT / "site", project / "site")
    out = project / "_site"
    build_site(project, out)
    previous = (out / "index.html").read_bytes()
    rename = Path.rename

    def fail_install(path, target):
        if path.name == "site" and path.parent.name.startswith(".iros-site-"):
            raise OSError("simulated install failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_install)
    with pytest.raises(OSError, match="simulated install failure"):
        build_site(project, out)
    assert (out / "index.html").read_bytes() == previous


def _register_test_routes(root, multiple=False):
    import copy
    import yaml
    path = root / 'site' / 'content.yaml'
    content = yaml.safe_load(path.read_text())
    route = copy.deepcopy(content['studies']['ust_curve_2024']['routes'][0])
    routes = [route]
    if multiple:
        routes.append({**route, 'primary': False, 'object': 'macro', 'subject': 'policy'})
    content['studies']['ust_curve_test'] = {'routes': routes}
    path.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False))


def test_home_uses_paired_routes_and_stable_targets(loaded):
    shutil.copytree(PROJECT_ROOT / 'site', loaded / 'site')
    _register_test_routes(loaded)
    run_study(loaded, write_study(loaded))
    page = build_site(loaded, loaded / '_site').read_text()
    assert 'href="studies/ust_curve_test/#curve"' in page
    summary = json.loads((loaded / '_site/summary.json').read_text())
    record = next(r for r in summary['classification']['studies'] if r['id'] == 'ust_curve_test')
    assert record['routes'][0]['available'] is True
    assert record['routes'][0]['object'] == 'assets'
    study = (loaded / '_site/studies/ust_curve_test/index.html').read_text()
    assert study.count('id="curve"') == 1


def _item(validation=None, ver=None, inputs=(), unsupported=(), cutoff="2026-10-30"):
    return {"result": {"validation": validation or {}, "unsupported": list(unsupported), "data_cutoff": cutoff},
            "verification": ver, "manifest": {"inputs": list(inputs)}}


def _scope(status, uncovered, verified):
    return {"status": status, "uncovered": uncovered, "verified_ranges": verified}


def test_notices_separate_failures_gaps_and_boundaries():
    """先拆事实再定级别：检查失败为 fail，前段或中段的核验缺口为 warn，维护周期内的尾端与研究边界为 info。"""
    from investment_os.site.catalog import notices
    ok = _item({"raw_spot_check": {"checked": 12, "status": "pass"}}, {"reproduced": True})
    assert notices(ok) == []
    tail = {"dataset_id": "ust", "use_scope": _scope("partial", [["2026-10-23", "2026-10-30"]], [["1990-01-02", "2026-10-22"]])}
    head = {"dataset_id": "cpi", "use_scope": _scope("partial", [["1928-01-01", "1947-11-30"]], [["1947-12-01", None]])}
    head2 = {"dataset_id": "dtb3", "use_scope": _scope("partial", [["1928-01-01", "1947-11-30"]], [["1947-12-01", None]])}
    bad = _item({"ratio_check": {"status": "fail"}}, {"reproduced": False}, [tail, head, head2],
                [{"item": "因果关系", "reason": "事后描述", "kind": "scope"}])
    daily = {"ust": "daily", "cpi": "monthly", "dtb3": "daily"}
    assert [(n.level, n.text) for n in notices(bad, daily)] == [
        ("fail", "1 项数据检查未通过"), ("fail", "固定输入重算不一致"),
        ("info", "用途核验未覆盖最新数据：ust（2026-10-23 至 2026-10-30）"),
        ("warn", "用途核验未覆盖部分研究期间：cpi、dtb3（1928-01-01 至 1947-11-30）"),
        ("info", "1 项问题不在本研究回答范围内")]
    assert [n.brief for n in notices(bad, daily)][2:4] == ["1 项输入的用途核验未覆盖最新数据", "2 项输入的用途核验未覆盖部分研究期间"]
    # 数据截止日之后的期间不影响结果，不提示
    after = {"dataset_id": "ff3", "use_scope": _scope("partial", [["2026-01-01", "2026-10-30"]], [["1926-07-01", "2025-12-31"]])}
    assert notices(_item(ver={"reproduced": True}, inputs=[after], cutoff="2025-12-31")) == []
    # 月份截止日按月末比较
    month = {"dataset_id": "ff3", "use_scope": _scope("partial", [["2026-08-15", "2026-10-30"]], [["1926-07-01", "2026-08-14"]])}
    assert [n.level for n in notices(_item(ver={"reproduced": True}, inputs=[month], cutoff="2026-08"), {"ff3": "monthly"})] == ["info"]
    out = {"dataset_id": "x", "use_scope": _scope("out_of_scope", [["2001-01-01", "2002-01-01"]], [["2010-01-01", None]])}
    assert [n.level for n in notices(_item(ver={"reproduced": True}, inputs=[out]))] == ["warn"]


def test_tail_gap_is_routine_only_within_the_maintenance_cycle():
    """只缺尾端的核验，滞后在维护周期内才降为 info；滞后多年或频率不明都保留 warn。"""
    from investment_os.site.catalog import notices
    years = {"dataset_id": "ust", "use_scope": _scope("partial", [["2021-01-01", "2026-10-22"]], [["1990-01-02", "2020-12-31"]])}
    item = _item(ver={"reproduced": True}, inputs=[years], cutoff="2026-10-22")
    assert [(n.level, n.brief) for n in notices(item, {"ust": "daily"})] == [("warn", "1 项输入的用途核验滞后超过维护周期")]
    tail = {"dataset_id": "ust", "use_scope": _scope("partial", [["2026-10-23", "2026-10-30"]], [["1990-01-02", "2026-10-22"]])}
    item = _item(ver={"reproduced": True}, inputs=[tail])
    assert [n.level for n in notices(item, {"ust": "daily"})] == ["info"]
    assert [n.level for n in notices(item)] == ["warn"]  # 频率不明，不能确认是例行滞后


def test_withheld_conclusions_are_graded_by_their_recorded_reason():
    """数据或输入不足而未输出的结论为 warn 并列出；研究不回答的问题为 info；旧结果没有分类时不推断原因。"""
    from investment_os.site.catalog import notices
    item = _item(ver={"reproduced": True}, unsupported=[
        {"item": "完整期间结论", "reason": "40 周缺少至少一个数值", "kind": "data"},
        {"item": "因果关系", "reason": "事后描述", "kind": "scope"}])
    assert [(n.level, n.text, n.brief) for n in notices(item)] == [
        ("warn", "因数据或输入不足未输出：完整期间结论", "1 项结论因数据或输入不足未输出"),
        ("info", "1 项问题不在本研究回答范围内", "1 项问题不在本研究回答范围内")]
    old = _item(ver={"reproduced": True}, unsupported=[{"item": "x", "reason": "y"}])
    assert [(n.level, n.text) for n in notices(old)] == [("info", "1 项结论未输出，原因见研究页")]


def test_check_note_does_not_turn_missing_checks_into_pass():
    """没有警告不等于检查通过：未执行、跳过与部分重算都要写明。"""
    from investment_os.site.catalog import check_note
    ok = _item({"raw_spot_check": {"checked": 12, "status": "pass"}}, {"reproduced": True, "scope": "full"})
    assert check_note(ok) == "已执行的 2 项检查通过"
    missing = _item({"raw_spot_check": {"status": "skipped"}, "ratio_check": {"status": "pass"},
                     "filing_review": {"status": "skipped"}})
    assert check_note(missing) == "已执行的 1 项检查通过；未执行：原始快照抽查、固定输入重算、另 1 项检查"
    assert check_note(_item(ver={"reproduced": True, "scope": "partial"})) == "暂无通过的检查；部分执行：固定输入重算"


def test_home_lists_each_study_once(loaded):
    shutil.copytree(PROJECT_ROOT / 'site', loaded / 'site')
    _register_test_routes(loaded, multiple=True)
    run_study(loaded, write_study(loaded))
    page = build_site(loaded, loaded / '_site').read_text()
    assert page.count('<h3><a href="studies/ust_curve_test/">') == 1
    summary = json.loads((loaded / '_site/summary.json').read_text())
    records = [r for r in summary['classification']['studies'] if r['id'] == 'ust_curve_test']
    assert len(records) == 1 and len(records[0]['routes']) == 2


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
    """Check text nodes; attributes contain bilingual query data, not displayed text."""
    import re
    from html.parser import HTMLParser

    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.text = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            skip = tag in ('script', 'style', 'head') or attrs.get('lang') == 'zh-CN' and tag != 'html' or attrs.get('class') == 'lang-switch'
            if tag not in ('meta', 'link', 'input', 'br', 'hr', 'img', 'source'):
                self.stack.append((tag, skip or any(v for _, v in self.stack)))
        def handle_endtag(self, tag):
            for i in range(len(self.stack)-1, -1, -1):
                if self.stack[i][0] == tag:
                    self.stack = self.stack[:i]
                    break
        def handle_data(self, data):
            if not any(v for _, v in self.stack): self.text.append(data)
    parser = Text(); parser.feed(html)
    return re.findall(r'.{0,20}[一-鿿　-〿＀-￯].{0,20}', ''.join(parser.text))


def test_english_pages_mirror_chinese_pages(loaded):
    """英文页面在 en/ 下镜像中文页面，共用根目录的资源与运行记录；页面顶端可以互相切换。"""
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    m = run_study(loaded, write_study(loaded))
    verify_run(loaded, m["run_id"])
    build_site(loaded, loaded / "_site")
    site = loaded / "_site"
    for page in ("index.html", "map.html", "sources.html", "methods.html", "studies/ust_curve_test/index.html"):
        assert (site / "en" / page).exists()
    zh_home = (site / "index.html").read_text(encoding="utf-8")
    en_home = (site / "en" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="zh-CN">' in zh_home and '<html lang="en">' in en_home
    assert '<a class="lang-switch" href="en/index.html" hreflang="en"' in zh_home
    assert '<a class="lang-switch" href="../index.html" hreflang="zh-CN"' in en_home
    assert 'href="../assets/style.css' in en_home and "Browse by object" in en_home
    # 选过英文的读者打开中文地址时转到英文页面；?lang=zh 可以强制中文
    assert 'localStorage.getItem("lang")==="en"' in zh_home and "localStorage" not in en_home.split("</head>")[0]

    en_study = (site / "en" / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    zh_study = (site / "studies" / "ust_curve_test" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="alternate" hreflang="en" href="../../studies/ust_curve_test/">' in en_study
    assert '<link rel="alternate" hreflang="zh-CN" href="../../studies/ust_curve_test/">' in zh_study
    assert '<a class="lang-switch" href="../../../studies/ust_curve_test/"' in en_study
    assert f'src="../../../runs/{m["run_id"]}/figures/' in en_study and "Key findings" in en_study
    # 发现由英文措辞从同一结果生成；记录中的中文原文不改写
    assert "The 10-year yield rose from 3.95% to 4.05%" in en_study
    assert "10 年期收益率由 3.95% 升至 4.05%" in (site / "studies" / "ust_curve_test" / "index.html").read_text()
    for page in ("index.html", "map.html", "sources.html", "methods.html", "studies/ust_curve_test/index.html"):
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
    texts = [content["tagline"]] + [m["label"] for m in content["studies"].values() if "label" in m]
    for b in content["data_groups"]:
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


def test_not_fetched_reason_comes_from_the_registry():
    """有意不在 CI 中取得的数据集写明原因；应取得却没取得的才显示「本次构建未取得」。"""
    from investment_os.registry import Registry
    from investment_os.site.collect import not_fetched_label, skip_reason
    from investment_os.site.i18n import use

    reg = Registry.load(PROJECT_ROOT)
    reason = {d.id: skip_reason(d.connector, reg.sources[d.source_id].signup, d.scheduled_fetch is not None)
              for d in reg.datasets.values()}
    assert reason["alfred_gdp"] == "key" and reason["manual_example"] == "manual"
    assert reason["fred_dff"] is None and reason["ust_par_yield_curve"] is None
    assert skip_reason("fred_graph_csv", "none", False) == "unscheduled"
    assert not_fetched_label("key") == "需要 API key，只在本机取得"
    assert not_fetched_label(None) == "本次构建未取得" and not_fetched_label(None, short=True) == "未取得"
    with use("en", {"phrases": {}, "patterns": []}, set()):
        assert not_fetched_label("manual") == "manual import, not fetched automatically"


def test_edgar_rows_say_why_ci_has_no_data_and_cards_list_them(loaded):
    """CI 中没有 SEC 财报数据：数据页写明原因（需要联系邮箱，只在本机取得）；资源卡片列出两个数据集，
    不再显示「来源说明，未登记数据集」；只核验了说明的来源（yfinance）仍显示这一标签。"""
    shutil.copytree(PROJECT_ROOT / "site", loaded / "site")
    build_site(loaded, loaded / "_site")
    methods = (loaded / "_site" / "methods.html").read_text(encoding="utf-8")
    assert "<strong>edgar_fsds</strong>" in methods and "<strong>edgar_companyfacts</strong>" in methods
    assert "需要联系邮箱（SEC_USER_AGENT），只在本机取得" in methods
    src = (loaded / "_site" / "sources.html").read_text(encoding="utf-8")
    card = src[src.index('id="src-sec_edgar"'):]
    card = card[:card.index("</article>")]
    assert "edgar_fsds" in card and "edgar_companyfacts" in card and "未登记数据集" not in card
    yf = src[src.index('id="src-yfinance"'):]
    assert "来源说明，未登记数据集" in yf[:yf.index("</article>")]
    cap = (loaded / "_site" / "map.html").read_text(encoding="utf-8")
    row = cap[cap.index("公司财报</strong>"):]
    row = row[:row.index("</tr>")]
    assert "edgar_fsds" in row and "规划，未开始" not in row


def test_edgar_rows_with_local_data(project):
    """本机有财报数据时，行数、申报数与最近一次同步来自 data/edgar 的目录。"""
    import pandas as pd

    from investment_os.contracts import FACT_COLUMNS, FILING_COLUMNS
    from investment_os.data.fundamentals import EdgarStore
    from investment_os.registry import Registry
    from investment_os.site.capability import direction_status
    from investment_os.site.collect import fundamentals_datasets

    store = EdgarStore(project)
    at = datetime(2026, 10, 24, 21, tzinfo=timezone.utc)
    facts = pd.DataFrame([["A-1", 320193, "us-gaap", "Revenues", pd.NaT, pd.Timestamp("2024-09-30"), 4, "USD", 1.0,
                           pd.Timestamp("2024-11-02", tz="UTC"), "fsds", pd.Timestamp(at)]], columns=FACT_COLUMNS)
    filings = pd.DataFrame([["A-1", 320193, "Apple", "10-K", 2024, "FY", pd.Timestamp("2024-09-30"), "0926",
                             pd.Timestamp("2024-11-01"), pd.Timestamp("2024-11-01 20:00", tz="UTC"), False, "3571",
                             "fsds", pd.Timestamp(at)]], columns=FILING_COLUMNS)
    store.write_partition("facts", "fsds", "2024q4", facts, {"companies": "x"}, at)
    store.write_partition("filings", "fsds", "2024q4", filings, {"companies": "x"}, at)
    store._log("fsds_remote.jsonl", {"quarter": "2024q4", "checked_at": at.isoformat(), "action": "unchanged"})
    rows = {r["dataset_id"]: r for r in fundamentals_datasets(Registry.load(project), project)}
    fsds = rows["edgar_fsds"]
    assert fsds["rows"] == 1 and fsds["status_counts"]["filings"] == 1 and fsds["status_counts"]["companies"] == 15
    assert fsds["last_fetch"] == {"status": "unchanged", "at": at.isoformat()} and fsds["status"] == "access_verified"
    assert rows["edgar_companyfacts"]["version_id"] is None  # 没有同步过 Company Facts
    st = direction_status({"datasets": ["edgar_fsds", "edgar_companyfacts"]}, Registry.load(project), rows, {})
    assert st["category"] == "data_only"
